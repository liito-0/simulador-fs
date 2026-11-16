"""Árvore de diretórios/arquivos + operações CRUD."""
import hashlib

from disk import DiskError, fmt_bytes
from allocation import STRATEGIES
from io_request import IORequest
from raid import RAIDError
from seguranca import Seguranca
import acl
import cripto


class FSError(Exception):
    pass


class Node:
    def __init__(self, name, parent=None):
        self.name, self.parent = name, parent
        self.owner, self.group = "root", "admin"   # preenchidos pelo FS a partir da sessão
        self.mode = 0o755 if parent is None else 0o755


class Directory(Node):
    def __init__(self, name, parent=None):
        super().__init__(name, parent)
        self.children = {}


class File(Node):
    def __init__(self, name, parent, size, strategy):
        super().__init__(name, parent)
        self.size, self.strategy = size, strategy
        self.alloc = {"inode": None, "data": []}
        self.mode = 0o644
        self.cripto = None


class FileSystem:
    def __init__(self, disk, strategy="indexada", seguranca=None):
        if disk.total_blocks < 1:
            raise FSError("O disco precisa de ao menos 1 bloco.")
        # Sem `seguranca`, uso programático: sessão root em MODO_KERNEL (compatível com Etapas 1-2).
        # O shell passa uma instância sem sessão e exige login.
        self.sec = seguranca or Seguranca(autologin_root=True)
        self.disk = disk
        self.strategy = strategy
        self.io_queue = []
        self.device = "hdd"      # "hdd" (fila + braço), "ssd" (páginas) ou "raid5"
        self.ssd = None          # instância de SSD, usada quando device == "ssd"
        self.raid = None         # instância de RAID5, usada quando device == "raid5"
        self.dev_log = []        # eventos de E/S do SSD/RAID (texto) para o shell exibir
        self.root = Directory("")
        self.root.mode = 0o755
        self.cwd = self.root
        self.integridade = {}
        disk.set_block(0, "INODE_RAIZ", self.root, detalhe="Diretório '/'")

    # ---------- identidade ----------
    def _atribuir_dono(self, node):
        """Novo nó pertence ao usuário efetivo da sessão e ao grupo primário dele."""
        u = self.sec.efetivo
        node.owner, node.group = u.nome, u.grupo
        return node

    # ---------- caminhos (absolutos e relativos) ----------
    def path_of(self, node):
        parts = []
        while node.parent is not None:
            parts.append(node.name)
            node = node.parent
        return "/" + "/".join(reversed(parts))

    def _parts(self, path):
        if not path:
            raise FSError("Caminho vazio.")
        return (self.root if path.startswith("/") else self.cwd), [p for p in path.split("/") if p]

    def _step(self, node, p):
        if p == ".":
            return node
        if p == "..":
            return node.parent or node
        if not isinstance(node, Directory):
            raise FSError(f"'{node.name}' não é um diretório.")
        if p not in node.children:
            raise FSError(f"'{p}' não encontrado em '{self.path_of(node)}'.")
        return node.children[p]

    def resolve(self, path):
        node, parts = self._parts(path)
        for p in parts:
            node = self._step(node, p)
        return node

    def resolve_parent(self, path):
        node, parts = self._parts(path)
        if not parts or parts[-1] in (".", ".."):
            raise FSError(f"Nome inválido em '{path}'.")
        for p in parts[:-1]:
            node = self._step(node, p)
        if not isinstance(node, Directory):
            raise FSError("O caminho pai não é um diretório.")
        return node, parts[-1]

    def all_files(self, node=None):
        node = node or self.root
        for c in node.children.values():
            if isinstance(c, File):
                yield c
            else:
                yield from self.all_files(c)

    def _enqueue_io(self, op, node):
        alloc = node.alloc
        blocks = ([alloc["inode"]] if alloc["inode"] is not None else []) + alloc["data"]
        owner = self.path_of(node)
        if self.device == "ssd" and self.ssd is not None:
            self._io_ssd(op, blocks, owner)   # SSD: sem braço, sem fila de trilhas
            return
        if self.device == "raid5" and self.raid is not None:
            self._io_raid(op, node, owner)
            return
        self.io_queue.extend(
            IORequest(op, block, self.disk.track_of(block), owner) for block in blocks
        )

    def _verificar_escrita_raid(self):
        if self.device == "raid5" and self.raid is not None and self.raid.failed_disks:
            raise FSError("Há disco com falha no RAID; recupere-o (raid_recover) antes de gravar.")

    @staticmethod
    def _conteudo_sintetico(owner, size):
        """Gera bytes determinísticos para arquivos sem conteúdo explícito."""
        base = f"[dados de {owner}] ".encode("utf-8")
        return (base * (size // len(base) + 1))[:size]

    def _gravar_conteudo(self, arquivo, dados):
        if len(dados) != arquivo.size:
            raise FSError("O conteúdo deve ter o mesmo tamanho declarado para o arquivo.")
        for indice, bloco in enumerate(arquivo.alloc["data"]):
            inicio = indice * self.disk.block_size
            parte = dados[inicio:inicio + self.disk.block_size]
            self.disk.blocks[bloco]["dados"] = parte
            self.disk.blocks[bloco]["usados"] = len(parte)
            self.integridade[bloco] = hashlib.sha256(parte).hexdigest()

    def _ler_conteudo(self, arquivo):
        partes = []
        for bloco in arquivo.alloc["data"]:
            registro = self.disk.blocks[bloco]
            partes.append(registro.get("dados", b"") if registro else b"")
        return b"".join(partes)[:arquivo.size]

    def _liberar_alocacao(self, arquivo):
        for bloco in arquivo.alloc["data"]:
            self.integridade.pop(bloco, None)
        STRATEGIES[arquivo.strategy].release(self.disk, arquivo.alloc)

    def _io_raid(self, op, node, owner):
        """Traduz a E/S do arquivo em gravação/leitura distribuída no arranjo RAID 5."""
        r = self.raid
        try:
            if op == "W":
                if r.failed_disks:
                    raise FSError("Há disco com falha no RAID; recupere-o (raid_recover) antes de gravar.")
                conteudo = self._conteudo_sintetico(owner, node.size)
                antigo = r.files.pop(owner, None)  # update: nova versão substitui a anterior
                try:
                    r.write(conteudo, file_id=owner)
                    linhas = r.descrever_escrita(owner, owner)
                    linhas.extend(r.teste_falha(owner, disk_index=1))
                except RAIDError:
                    if antigo is not None:
                        r.files[owner] = antigo
                    else:
                        r.files.pop(owner, None)
                    raise
                self.dev_log.extend(linhas)
            else:
                if owner not in r.files:
                    self.dev_log.append(f"R | '{owner}' não está gravado no RAID")
                    return
                owner_original = r.files[owner].get("owner", owner)
                esperado = self._conteudo_sintetico(owner_original, node.size)
                dados = r.read(owner)
                dados = dados.encode("utf-8") if isinstance(dados, str) else dados
                if r.failed_disks:
                    d = sorted(r.failed_disks)[0] + 1
                    self.dev_log.append(f"R | Disco {d} com falha: blocos reconstruídos via XOR")
                self.dev_log.append(f"R | {len(r.layout(owner))} stripes lidas | integridade: "
                                    f"{'[OK]' if dados == esperado else '[ERRO]'}")
        except RAIDError:
            raise
        except FSError:
            raise
        except Exception as e:  # Outros erros do dispositivo são exibidos no log.
            self.dev_log.append(f"{op} | ERRO RAID: {e}")

    def _io_ssd(self, op, blocks, owner):
        """Traduz blocos do FS em operações de página no SSD (bloco = página lógica)."""
        ssd = self.ssd
        for b in blocks:
            try:
                if op == "W":
                    gc_antes, erase_antes = ssd.gc_count, list(ssd.erase_count)
                    antiga = ssd.mapping.get(b)
                    fisica = ssd.write(b, f"{owner}#bloco{b}")
                    msg = (f"W | bloco {b} -> página lógica {b} -> página física {fisica} "
                           f"(bloco SSD {ssd.block_of(fisica)})")
                    if antiga is not None:
                        msg += f" | invalidou página física {antiga}"
                    if ssd.gc_count > gc_antes:
                        apagados = [i for i, (x, y) in enumerate(zip(erase_antes, ssd.erase_count)) if y > x]
                        msg += f" | GC: apagou bloco SSD {apagados}"
                    self.dev_log.append(msg)
                else:
                    if b in ssd.mapping:
                        fisica = ssd.mapping[b]
                        ssd.read(b)
                        self.dev_log.append(f"R | bloco {b} -> página lógica {b} -> página física {fisica}")
                    else:
                        self.dev_log.append(f"R | bloco {b} -> página lógica {b} não mapeada no SSD")
            except Exception as e:  # SSDError: não derruba o FS
                self.dev_log.append(f"{op} | bloco {b} -> ERRO SSD: {e}")

    # ---------- CREATE ----------
    def mkdir(self, path, parents=False):
        self.sec.exigir_login()
        if parents:
            node, parts = self._parts(path)
            novos = []
            for p in parts:
                if not isinstance(node, Directory):
                    raise FSError("O caminho pai não é um diretório.")
                if p not in node.children:
                    acl.checar(self.sec, node, "w")
                    filho = Directory(p, node)
                    self._atribuir_dono(filho)
                    novos.append((node, filho))
                    node = filho
                else:
                    node = self._step(node, p)
            for pai, filho in novos:
                pai.children[filho.name] = self._atribuir_dono(filho)
            return
        parent, name = self.resolve_parent(path)
        if name in parent.children:
            raise FSError(f"'{path}' já existe.")
        acl.checar(self.sec, parent, "w")
        parent.children[name] = self._atribuir_dono(Directory(name, parent))

    def create(self, path, size=None, strategy=None, content=None):
        self.sec.exigir_login()
        if content is not None:
            conteudo = content.encode("utf-8") if isinstance(content, str) else content
            size = len(conteudo)
        elif size is not None:
            conteudo = self._conteudo_sintetico(path, size)
        else:
            raise FSError("Informe --size ou --content.")
        strategy = strategy or self.strategy
        if strategy not in STRATEGIES:
            raise FSError(f"Estratégia desconhecida: {strategy}")
        parent, name = self.resolve_parent(path)
        if name in parent.children:
            raise FSError(f"'{path}' já existe.")
        acl.checar(self.sec, parent, "w")
        self._verificar_escrita_raid()
        f = self._atribuir_dono(File(name, parent, size, strategy))
        f.alloc = STRATEGIES[strategy].allocate(self.disk, f, size)  # pode levantar DiskError
        self._gravar_conteudo(f, conteudo)
        parent.children[name] = f
        try:
            self._enqueue_io("W", f)
        except (FSError, RAIDError):
            del parent.children[name]
            self._liberar_alocacao(f)
            raise
        return f

    # ---------- READ ----------
    def ls(self, path=".", long=False):
        self.sec.exigir_login()
        node = self.resolve(path)
        if isinstance(node, File):
            acl.checar(self.sec, node, "r")
            return [self._linha_longo(node)] if long else [self._linha(node)]
        acl.checar(self.sec, node, "r")
        if long:
            return [self._linha_longo(c) for c in sorted(
                node.children.values(), key=lambda n: (isinstance(n, File), n.name)
            )]
        return [self._linha(c) for c in sorted(node.children.values(),
                key=lambda n: (isinstance(n, File), n.name))]

    @staticmethod
    def _linha(n):
        if isinstance(n, Directory):
            return f"{n.name}/ [DIR]"
        return f"{n.name} ({fmt_bytes(n.size)}) [ARQ]"

    @staticmethod
    def _linha_longo(n):
        tipo = "d" if isinstance(n, Directory) else "-"
        return f"{tipo}{acl.perm_str(n.mode)} {n.owner}:{n.group} {FileSystem._linha(n)}"

    def read(self, path):
        self.sec.exigir_login()
        n = self.resolve(path)
        if isinstance(n, Directory):
            raise FSError(f"'{path}' é um diretório (use 'ls').")
        acl.checar(self.sec, n, "r")
        acesso = acl.relatorio(self.sec, n, "r")
        a = n.alloc
        self._enqueue_io("R", n)
        return [f"Arquivo : {self.path_of(n)}",
                f"Tamanho : {n.size} bytes ({fmt_bytes(n.size)})",
                f"Alocação: {n.strategy}",
                f"I-node  : {'Bloco %02d' % a['inode'] if a['inode'] is not None else '-'}",
                f"Blocos  : {a['data']}",
                f"Dono    : {n.owner} (Grupo: {n.group})",
                acesso]

    def tree(self):
        self.sec.exigir_login()
        lines = ["/"]

        def rec(d, prefix):
            items = sorted(d.children.values(), key=lambda n: (isinstance(n, File), n.name))
            for k, n in enumerate(items):
                last = k == len(items) - 1
                lines.append(prefix + ("└── " if last else "├── ") + self._linha(n))
                if isinstance(n, Directory):
                    rec(n, prefix + ("    " if last else "│   "))
        rec(self.root, "")
        return "\n".join(lines)

    def cd(self, path):
        self.sec.exigir_login()
        n = self.resolve(path)
        if not isinstance(n, Directory):
            raise FSError(f"'{path}' não é um diretório.")
        acl.checar(self.sec, n, "x")
        self.cwd = n

    # ---------- UPDATE ----------
    def update(self, path, new_size):
        self.sec.exigir_login()
        f = self.resolve(path)
        if not isinstance(f, File):
            raise FSError("Só é possível redimensionar arquivos.")
        acl.checar(self.sec, f, "w")
        if f.cripto is not None:
            raise FSError("Arquivo criptografado: use decrypt_file antes de update.")
        self._verificar_escrita_raid()
        snapshot = [dict(bloco) if bloco is not None else None for bloco in self.disk.blocks]
        integridade = dict(self.integridade)
        fila, log, old, old_size = list(self.io_queue), list(self.dev_log), f.alloc, f.size
        strat = STRATEGIES[f.strategy]
        self._liberar_alocacao(f)
        try:
            f.alloc = strat.allocate(self.disk, f, new_size)
            f.size = new_size
            self._gravar_conteudo(f, self._conteudo_sintetico(self.path_of(f), new_size))
            self._enqueue_io("W", f)
        except (DiskError, NotImplementedError, FSError, RAIDError):
            self.disk.blocks[:] = snapshot  # desfaz
            self.integridade.clear()
            self.integridade.update(integridade)
            f.alloc = old
            f.size = old_size
            self.io_queue[:] = fila
            self.dev_log[:] = log
            raise

    def move(self, src, dst):
        """mv: renomeia ou move. Se dst é diretório existente, move para dentro dele."""
        self.sec.exigir_login()
        n = self.resolve(src)
        if n is self.root:
            raise FSError("Não é possível mover a raiz.")
        arquivos = list(self.all_files(n)) if isinstance(n, Directory) else [n]
        caminhos_antigos = {arquivo: self.path_of(arquivo) for arquivo in arquivos}
        try:
            destino = self.resolve(dst)
        except FSError:
            destino = None
        if isinstance(destino, Directory):
            novo_pai, novo_nome = destino, n.name
        else:
            novo_pai, novo_nome = self.resolve_parent(dst)
        p = novo_pai
        while p is not None:
            if p is n:
                raise FSError("Não é possível mover um diretório para dentro de si mesmo.")
            p = p.parent
        if novo_nome in novo_pai.children:
            raise FSError(f"'{novo_nome}' já existe no destino.")
        acl.checar(self.sec, n.parent, "w")
        acl.checar(self.sec, novo_pai, "w")
        del n.parent.children[n.name]
        n.name, n.parent = novo_nome, novo_pai
        novo_pai.children[novo_nome] = n
        if self.device == "raid5" and self.raid is not None:
            for arquivo, caminho_antigo in caminhos_antigos.items():
                caminho_novo = self.path_of(arquivo)
                if caminho_antigo in self.raid.files:
                    self.raid.rename(caminho_antigo, caminho_novo)

    # ---------- DELETE ----------
    def remove(self, path, recursive=False):
        self.sec.exigir_login()
        n = self.resolve(path)
        if n is self.root:
            raise FSError("Não é possível remover a raiz.")
        p = self.cwd
        while p is not None:
            if p is n:
                raise FSError("Não é possível remover o diretório atual (ou um pai dele).")
            p = p.parent
        if isinstance(n, Directory) and n.children and not recursive:
            raise FSError(f"'{path}' não está vazio (use 'rm -r').")
        acl.checar(self.sec, n.parent, "w")
        self._liberar(n)
        del n.parent.children[n.name]

    def _liberar(self, n):
        if isinstance(n, File):
            if self.device == "raid5" and self.raid is not None:
                self.raid.remove(self.path_of(n))
            if self.device == "ssd" and self.ssd is not None:
                a = n.alloc
                for b in ([a["inode"]] if a["inode"] is not None else []) + a["data"]:
                    if b in self.ssd.mapping:
                        self.ssd.trim(b)       # TRIM: páginas do arquivo removido
            self._liberar_alocacao(n)
        else:
            for c in list(n.children.values()):
                self._liberar(c)

    def chmod(self, path, mode):
        self.sec.exigir_login()
        n = self.resolve(path)
        if self.sec.modo != "MODO_KERNEL" and self.sec.efetivo.nome != n.owner:
            self.sec.auditar("CHMOD_NEGADO", f"'{self.sec.efetivo.nome}' em '{self.path_of(n)}'")
            raise FSError("Somente o proprietário ou root pode alterar permissões.")
        if isinstance(mode, str):
            if len(mode) != 3 or any(d not in "01234567" for d in mode):
                raise FSError("Permissão inválida; use três dígitos octais entre 000 e 777.")
            mode = int(mode, 8)
        if not isinstance(mode, int) or not 0 <= mode <= 0o777:
            raise FSError("Permissão inválida; use um valor entre 000 e 777.")
        n.mode = mode
        self.sec.auditar("CHMOD", f"'{self.path_of(n)}' para {mode:03o}")

    def chown(self, path, usuario, grupo=None):
        self.sec.exigir_kernel("chown")
        n = self.resolve(path)
        if usuario not in self.sec.usuarios:
            raise FSError(f"Usuário '{usuario}' não existe.")
        if grupo is not None and grupo not in self.sec.grupos:
            raise FSError(f"Grupo '{grupo}' não existe.")
        n.owner = usuario
        if grupo is not None:
            n.group = grupo
        self.sec.auditar("CHOWN", f"'{self.path_of(n)}' para {n.owner}:{n.group}")

    def encrypt_file(self, path, chave):
        self.sec.exigir_login()
        f = self.resolve(path)
        if not isinstance(f, File):
            raise FSError("Só é possível criptografar arquivos.")
        acl.checar(self.sec, f, "r")
        acl.checar(self.sec, f, "w")
        if f.cripto is not None:
            raise FSError("O arquivo já está criptografado.")
        self._verificar_escrita_raid()
        cifrado, registro = cripto.cifrar(self._ler_conteudo(f), chave)
        snapshot = [dict(bloco) if bloco is not None else None for bloco in self.disk.blocks]
        integridade = dict(self.integridade)
        fila, log = list(self.io_queue), list(self.dev_log)
        try:
            f.cripto = registro
            self._gravar_conteudo(f, cifrado)
            self._enqueue_io("W", f)
        except Exception:
            self.disk.blocks[:] = snapshot
            self.integridade.clear()
            self.integridade.update(integridade)
            self.io_queue[:] = fila
            self.dev_log[:] = log
            f.cripto = None
            raise
        primeiro = self.disk.blocks[f.alloc["data"][0]]["dados"] if f.alloc["data"] else b""
        prefixo = primeiro.hex().upper()[:7]
        self.sec.auditar("ENCRYPT", self.path_of(f))
        return (f"Arquivo '{self.path_of(f)}' criptografado com sucesso.\n"
                f"Conteúdo gravado nos blocos físicos: \"0x{prefixo} (Encrypted Ciphertext)\"")

    def decrypt_file(self, path, chave):
        self.sec.exigir_login()
        f = self.resolve(path)
        if not isinstance(f, File):
            raise FSError("Só é possível descriptografar arquivos.")
        acl.checar(self.sec, f, "r")
        acl.checar(self.sec, f, "w")
        if f.cripto is None:
            raise FSError("O arquivo não está criptografado.")
        try:
            claro = cripto.decifrar(self._ler_conteudo(f), chave, f.cripto)
        except cripto.CriptoError as erro:
            self.sec.auditar("DECRYPT_FALHA", self.path_of(f))
            raise FSError(str(erro))
        self._verificar_escrita_raid()
        registro_cripto = f.cripto
        snapshot = [dict(bloco) if bloco is not None else None for bloco in self.disk.blocks]
        integridade = dict(self.integridade)
        fila, log = list(self.io_queue), list(self.dev_log)
        try:
            f.cripto = None
            self._gravar_conteudo(f, claro)
            self._enqueue_io("W", f)
        except Exception:
            self.disk.blocks[:] = snapshot
            self.integridade.clear()
            self.integridade.update(integridade)
            self.io_queue[:] = fila
            self.dev_log[:] = log
            f.cripto = registro_cripto
            raise
        self.sec.auditar("DECRYPT", self.path_of(f))
        return f"Arquivo '{self.path_of(f)}' descriptografado com sucesso."

    def cat(self, path, chave=None):
        self.sec.exigir_login()
        f = self.resolve(path)
        if not isinstance(f, File):
            raise FSError("Só é possível ler arquivos.")
        acl.checar(self.sec, f, "r")
        conteudo = self._ler_conteudo(f)
        if f.cripto is not None:
            if chave is None:
                return conteudo.hex().upper()
            try:
                conteudo = cripto.decifrar(conteudo, chave, f.cripto)
            except cripto.CriptoError as erro:
                raise FSError(str(erro))
        return conteudo.decode("utf-8", errors="replace")
