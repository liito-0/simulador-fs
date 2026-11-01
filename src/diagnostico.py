"""Diagnóstico do disco: mapa, fragmentação e necessidade de compactação."""
from disk import fmt_bytes


def cabecalho(fs):
    d = fs.disk
    return (f"Tamanho do Bloco de Disco: {fmt_bytes(d.block_size)} | "
            f"Total de Blocos: {d.total_blocks} ({fmt_bytes(d.block_size * d.total_blocks)})")


def mapa_disco(fs):
    """Mapa de alocação bloco a bloco (livres consecutivos são agrupados)."""
    d = fs.disk
    out = ["[MAPA DE ALOCAÇÃO DO DISCO]"]
    i = 0
    while i < d.total_blocks:
        b = d.blocks[i]
        if b is None:
            j = i
            while j + 1 < d.total_blocks and d.blocks[j + 1] is None:
                j += 1
            rotulo = f"{i:02d}" if i == j else f"{i:02d}..{j:02d}"
            out.append(f"Bloco {rotulo:<8}: [LIVRE]")
            i = j + 1
            continue
        caminho = fs.path_of(b["dono"])
        if b["tipo"] == "INODE_RAIZ":
            desc = f"Diretório '/'"
        elif b["tipo"] == "INODE":
            desc = f"Arquivo '{caminho}'  {b['detalhe']}"
        else:
            desc = f"'{caminho}' (Bloco {b['seq']} - {b['usados']} bytes ocupados) {b['detalhe']}"
        out.append(f"Bloco {i:02d}   [{b['tipo']}] : {desc.rstrip()}")
        i += 1
    return "\n".join(out)


# ------------------------------------------------------------------
# TODO (Giovanna) -- as duas funções abaixo são a sua parte!
# ------------------------------------------------------------------
def relatorio_fragmentacao(fs):
    """TODO (Giovanna): devolver o texto do RELATÓRIO DE FRAGMENTAÇÃO, no formato do enunciado:

    --- RELATÓRIO DE FRAGMENTAÇÃO ---
    Tamanho Real do Arquivo 'app.log': 10240 bytes (10 KB)
    Espaço Alocado no Disco         : 12288 bytes (3 blocos de 4 KB)
    Fragmentação Interna            : 2048 bytes (50% de desperdício no Bloco 04)
    Fragmentação Externa            : 0 bytes
    Necessidade de Compactação      : NÃO (...)

    Dicas:
      - for f in fs.all_files():  -> f.size, f.alloc["data"], f.strategy, fs.path_of(f)
      - interna (por arquivo) = len(f.alloc["data"]) * disk.block_size - f.size
        (desperdício % do último bloco = interna / block_size)
      - externa = bytes dos blocos livres que estão FORA do maior trecho livre
        (use disk.free_runs()); se só existe 1 trecho livre, externa = 0
      - precisa compactar = SIM se houver externa > 0 E algum arquivo usa alocação
        contígua (f.strategy == "contigua"); indexada/encadeada não precisam.
      - também mostre a ocupação exata de blocos por arquivo (ex.: blocos [2, 3, 4]).
    """
    raise NotImplementedError("relatorio_fragmentacao (parte da Giovanna)")


def compactar(fs):
    """TODO (Giovanna): compactar o disco (desfragmentar).

    Dicas: percorra os arquivos, libere seus blocos (STRATEGIES[f.strategy].release)
    e realoque em sequência a partir do primeiro bloco livre depois do i-node raiz,
    deixando todo o espaço livre num único trecho no final. Devolva uma mensagem
    com quantos blocos foram movidos.
    """
    raise NotImplementedError("compactar (parte da Giovanna)")
