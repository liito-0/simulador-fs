"""Simulador de Sistema de Arquivos - ETAPA 2. Uso: python main.py [opções]"""
import argparse, re, shlex, sys
from disk import Disk, DiskError, fmt_bytes
from fs import FileSystem, FSError
from allocation import STRATEGIES
import diagnostico as dx
from scheduler import fcfs, sstf, scan, cscan, formatar

AJUDA = """Comandos:
  mkdir [-p] <caminho>                 cria diretório
  create <caminho> --size 10KB [--alloc contigua|encadeada|indexada]
  write_file <caminho> --size 8KB [--alloc ...] cria arquivo e registra E/S
  ls [caminho] | cd <caminho> | pwd | tree
  read <arquivo>                       mostra metadados e blocos
  read_file <arquivo>                  lê arquivo e registra E/S
  io_queue | io_clear                  lista ou limpa requisições de E/S
  disk_sched <fcfs|sstf|scan|cscan|all> [--head N] [--dir up|down]
            [--tracks 98,183,37,122,14] [--max-track N]
  update <arquivo> --size 20KB         redimensiona (Atualizar)
  mv <origem> <destino>                move/renomeia
  rm [-r] <caminho>                    remove arquivo/diretório
  alloc <estrategia>                   estratégia padrão para novos arquivos
  fs_status [--details]                mapa do disco + fragmentação
  compact                              compacta o disco
  help | exit"""


def parse_size(s):
    m = re.fullmatch(r"(\d+)\s*(B|KB|MB)?", s.strip(), re.I)
    if not m:
        raise FSError(f"Tamanho inválido: '{s}' (ex.: 512B, 10KB, 1MB)")
    return int(m.group(1)) * {"": 1, "B": 1, "KB": 1024, "MB": 1024 ** 2}[(m.group(2) or "").upper()]


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


def executar_io(fs, cmd, a):
    """Executa comandos de E/S e escalonamento; retorna se reconheceu o comando."""
    if cmd == "write_file":
        size, alloc = pop_opt(a, "--size"), pop_opt(a, "--alloc")
        if size is None or len(a) != 1:
            raise FSError("Use: write_file <caminho> --size 8KB [--alloc estrategia]")
        inicio = len(fs.io_queue)
        fs.create(a[0], parse_size(size), alloc)
        print("[ÁRVORE DO SISTEMA DE ARQUIVOS]")
        print(fs.tree())
        tracks = [request.track for request in fs.io_queue[inicio:]]
        print(f"[E/S] Requisições de leitura/escrita pendentes nas trilhas: {tracks}")
        return True
    if cmd == "read_file":
        if len(a) != 1:
            raise FSError("Use: read_file <arquivo>")
        inicio = len(fs.io_queue)
        print("\n".join(fs.read(a[0])))
        tracks = [request.track for request in fs.io_queue[inicio:]]
        print(f"[E/S] Requisições de leitura/escrita pendentes nas trilhas: {tracks}")
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


def executar(fs, linha):
    args = shlex.split(linha)
    if not args:
        return
    cmd, a = args[0].lower(), args[1:]
    if executar_io(fs, cmd, a):
        return
    if cmd == "mkdir":
        p = pop_flag(a, "-p"); fs.mkdir(a[0], parents=p)
    elif cmd == "create":
        size, alloc = pop_opt(a, "--size"), pop_opt(a, "--alloc")
        if size is None:
            raise FSError("Use: create <caminho> --size 10KB")
        fs.create(a[0], parse_size(size), alloc)
        print("[ÁRVORE DO SISTEMA DE ARQUIVOS]"); print(fs.tree())
    elif cmd == "ls":
        print("\n".join(fs.ls(a[0] if a else ".")) or "(vazio)")
    elif cmd == "cd":
        fs.cd(a[0])
    elif cmd == "pwd":
        print(fs.path_of(fs.cwd))
    elif cmd == "tree":
        print("[ÁRVORE DO SISTEMA DE ARQUIVOS]"); print(fs.tree())
    elif cmd == "read":
        print("\n".join(fs.read(a[0])))
    elif cmd == "update":
        size = pop_opt(a, "--size")
        if size is None:
            raise FSError("Use: update <arquivo> --size 20KB")
        fs.update(a[0], parse_size(size)); print("Atualizado.")
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
    ap.add_argument("--script")
    o = ap.parse_args()
    fs = FileSystem(Disk(o.blocks, o.block_size), o.alloc)

    def rodar(l):
        try:
            executar(fs, l)
        except (FSError, DiskError) as e:
            print(f"Erro: {e}")
        except NotImplementedError as e:
            print(f"[PENDENTE] {e}")
        except IndexError:
            print("Erro: argumentos insuficientes (digite help)")

    if o.script:
        for l in open(o.script, encoding="utf-8"):
            if l.strip() and not l.startswith("#"):
                print(f"> {l.strip()}"); rodar(l)
        return
    print("Simulador de FS - digite 'help'.")
    while True:
        try:
            l = input(f"{fs.path_of(fs.cwd)}> ")
        except EOFError:
            break
        if l.strip().lower() in ("exit", "quit"):
            break
        rodar(l)


if __name__ == "__main__":
    main()
