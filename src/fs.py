"""Árvore de diretórios/arquivos + operações CRUD."""
from disk import DiskError, fmt_bytes
from allocation import STRATEGIES
from io_request import IORequest


class FSError(Exception):
    pass


class Node:
    def __init__(self, name, parent=None):
        self.name, self.parent = name, parent


class Directory(Node):
    def __init__(self, name, parent=None):
        super().__init__(name, parent)
        self.children = {}


class File(Node):
    def __init__(self, name, parent, size, strategy):
        super().__init__(name, parent)
        self.size, self.strategy = size, strategy
        self.alloc = {"inode": None, "data": []}


class FileSystem:
    def __init__(self, disk, strategy="indexada"):
        if disk.total_blocks < 1:
            raise FSError("O disco precisa de ao menos 1 bloco.")
        self.disk = disk
        self.strategy = strategy
        self.io_queue = []
        self.device = "hdd"      # "hdd" (fila + braço), "ssd" (páginas) ou "raid5"
        self.ssd = None          # instância de SSD, usada quando device == "ssd"
        self.raid = None         # instância de RAID5, usada quando device == "raid5"
        self.dev_log = []        # eventos de E/S do SSD/RAID (texto) para o shell exibir
        self.root = Directory("")
        self.cwd = self.root
        disk.set_block(0, "INODE_RAIZ", self.root, detalhe="Diretório '/'")

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

    @staticmethod
    def _conteudo_sintetico(owner, size):
        """O FS guarda só o tamanho; gera bytes determinísticos para o RAID distribuir."""
        base = f"[dados de {owner}] ".encode("utf-8")
        return (base * (size // len(base) + 1))[:size]

    def _io_raid(self, op, node, owner):
        """Traduz a E/S do arquivo em gravação/leitura distribuída no arranjo RAID 5."""
        r = self.raid
        try:
            if op == "W":
                if r.failed_disks:
                    raise RuntimeError("há disco com falha; recupere-o (raid_recover) antes de gravar")
                conteudo = self._conteudo_sintetico(owner, node.size)
                r.remove(owner)               # update: nova versão substitui a anterior
                r.write(conteudo, file_id=owner)
                self.dev_log.extend(r.descrever_escrita(owner, owner))
                self.dev_log.extend(r.teste_falha(owner, disk_index=1))
            else:
                if owner not in r.files:
                    self.dev_log.append(f"R | '{owner}' não está gravado no RAID")
                    return
                esperado = self._conteudo_sintetico(owner, node.size)
                dados = r.read(owner)
                dados = dados.encode("utf-8") if isinstance(dados, str) else dados
                if r.failed_disks:
                    d = sorted(r.failed_disks)[0] + 1
                    self.dev_log.append(f"R | Disco {d} com falha: blocos reconstruídos via XOR")
                self.dev_log.append(f"R | {len(r.layout(owner))} stripes lidas | integridade: "
                                    f"{'[OK]' if dados == esperado else '[ERRO]'}")
        except Exception as e:  # RAIDError etc.: não derruba o FS
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
        if parents:
            node, parts = self._parts(path)
            for p in parts:
                if p not in node.children:
                    node.children[p] = Directory(p, node)
                node = self._step(node, p)
            return
        parent, name = self.resolve_parent(path)
        if name in parent.children:
            raise FSError(f"'{path}' já existe.")
        parent.children[name] = Directory(name, parent)

    def create(self, path, size, strategy=None):
        strategy = strategy or self.strategy
        if strategy not in STRATEGIES:
            raise FSError(f"Estratégia desconhecida: {strategy}")
        parent, name = self.resolve_parent(path)
        if name in parent.children:
            raise FSError(f"'{path}' já existe.")
        f = File(name, parent, size, strategy)
        f.alloc = STRATEGIES[strategy].allocate(self.disk, f, size)  # pode levantar DiskError
        parent.children[name] = f
        self._enqueue_io("W", f)
        return f

    # ---------- READ ----------
    def ls(self, path="."):
        node = self.resolve(path)
        if isinstance(node, File):
            return [self._linha(node)]
        return [self._linha(c) for c in sorted(node.children.values(),
                key=lambda n: (isinstance(n, File), n.name))]

    @staticmethod
    def _linha(n):
        if isinstance(n, Directory):
            return f"{n.name}/ [DIR]"
        return f"{n.name} ({fmt_bytes(n.size)}) [ARQ]"

    def read(self, path):
        n = self.resolve(path)
        if isinstance(n, Directory):
            raise FSError(f"'{path}' é um diretório (use 'ls').")
        a = n.alloc
        self._enqueue_io("R", n)
        return [f"Arquivo : {self.path_of(n)}",
                f"Tamanho : {n.size} bytes ({fmt_bytes(n.size)})",
                f"Alocação: {n.strategy}",
                f"I-node  : {'Bloco %02d' % a['inode'] if a['inode'] is not None else '-'}",
                f"Blocos  : {a['data']}"]

    def tree(self):
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
        n = self.resolve(path)
        if not isinstance(n, Directory):
            raise FSError(f"'{path}' não é um diretório.")
        self.cwd = n

    # ---------- UPDATE ----------
    def update(self, path, new_size):
        f = self.resolve(path)
        if not isinstance(f, File):
            raise FSError("Só é possível redimensionar arquivos.")
        snapshot, old = list(self.disk.blocks), f.alloc
        strat = STRATEGIES[f.strategy]
        strat.release(self.disk, old)
        try:
            f.alloc = strat.allocate(self.disk, f, new_size)
            f.size = new_size
        except (DiskError, NotImplementedError):
            self.disk.blocks[:] = snapshot  # desfaz
            f.alloc = old
            raise
        self._enqueue_io("W", f)

    def move(self, src, dst):
        """mv: renomeia ou move. Se dst é diretório existente, move para dentro dele."""
        n = self.resolve(src)
        if n is self.root:
            raise FSError("Não é possível mover a raiz.")
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
        del n.parent.children[n.name]
        n.name, n.parent = novo_nome, novo_pai
        novo_pai.children[novo_nome] = n

    # ---------- DELETE ----------
    def remove(self, path, recursive=False):
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
            STRATEGIES[n.strategy].release(self.disk, n.alloc)
        else:
            for c in list(n.children.values()):
                self._liberar(c)
