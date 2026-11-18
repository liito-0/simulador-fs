"""Simulador de Sistema de Arquivos - ETAPA 3 (segurança). Uso: python main.py [opções]"""
import argparse, getpass, re, shlex, sys
from disk import Disk, DiskError, fmt_bytes
from fs import FileSystem, FSError
from allocation import STRATEGIES
import diagnostico as dx
from scheduler import fcfs, sstf, scan, cscan, formatar
from ssd import SSD, SSDError
from raid import RAID5, RAIDError
from seguranca import Seguranca, SecurityError, AuthError, PrivilegeError
from memoria import GerenciadorMemoria
from mem_reservada import MemoriaError
import antivirus
import acl

AJUDA = """
╔══════════════════════════════════════════════════════════════╗
║             SIMULADOR DE SISTEMA DE ARQUIVOS -               ║
║                       MENU DE AJUDA                          ║
╚══════════════════════════════════════════════════════════════╝

[1] SISTEMA DE ARQUIVOS
---------------------------------------------------------------
  mkdir <caminho>       Criar diretório
  cd <caminho>          Navegar entre diretórios
  pwd                   Mostrar diretório atual
  ls [caminho]          Listar arquivos e diretórios
  tree                  Exibir hierarquia completa

[2] MANIPULAÇÃO DE ARQUIVOS
---------------------------------------------------------------
  create <caminho>      Criar arquivo
  read <arquivo>        Consultar metadados e blocos
  update <arquivo>      Atualizar tamanho do arquivo
  mv <origem> <destino> Mover ou renomear
  rm <caminho>          Remover arquivo ou diretório

[3] ARMAZENAMENTO E ALOCAÇÃO
---------------------------------------------------------------
  alloc <estratégia>    Definir estratégia padrão
  fs_status             Exibir diagnóstico do disco
  fs_status --details   Exibir mapa e fragmentação
  compact               Compactar o disco

  Estratégias disponíveis:
  - contigua
  - encadeada
  - indexada

[4] ENTRADA E SAÍDA (E/S)
---------------------------------------------------------------
  write_file <caminho>  Gravar arquivo e gerar E/S
  read_file <arquivo>   Ler arquivo e gerar E/S
  io_queue              Consultar fila de requisições
  io_clear              Limpar fila de E/S

[5] ESCALONAMENTO DO DISCO
---------------------------------------------------------------
  disk_sched fcfs       Primeiro a chegar, primeiro atendido
  disk_sched sstf       Menor deslocamento primeiro
  disk_sched scan       Varredura do disco
  disk_sched cscan      Varredura circular
  disk_sched all        Comparar todos os algoritmos

  Opções:
  --head N              Posição inicial da cabeça
  --dir up|down         Direção do movimento
  --tracks LISTA        Trilhas solicitadas
  --max-track N         Limite máximo de trilhas

  Iniciar com --device ssd faz o write_file/read_file gerarem E/S
  em páginas do SSD (GC e wear leveling) no lugar da fila de trilhas.
  Com --device raid5 [--raid-disks N], os arquivos são distribuídos em
  stripes com paridade, com teste de falha de disco e reconstrução XOR.

[6] GERENCIAMENTO DE SSD
---------------------------------------------------------------
  ssd_write <pagina> <conteúdo>  Gravar dados em uma página
  ssd_read <pagina>              Ler dados de uma página
  ssd_trim <pagina>              Invalidar uma página
  ssd_status                     Exibir status do SSD
  ssd_wear                       Exibir desgaste dos blocos

[7] GERENCIAMENTO RAID 5
---------------------------------------------------------------
  raid_write <id> <conteúdo>  Gravar arquivo no RAID
  raid_read <id>              Ler arquivo do RAID
  raid_fail <disco>           Simular falha (discos numerados a partir de 1)
  raid_recover <disco>        Recuperar disco com falha
  raid_status                 Exibir estado do arranjo

[8] SEGURANÇA: IDENTIDADE E PRIVILÉGIOS
---------------------------------------------------------------
  login --user <nome> [--password S]   Autenticar (senha pedida sem eco)
  logout                               Encerrar a sessão
  whoami                               Usuário, grupos e modo de execução
  users / groups                       Listar usuários / grupos
  passwd [usuario] [--old S] [--password S]  Trocar senha
  sudo [--password S] <comando>        Executar em MODO_KERNEL (só grupo admin)

  Exigem MODO_KERNEL (root):
  useradd <nome> [--group G] [--password S]   Criar usuário
  userdel <nome>                       Remover usuário
  usermod <nome> [--add-group G] [--del-group G] [--group G]
  groupadd <nome> / groupdel <nome>    Criar / remover grupo
  shadow                               Ver armazenamento de senhas (salt+hash)
  audit_log                            Ver log de auditoria
  compact, alloc, io_clear, ssd_*, raid_*   Operações críticas de sistema/hardware

  Modos: MODO_USUARIO (usuários comuns) e MODO_KERNEL (root / sudo).

[9] CONTROLE DE ACESSO, CRIPTOGRAFIA E ANTIVÍRUS
---------------------------------------------------------------
  chmod <000-777> <caminho>       Alterar permissões (dono ou root)
  chown <usuário>[:grupo] <caminho> Alterar dono/grupo (exige MODO_KERNEL)
  acl <caminho>                   Exibir matriz rwx do objeto
  ls -l [caminho]                 Listar permissões e dono:grupo
  create <caminho> --content "texto" [--alloc estratégia]
  write_file <caminho> --content "texto" [--alloc estratégia]
  encrypt_file <caminho> --key K   Criptografar (chave pedida sem eco)
  decrypt_file <caminho> --key K   Descriptografar (exige r e w na ACL)
  cat <caminho> [--key K]          Ler conteúdo; ciphertext em hex sem chave
  antivirus_scan [caminho]         Varredura (exige MODO_KERNEL)
  disk_tamper <caminho|--block N> [--data TEXTO] (exige MODO_KERNEL)

[10] GERENCIAMENTO DE MEMÓRIA
---------------------------------------------------------------
  create_process --name N --size 512KB --type critical|normal
  terminate_process --name N       Encerrar processo
  ps                               Listar processos
  memory_status [--reserved|--virtual]  Consultar o estado da memória
  memory_compact --reserved        Compactar região reservada (exige MODO_KERNEL)
  memory_report                    Relatório de fragmentação
  translate_address --process N --page K
  execute_step --process N --instruction "LOAD_DATA Página 2"

  create_process --type critical exige MODO_KERNEL.
  Processos normais e o encerramento dos próprios processos normais
  estão disponíveis a qualquer usuário autenticado.

---------------------------------------------------------------
  help                  Exibir este menu
  exit                  Encerrar simulador
===============================================================
"""

def parse_size(s):
    m = re.fullmatch(r"(\d+)\s*(B|KB|MB)?", s.strip(), re.I)
    if not m:
        raise FSError(f"Tamanho inválido: '{s}' (ex.: 512B, 10KB, 1MB)")
    return int(m.group(1)) * {"": 1, "B": 1, "KB": 1024, "MB": 1024 ** 2}[(m.group(2) or "").upper()]


def parse_size_arg(s):
    try:
        return parse_size(s)
    except FSError as erro:
        raise argparse.ArgumentTypeError(str(erro))


def pop_opt(args, nome):
    if nome in args:
        i = args.index(nome)
        if i + 1 >= len(args):
            raise FSError(f"{nome} precisa de um valor.")
        v = args[i + 1]
        del args[i:i + 2]
        return v
    return None


def pop_flag(args, *nomes):
    achou = any(n in args for n in nomes)
    args[:] = [a for a in args if a not in nomes]
    return achou


def mostrar_io(fs, inicio, inicio_ssd):
    """Mostra o resultado da E/S conforme o dispositivo (HDD ou SSD)."""
    if fs.device == "raid5":
        print("\n".join(fs.dev_log[inicio_ssd:]))
        return
    if fs.device == "ssd":
        print("[E/S - SSD] Operações em páginas (sem movimento de braço):")
        for linha in fs.dev_log[inicio_ssd:]:
            print("  " + linha)
        desgaste = ", ".join(f"B{i}:{n}" for i, n in enumerate(fs.ssd.erase_count))
        print(f"[WEAR LEVELING] Apagamentos por bloco: {desgaste}")
        return
    tracks = [request.track for request in fs.io_queue[inicio:]]
    print(f"[E/S] Requisições de leitura/escrita pendentes nas trilhas: {tracks}")
    print(f"Posição atual da cabeça de leitura: Trilha {fs.disk.head}")


def executar_io(fs, cmd, a):
    """Executa comandos de E/S e escalonamento; retorna se reconheceu o comando."""
    if cmd == "write_file":
        size, alloc, content = (pop_opt(a, "--size"), pop_opt(a, "--alloc"),
                                pop_opt(a, "--content"))
        if (size is None and content is None) or len(a) != 1:
            raise FSError('Use: write_file <caminho> --size 8KB ou --content "texto"')
        inicio, inicio_ssd = len(fs.io_queue), len(fs.dev_log)
        fs.create(a[0], parse_size(size) if size is not None else None, alloc, content)
        print("[ÁRVORE DO SISTEMA DE ARQUIVOS]")
        print(fs.tree())
        mostrar_io(fs, inicio, inicio_ssd)
        return True
    if cmd == "read_file":
        if len(a) != 1:
            raise FSError("Use: read_file <arquivo>")
        inicio, inicio_ssd = len(fs.io_queue), len(fs.dev_log)
        print("\n".join(fs.read(a[0])))
        mostrar_io(fs, inicio, inicio_ssd)
        return True
    if cmd == "io_queue":
        if a:
            raise FSError("Use: io_queue")
        if not fs.io_queue:
            print("Fila de E/S vazia.")
        else:
            for request in fs.io_queue:
                print(f"{request.op} | bloco {request.block} | trilha {request.track} "
                      f"| arquivo {request.owner}")
        return True
    if cmd == "io_clear":
        if a:
            raise FSError("Use: io_clear")
        fs.io_queue.clear()
        print("Fila de E/S limpa.")
        return True
    if cmd != "disk_sched":
        return False

    if fs.device != "hdd" and "--tracks" not in a:
        print(f"Dispositivo {fs.device.upper()}: não há fila de trilhas/braço para escalonar. "
              "Use --device hdd, ou informe --tracks.")
        return True
    if not a:
        raise FSError("Use: disk_sched <fcfs|sstf|scan|cscan|all> [opções]")
    algorithm = a.pop(0).lower()
    tracks_arg = pop_opt(a, "--tracks")
    head_arg = pop_opt(a, "--head")
    direction = pop_opt(a, "--dir") or "up"
    max_arg = pop_opt(a, "--max-track")
    if a:
        raise FSError(f"Opção desconhecida: {a[0]}")
    if algorithm not in ("fcfs", "sstf", "scan", "cscan", "all"):
        raise FSError(f"Algoritmo inválido: {algorithm}")
    if direction not in ("up", "down"):
        raise FSError("A direção deve ser 'up' ou 'down'.")
    try:
        head = fs.disk.head if head_arg is None else int(head_arg)
        max_track = fs.disk.max_track if max_arg is None else int(max_arg)
        if tracks_arg is None:
            tracks = [request.track for request in fs.io_queue]
        else:
            tracks = [] if not tracks_arg else [int(track) for track in tracks_arg.split(",")]
    except ValueError:
        raise FSError("Cabeça, trilhas e max-track devem ser números inteiros.")
    if max_track < 0:
        raise FSError("max-track deve ser maior ou igual a zero.")
    if not 0 <= head <= max_track:
        raise FSError(f"A cabeça {head} está fora de 0..{max_track}.")
    if any(not 0 <= track <= max_track for track in tracks):
        raise FSError(f"Há trilhas fora de 0..{max_track}.")

    algorithms = {"fcfs": fcfs, "sstf": sstf, "scan": scan, "cscan": cscan}
    selected = list(algorithms) if algorithm == "all" else [algorithm]
    results = {}
    for name in selected:
        results[name] = algorithms[name](tracks, head, max_track, direction)
        order, movements, total = results[name]
        formatar(name, head, order, movements, total)
    if algorithm == "all":
        print("--- COMPARAÇÃO DE ESCALONAMENTOS ---")
        print("Algoritmo | Total de Movimento")
        for name in selected:
            label = "C-SCAN" if name == "cscan" else name.upper()
            print(f"{label:<8} | {results[name][2]} trilhas")
    if results[selected[-1]][0]:
        fs.disk.head = results[selected[-1]][0][-1]
    if tracks_arg is None:
        fs.io_queue.clear()
    return True

def executar_ssd(ssd, cmd, a):
    """Executa comandos de gerenciamento do SSD."""

    if cmd == "ssd_write":
        if len(a) < 2:
            raise SSDError(
                "Use: ssd_write <pagina> <conteúdo>"
            )

        try:
            pagina = int(a[0])
        except ValueError:
            raise SSDError("O número da página deve ser inteiro.")

        conteudo = " ".join(a[1:])

        fisica = ssd.write(pagina, conteudo)

        print(f"Dados gravados na página lógica {pagina}.")
        print(f"Página física utilizada: {fisica}")

        return True

    if cmd == "ssd_read":
        if len(a) != 1:
            raise SSDError("Use: ssd_read <pagina>")

        try:
            pagina = int(a[0])
        except ValueError:
            raise SSDError("O número da página deve ser inteiro.")

        conteudo = ssd.read(pagina)

        print(f"Conteúdo da página {pagina}: {conteudo}")
        return True

    if cmd == "ssd_trim":
        if len(a) != 1:
            raise SSDError("Use: ssd_trim <pagina>")

        try:
            pagina = int(a[0])
        except ValueError:
            raise SSDError("O número da página deve ser inteiro.")

        ssd.trim(pagina)

        print(f"Página lógica {pagina} invalidada.")
        return True

    if cmd == "ssd_status":
        if a:
            raise SSDError("Use: ssd_status")

        status = ssd.status()

        print("--- STATUS DO SSD ---")

        for nome, valor in status.items():
            print(f"{nome.replace('_', ' ').capitalize():<22}: {valor}")

        return True

    if cmd == "ssd_wear":
        if a:
            raise SSDError("Use: ssd_wear")

        print("--- WEAR LEVELING ---")

        for bloco in ssd.wear_report():
            print(
                f"Bloco {bloco['bloco']}: "
                f"{bloco['apagamentos']} apagamentos"
            )

        return True

    return False


def executar_raid(raid, cmd, a):
    """Executa comandos de gerenciamento do RAID 5."""

    if cmd == "raid_write":
        if len(a) < 2:
            raise RAIDError(
                'Use: raid_write <id> "conteúdo"'
            )

        file_id = a[0]
        conteudo = " ".join(a[1:])

        raid.write(conteudo, file_id=file_id)

        print(f"Arquivo '{file_id}' gravado no RAID 5.")
        print("Distribuição dos blocos:")

        status = raid.status()

        for i, quantidade in enumerate(status["stripes_por_disco"]):
            print(f"Disco {i}: {quantidade} blocos")

        return True

    if cmd == "raid_read":
        if len(a) != 1:
            raise RAIDError("Use: raid_read <id>")

        conteudo = raid.read(a[0])

        print(f"Conteúdo de '{a[0]}': {conteudo}")
        return True

    if cmd == "raid_fail":
        if len(a) != 1:
            raise RAIDError("Use: raid_fail <disco>")

        try:
            disco = int(a[0])
        except ValueError:
            raise RAIDError("O disco deve ser identificado por um número.")

        raid.fail_disk(disco - 1)   # o shell numera os discos a partir de 1

        print(f"Falha simulada no Disco {disco}.")
        print("O RAID 5 continua tolerando uma falha.")

        return True

    if cmd == "raid_recover":
        if len(a) != 1:
            raise RAIDError("Use: raid_recover <disco>")

        try:
            disco = int(a[0])
        except ValueError:
            raise RAIDError("O disco deve ser identificado por um número.")

        raid.recover(disco - 1)

        print(f"Disco {disco} reconstruído com sucesso via XOR.")

        return True

    if cmd == "raid_status":
        if a:
            raise RAIDError("Use: raid_status")

        print("--- STATUS DO RAID 5 ---")

        for nome, valor in raid.status().items():
            print(f"{nome.replace('_', ' ').capitalize():<22}: {valor}")

        return True

    return False


# ---------- Etapa 3: segurança ----------
SEM_LOGIN = {"help", "login"}
KERNEL_PROPRIOS = {"useradd", "userdel", "usermod", "groupadd", "groupdel", "shadow",
                   "audit_log", "chown", "antivirus_scan", "disk_tamper"}
KERNEL_SISTEMA = {"compact", "alloc", "io_clear", "memory_compact"}   # + SSD/RAID


def exige_kernel(cmd):
    return cmd in KERNEL_PROPRIOS or cmd in KERNEL_SISTEMA or cmd.startswith(("ssd_", "raid_"))


def mascarar(linha):
    """Esconde senhas/chaves passadas em linhas de script."""
    return re.sub(r"(--(?:password|old|key)\s+)(\"[^\"]*\"|'[^']*'|\S+)", r"\1****", linha)


def pedir_senha(a, ler_senha, prompt="Senha: ", opcao="--password", confirmar=False):
    """Senha vinda de --password (scripts) ou lida sem eco (interativo)."""
    v = pop_opt(a, opcao)
    if v is not None:
        return v
    if ler_senha is None:
        raise SecurityError(f"Senha obrigatória: informe {opcao}.")
    v = ler_senha(prompt)
    if confirmar and ler_senha("Repita a senha: ") != v:
        raise SecurityError("As senhas não conferem.")
    return v


def executar_seguranca(fs, cmd, a, ssd, raid, ler_senha):
    """Comandos de identidade/privilégio; retorna se reconheceu o comando."""
    sec = fs.sec
    if cmd == "login":
        nome = pop_opt(a, "--user")
        if nome is None or any(x.startswith("--") and x != "--password" for x in a):
            raise SecurityError("Use: login --user <nome> [--password <senha>]")
        if sec.autenticado:
            raise AuthError(f"Já autenticado como '{sec.usuario.nome}'. Use 'logout' antes.")
        senha = pedir_senha(a, ler_senha)
        u = sec.login(nome, senha)
        print(f"Autenticado com sucesso. Usuário: '{u.nome}' | Grupo: '{u.grupo}' | Modo: {sec.modo}")
        fs.cwd = fs.root
        return True
    if cmd == "logout":
        nome = sec.usuario.nome
        sec.logout()
        print(f"Sessão de '{nome}' encerrada.")
        return True
    if cmd == "whoami":
        print(sec.descrever())
        return True
    if cmd == "users":
        print("\n".join(sec.listar_usuarios()))
        return True
    if cmd == "groups":
        print("\n".join(sec.listar_grupos()))
        return True
    if cmd == "sudo":
        senha = None
        if a[:1] == ["--password"]:
            senha, a = (a[1] if len(a) > 1 else ""), a[2:]
        if not a:
            raise SecurityError("Use: sudo [--password <senha>] <comando>")
        if a[0].lower() in ("login", "logout", "sudo"):
            raise SecurityError(f"'{a[0]}' não pode ser executado com sudo.")
        if senha is None:
            if ler_senha is None:
                raise SecurityError("Senha obrigatória: use sudo --password <senha> <comando>.")
            senha = ler_senha(f"[sudo] senha de '{sec.usuario.nome}': ")
        with sec.sudo(senha):
            executar(fs, shlex.join(a), ssd, raid, ler_senha)
        return True
    if cmd == "passwd":
        antiga, nova = pop_opt(a, "--old"), pop_opt(a, "--password")
        alvo = a[0] if a else sec.usuario.nome
        if alvo == sec.usuario.nome and antiga is None:
            antiga = pedir_senha([], ler_senha, "Senha atual: ")
        if nova is None:
            nova = pedir_senha([], ler_senha, "Nova senha: ", confirmar=True)
        sec.passwd(alvo, nova, antiga)
        print(f"Senha de '{alvo}' alterada.")
        return True
    if cmd == "useradd":
        grupo, senha = pop_opt(a, "--group"), pop_opt(a, "--password")
        if len(a) != 1:
            raise SecurityError("Use: useradd <nome> [--group G] [--password S]")
        sec.exigir_kernel("useradd")  # nega antes de pedir a senha do novo usuário
        if senha is None:
            senha = pedir_senha([], ler_senha, "Senha do novo usuário: ", confirmar=True)
        u = sec.useradd(a[0], senha, grupo)
        print(f"Usuário '{u.nome}' criado (uid {u.uid}, grupo '{u.grupo}').")
        return True
    if cmd == "userdel":
        if len(a) != 1:
            raise SecurityError("Use: userdel <nome>")
        sec.userdel(a[0]); print(f"Usuário '{a[0]}' removido.")
        return True
    if cmd == "usermod":
        add, rem, prim = pop_opt(a, "--add-group"), pop_opt(a, "--del-group"), pop_opt(a, "--group")
        if len(a) != 1 or not (add or rem or prim):
            raise SecurityError("Use: usermod <nome> [--add-group G] [--del-group G] [--group G]")
        sec.usermod(a[0], adicionar=add, remover=rem, primario=prim)
        print(f"Usuário '{a[0]}' atualizado.")
        return True
    if cmd == "groupadd":
        if len(a) != 1:
            raise SecurityError("Use: groupadd <nome>")
        g = sec.groupadd(a[0]); print(f"Grupo '{g.nome}' criado (gid {g.gid}).")
        return True
    if cmd == "groupdel":
        if len(a) != 1:
            raise SecurityError("Use: groupdel <nome>")
        sec.groupdel(a[0]); print(f"Grupo '{a[0]}' removido.")
        return True
    if cmd == "shadow":
        print("[ARMAZENAMENTO DE SENHAS - nome:$algoritmo$iterações$salt$hash]")
        print("\n".join(sec.shadow()))
        return True
    if cmd == "audit_log":
        print("\n".join(sec.linhas_auditoria()) or "(vazio)")
        return True
    return False


def executar_controles(fs, cmd, a, ler_senha):
    if cmd == "chmod":
        if len(a) != 2:
            raise FSError("Use: chmod <000-777> <caminho>")
        fs.chmod(a[1], a[0])
        print(f"Permissões de '{a[1]}' alteradas para {int(a[0], 8):03o}.")
        return True
    if cmd == "chown":
        if len(a) != 2:
            raise FSError("Use: chown <usuário>[:grupo] <caminho>")
        identidade = a[0].split(":", 1)
        fs.chown(a[1], identidade[0], identidade[1] if len(identidade) == 2 else None)
        print(f"Proprietário de '{a[1]}' alterado para {fs.resolve(a[1]).owner}:"
              f"{fs.resolve(a[1]).group}.")
        return True
    if cmd == "acl":
        if len(a) != 1:
            raise FSError("Use: acl <caminho>")
        print("\n".join(acl.matriz(fs.resolve(a[0]))))
        return True
    if cmd == "encrypt_file":
        chave = pedir_senha(a, ler_senha, "Chave: ", "--key")
        if len(a) != 1:
            raise FSError("Use: encrypt_file <caminho> --key K")
        print(fs.encrypt_file(a[0], chave))
        return True
    if cmd == "decrypt_file":
        chave = pedir_senha(a, ler_senha, "Chave: ", "--key")
        if len(a) != 1:
            raise FSError("Use: decrypt_file <caminho> --key K")
        print(fs.decrypt_file(a[0], chave))
        return True
    if cmd == "cat":
        chave = pop_opt(a, "--key")
        if len(a) != 1:
            raise FSError("Use: cat <caminho> [--key K]")
        print(fs.cat(a[0], chave))
        return True
    if cmd == "antivirus_scan":
        if len(a) > 1:
            raise FSError("Use: antivirus_scan [caminho]")
        print("\n".join(antivirus.varrer(fs, a[0] if a else "/")))
        return True
    if cmd == "disk_tamper":
        bloco_arg = pop_opt(a, "--block")
        dados = pop_opt(a, "--data")
        if bloco_arg is not None:
            if a:
                raise FSError("Use: disk_tamper --block N [--data TEXTO]")
            try:
                bloco = int(bloco_arg)
            except ValueError:
                raise FSError("O número do bloco deve ser inteiro.")
            caminho = None
        else:
            if len(a) != 1:
                raise FSError("Use: disk_tamper <caminho> [--data TEXTO]")
            caminho, bloco = a[0], None
        bloco = antivirus.adulterar(fs, caminho, bloco, dados)
        print(f"Bloco {bloco} adulterado diretamente no disco.")
        return True
    return False


def _memoria(fs):
    if fs.mem is None:
        fs.mem = GerenciadorMemoria(sec=fs.sec)
    return fs.mem


def _linhas_virtual(linhas):
    return linhas if isinstance(linhas, list) else str(linhas).splitlines()


def _mostrar_relatorio_periodico(mem):
    linhas = mem.consumir_relatorio_periodico()
    if linhas:
        print("\n".join(linhas))


def executar_memoria(fs, cmd, a):
    """Executa comandos da Etapa 4; retorna se reconheceu o comando."""
    comandos = {
        "create_process", "terminate_process", "ps", "memory_status",
        "memory_compact", "memory_report", "translate_address", "execute_step",
    }
    if cmd not in comandos:
        return False
    mem = _memoria(fs)
    if cmd == "create_process":
        nome = pop_opt(a, "--name")
        tamanho = pop_opt(a, "--size")
        tipo = pop_opt(a, "--type")
        if a or nome is None or tamanho is None or tipo is None:
            raise FSError("Use: create_process --name N --size 512KB --type critical|normal")
        try:
            bytes_tamanho = parse_size(tamanho)
        except FSError as erro:
            raise MemoriaError(str(erro))
        if tipo == "critical":
            fs.sec.exigir_kernel("create_process (critical)")
        proc = mem.criar_processo(nome, bytes_tamanho, tipo, fs.sec.efetivo.nome)
        if proc.tipo == "critical":
            inicio, fim = mem.reservada.alocacoes[proc.nome]
            print("Alocado de forma contígua na Área Reservada: "
                  f"[{mem.reservada.formatar_endereco(inicio)} até "
                  f"{mem.reservada.formatar_endereco(fim)}] "
                  f"({mem.reservada._kb(proc.tamanho)} KB)")
        else:
            linhas_virtual = mem.consumir_saida_virtual()
            if linhas_virtual:
                print("\n".join(_linhas_virtual(linhas_virtual)))
        _mostrar_relatorio_periodico(mem)
        return True
    if cmd == "terminate_process":
        nome = pop_opt(a, "--name")
        if nome is None or a:
            raise FSError("Use: terminate_process --name N")
        proc = mem.processos.get(nome)
        if proc is None:
            raise MemoriaError(f"Processo '{nome}' não encontrado.")
        proc, intervalo, linhas_virtual = mem.encerrar_processo(nome)
        if intervalo is not None:
            inicio, fim = intervalo
            print(f"[ENCERRAMENTO DE PROCESSO CRÍTICO] Processo '{proc.nome}' finalizado.")
            print(f"Área de {mem.reservada._kb(proc.tamanho)} KB no intervalo "
                  f"[{mem.reservada.formatar_endereco(inicio)} a "
                  f"{mem.reservada.formatar_endereco(fim)}] liberada na Área Reservada da RAM.")
        else:
            print(f"Processo '{proc.nome}' finalizado.")
            if linhas_virtual:
                print("\n".join(_linhas_virtual(linhas_virtual)))
        _mostrar_relatorio_periodico(mem)
        return True
    if cmd == "ps":
        if a:
            raise FSError("Use: ps")
        print(f"{'PID':<6} {'NOME':<24} {'TIPO':<10} {'TAMANHO':<12} "
              f"{'REGIÃO':<20} DONO")
        for proc in sorted(mem.processos.values(), key=lambda p: p.pid):
            regiao = "Área Reservada" if proc.tipo == "critical" else "Memória Virtual"
            tamanho = f"{mem.reservada._kb(proc.tamanho)} KB"
            print(f"{proc.pid:<6} {proc.nome:<24} {proc.tipo:<10} "
                  f"{tamanho:<12} {regiao:<20} {proc.dono}")
        return True
    if cmd == "memory_status":
        reservada = pop_flag(a, "--reserved")
        virtual = pop_flag(a, "--virtual")
        if a or (reservada and virtual):
            raise FSError("Use: memory_status [--reserved|--virtual]")
        if reservada:
            print("\n".join(mem.reservada.mapa()))
            print()
            print("\n".join(mem.reservada.diagnostico()))
        elif virtual:
            if mem.virtual is None:
                print("Memória virtual: não disponível")
            else:
                print("\n".join(_linhas_virtual(mem.virtual.status())))
        else:
            usado = mem.reservada.tamanho - mem.reservada.total_livre
            percentual = usado / mem.reservada.tamanho * 100
            preenchido = round(percentual / 5)
            print("--- STATUS DA MEMÓRIA ---")
            print(f"RAM total       : {mem.reservada.formatar_endereco(mem.ram_total)}")
            print(f"Região reservada: {mem.reservada.formatar_endereco(mem.tamanho_reservado)}")
            print(f"Região dinâmica : {mem.reservada.formatar_endereco(mem.tamanho_dinamico)}")
            print(f"Área reservada usada/livre: {mem.reservada._kb(usado)}/"
                  f"{mem.reservada._kb(mem.reservada.total_livre)} KB "
                  f"({percentual:.1f}% usada)")
            print(f"[{'#' * preenchido}{'.' * (20 - preenchido)}]")
            if mem.virtual is None:
                print("Memória virtual: não disponível")
            else:
                print("\n".join(_linhas_virtual(mem.virtual.status())))
        return True
    if cmd == "memory_compact":
        reservado = pop_flag(a, "--reserved")
        if a or not reservado:
            raise FSError("Use: memory_compact --reserved")
        fs.sec.exigir_kernel("memory_compact")
        movimentos = mem.reservada.compactar()
        fs.sec.auditar("MEM_COMPACT", f"{len(movimentos)} processo(s) movido(s)")
        if not movimentos:
            print("Compactação desnecessária: não há fragmentação externa.")
            return True
        print("[EXECUTANDO COMPACTAÇÃO DA ÁREA RESERVADA DA RAM]")
        print("Realocando blocos contíguos para eliminar a fragmentação externa...")
        for nome, antigo_inicio, antigo_fim, novo_inicio, novo_fim in movimentos:
            print(f"- Mapeamento de '{nome}': "
                  f"[{mem.reservada.formatar_endereco(antigo_inicio)} a "
                  f"{mem.reservada.formatar_endereco(antigo_fim)}] -> Ajustado para: "
                  f"[{mem.reservada.formatar_endereco(novo_inicio)} a "
                  f"{mem.reservada.formatar_endereco(novo_fim)}]")
        print("\n--- MAPA APÓS COMPACTAÇÃO ---")
        print("\n".join(mem.reservada.mapa()))
        print("Resultado: Fragmentação externa eliminada. Maior bloco contíguo: "
              f"{mem.reservada._kb(mem.reservada.maior_bloco)} KB.")
        return True
    if cmd == "memory_report":
        if a:
            raise FSError("Use: memory_report")
        print("\n".join(mem.relatorio_fragmentacao()))
        return True
    if cmd in ("translate_address", "execute_step"):
        nome = pop_opt(a, "--process")
        if cmd == "translate_address":
            pagina = pop_opt(a, "--page")
            argumento = "--page K"
        else:
            instrucao = pop_opt(a, "--instruction")
            argumento = '--instruction "LOAD_DATA Página 2"'
        if a or nome is None or (pagina is None if cmd == "translate_address" else instrucao is None):
            raise FSError(f"Use: {cmd} --process N {argumento}")
        proc = mem.processos.get(nome)
        if proc is None:
            raise MemoriaError(f"Processo '{nome}' não existe.")
        if proc.tipo != "normal":
            raise MemoriaError(f"Processo '{nome}' não utiliza memória virtual.")
        if mem.virtual is None:
            raise MemoriaError(
                "Memória virtual indisponível: módulo da parte B ainda não integrado."
            )
        if cmd == "translate_address":
            try:
                pagina = int(pagina)
            except ValueError:
                raise MemoriaError("A página deve ser um número inteiro.")
            linhas = mem.virtual.traduzir(proc, pagina)
        else:
            linhas = mem.virtual.executar_passo(proc, instrucao)
        print("\n".join(_linhas_virtual(linhas)))
        return True
    return False


def executar(fs, linha, ssd=None, raid=None, ler_senha=None):
    args = shlex.split(linha)
    if not args:
        return
    cmd, a = args[0].lower(), args[1:]
    # Etapa 3: autenticação e portão de privilégios antes de qualquer comando
    if cmd not in SEM_LOGIN:
        fs.sec.exigir_login()
    if exige_kernel(cmd):
        fs.sec.exigir_kernel(cmd)
        if cmd in KERNEL_SISTEMA or cmd.startswith(("ssd_", "raid_")):
            fs.sec.auditar("KERNEL_OP", cmd)
    if executar_seguranca(fs, cmd, a, ssd, raid, ler_senha):
        return
    if executar_controles(fs, cmd, a, ler_senha):
        return
    if executar_memoria(fs, cmd, a):
        return
    if executar_io(fs, cmd, a):
        return
    if ssd is not None and executar_ssd(ssd, cmd, a):
        return
    if raid is not None and executar_raid(raid, cmd, a):
        return
    if cmd == "mkdir":
        p = pop_flag(a, "-p"); fs.mkdir(a[0], parents=p)
    elif cmd == "create":
        size, alloc, content = (pop_opt(a, "--size"), pop_opt(a, "--alloc"),
                                pop_opt(a, "--content"))
        if (size is None and content is None) or len(a) != 1:
            raise FSError('Use: create <caminho> --size 10KB ou --content "texto"')
        fs.create(a[0], parse_size(size) if size is not None else None, alloc, content)
        print("[ÁRVORE DO SISTEMA DE ARQUIVOS]"); print(fs.tree())
    elif cmd == "ls":
        longo = pop_flag(a, "-l")
        if len(a) > 1:
            raise FSError("Use: ls [-l] [caminho]")
        print("\n".join(fs.ls(a[0] if a else ".", long=longo)) or "(vazio)")
    elif cmd == "cd":
        fs.cd(a[0])
    elif cmd == "pwd":
        print(fs.path_of(fs.cwd))
    elif cmd == "tree":
        print("[ÁRVORE DO SISTEMA DE ARQUIVOS]"); print(fs.tree())
    elif cmd == "read":
        if len(a) != 1:
            raise FSError("Use: read <arquivo>")
        print("\n".join(fs.read(a[0])))
    elif cmd == "update":
        size = pop_opt(a, "--size")
        if size is None:
            raise FSError("Use: update <arquivo> --size 20KB")
        inicio_ssd = len(fs.dev_log)
        fs.update(a[0], parse_size(size)); print("Atualizado.")
        if fs.device != "hdd":
            mostrar_io(fs, 0, inicio_ssd)
    elif cmd in ("mv", "rename"):
        fs.move(a[0], a[1])
    elif cmd in ("rm", "rmdir"):
        r = pop_flag(a, "-r"); fs.remove(a[0], recursive=r)
    elif cmd == "alloc":
        if a[0] not in STRATEGIES:
            raise FSError(f"Opções: {', '.join(STRATEGIES)}")
        fs.strategy = a[0]; print(f"Estratégia padrão: {a[0]}")
    elif cmd == "fs_status":
        det = pop_flag(a, "--details")
        d = fs.disk
        print(dx.cabecalho(fs))
        print(f"Estratégia padrão: {fs.strategy} | Blocos usados: "
              f"{d.total_blocks - len(d.free_list())} | livres: {len(d.free_list())}")
        if det:
            print(); print(dx.mapa_disco(fs)); print()
            try:
                print(dx.relatorio_fragmentacao(fs))
            except NotImplementedError as e:
                print(f"[PENDENTE] {e}")
    elif cmd == "compact":
        print(dx.compactar(fs))
    elif cmd == "help":
        print(AJUDA)
    else:
        raise FSError(f"Comando desconhecido: '{cmd}' (digite help)")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--blocks", type=int, default=16)
    ap.add_argument("--block-size", type=int, default=4096)
    ap.add_argument("--alloc", default="indexada", choices=list(STRATEGIES))
    ap.add_argument("--device", default="hdd", choices=["hdd", "ssd", "raid5"],
                    help="dispositivo: hdd (braço), ssd (páginas) ou raid5 (discos + paridade)")
    ap.add_argument("--raid-disks", type=int, default=3, help="discos do RAID 5 (mínimo 3)")
    ap.add_argument("--ram", type=parse_size_arg, default=8 * 1024 ** 2)
    ap.add_argument("--reserved", type=parse_size_arg, default=4 * 1024 ** 2)
    ap.add_argument("--page-size", type=parse_size_arg, default=4 * 1024)
    ap.add_argument("--report-every", type=int, default=5)
    ap.add_argument("--script")
    ap.add_argument("--root-password", default="root",
                    help="senha inicial do superusuário (padrão: root; troque com 'passwd')")
    o = ap.parse_args()
    if o.ram <= 0 or o.reserved <= 1024 ** 2 or o.reserved >= o.ram:
        ap.error("--ram deve ser maior que --reserved, que deve exceder 1MB.")
    if o.page_size <= 0 or o.report_every < 0:
        ap.error("--page-size deve ser positivo e --report-every não negativo.")
    sec = Seguranca(senha_root=o.root_password)   # sem sessão: exige login
    fs = FileSystem(Disk(o.blocks, o.block_size), o.alloc, seguranca=sec)
    fs.mem = GerenciadorMemoria(o.ram, o.reserved, o.page_size, sec, o.report_every)
    ssd = SSD(total_blocks=max(8, o.blocks // 4 + 2), pages_per_block=4)
    fs.device, fs.ssd = o.device, ssd
    raid = RAID5(total_disks=o.raid_disks, block_size=o.block_size)
    fs.raid = raid

    def rodar(l, ler_senha):
        try:
            executar(fs, l, ssd, raid, ler_senha)
        except PrivilegeError as e:
            print(e)
        except (FSError, DiskError, SSDError, RAIDError, SecurityError, MemoriaError) as e:
            print(f"Erro: {e}")
        except NotImplementedError as e:
            print(f"[PENDENTE] {e}")
        except IndexError:
            print("Erro: argumentos insuficientes (digite help)")

    if o.script:
        for l in open(o.script, encoding="utf-8"):
            if l.strip() and not l.startswith("#"):
                print(f"> {mascarar(l.strip())}"); rodar(l, None)  # scripts: senha via --password
        return
    print("Simulador de FS - digite 'help'. Entre com: login --user <nome>")
    while True:
        try:
            if sec.autenticado:
                prompt = f"[{sec.usuario.nome}|{sec.modo}] {fs.path_of(fs.cwd)}> "
            else:
                prompt = "[deslogado]> "
            l = input(prompt)
        except EOFError:
            break
        if l.strip().lower() in ("exit", "quit"):
            break
        rodar(l, getpass.getpass)


if __name__ == "__main__":
    main()
