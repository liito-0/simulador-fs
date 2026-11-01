"""Simulador de Sistema de Arquivos - ETAPA 1.  Uso: python main.py [--blocks 16] [--block-size 4096] [--alloc indexada] [--script demo.txt]"""
import argparse, re, shlex
from disk import Disk, DiskError, fmt_bytes
from fs import FileSystem, FSError
from allocation import STRATEGIES
import diagnostico as dx

AJUDA = """Comandos:
  mkdir [-p] <caminho>                 cria diretório
  create <caminho> --size 10KB [--alloc contigua|encadeada|indexada]
  ls [caminho] | cd <caminho> | pwd | tree
  read <arquivo>                       mostra metadados e blocos
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


def executar(fs, linha):
    args = shlex.split(linha)
    if not args:
        return
    cmd, a = args[0].lower(), args[1:]
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
