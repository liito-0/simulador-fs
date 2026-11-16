"""Diagnóstico do disco: mapa, fragmentação e necessidade de compactação."""
from disk import fmt_bytes
from allocation import STRATEGIES


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


def relatorio_fragmentacao(fs):
    """Devolve o relatório de fragmentação dos arquivos e do disco."""
    d = fs.disk
    arquivos = sorted(fs.all_files(), key=lambda f: fs.path_of(f))
    runs = d.free_runs()
    externa = (sum(tamanho for _, tamanho in runs) - max(
        (tamanho for _, tamanho in runs), default=0
    )) * d.block_size if len(runs) > 1 else 0
    precisa_compactar = externa > 0 and (
        fs.strategy == "contigua" or any(f.strategy == "contigua" for f in arquivos)
    )

    if externa == 0:
        motivo = "Sem fragmentação externa"
    elif arquivos and all(f.strategy == "encadeada" for f in arquivos):
        motivo = "Alocação encadeada não exige blocos contíguos"
    elif not arquivos and fs.strategy == "encadeada":
        motivo = "Alocação encadeada não exige blocos contíguos"
    else:
        motivo = "Blocos alocados via i-node indexado"

    necessidade = "SIM" if precisa_compactar else f"NÃO ({motivo})"
    linhas = ["--- RELATÓRIO DE FRAGMENTAÇÃO ---"]
    if not arquivos:
        linhas.append("Nenhum arquivo no disco.")
    else:
        for f in arquivos:
            blocos = f.alloc["data"]
            n = len(blocos)
            alocado = n * d.block_size
            interna = alocado - f.size
            linhas.append(f"Tamanho Real do Arquivo '{f.name}': "
                          f"{f.size} bytes ({fmt_bytes(f.size)})")
            linhas.append(f"Espaço Alocado no Disco         : {alocado} bytes "
                          f"({n} blocos de {fmt_bytes(d.block_size)})")
            linhas.append(f"Blocos                          : {blocos}")
            if interna == 0:
                linhas.append("Fragmentação Interna            : "
                              "0 bytes (0% de desperdício)")
            else:
                percentual = round(interna / d.block_size * 100)
                linhas.append(f"Fragmentação Interna            : {interna} bytes "
                              f"({percentual}% de desperdício no Bloco {blocos[-1]:02d})")
            linhas.append(f"Fragmentação Externa            : {externa} bytes")
            linhas.append(f"Necessidade de Compactação      : {necessidade}")

    runs_texto = ", ".join(
        f"[{inicio}]" if tamanho == 1 else f"[{inicio}..{inicio + tamanho - 1}]"
        for inicio, tamanho in runs
    ) or "(nenhum)"
    usados = d.total_blocks - len(d.free_list())
    linhas.extend([
        "",
        "--- RESUMO DO DISCO ---",
        f"Blocos usados/livres             : {usados}/{len(d.free_list())}",
        f"Trechos livres                   : {runs_texto}",
        f"Fragmentação Externa Total       : {externa} bytes",
        f"Necessidade de Compactação       : {necessidade}",
    ])
    return "\n".join(linhas)


def compactar(fs):
    """Reorganiza os arquivos para concentrar o espaço livre no final do disco."""
    fs.sec.exigir_kernel("compact")   # reorganiza blocos físicos: operação crítica
    d = fs.disk
    arquivos = list(fs.all_files())

    def posicao(f):
        blocos = ([f.alloc["inode"]] if f.alloc["inode"] is not None else [])
        blocos.extend(f.alloc["data"][:1])
        return min(blocos) if blocos else d.total_blocks

    arquivos.sort(key=posicao)
    snapshot = d.blocks[:]
    integridade = dict(fs.integridade)
    alocacoes_antigas = [(f, f.alloc) for f in arquivos]
    alocacoes_por_arquivo = dict(alocacoes_antigas)
    dados_antigos = {}
    for f, alloc in alocacoes_antigas:
        for bloco in alloc["data"]:
            registro = d.blocks[bloco]
            dados_antigos[(f, bloco)] = (
                registro.get("dados") if registro else None,
                registro.get("usados", 0) if registro else 0,
                fs.integridade.get(bloco),
                bloco in fs.integridade,
            )

    try:
        for f in arquivos:
            for bloco in f.alloc["data"]:
                fs.integridade.pop(bloco, None)
            STRATEGIES[f.strategy].release(d, f.alloc)
        for f in arquivos:
            f.alloc = STRATEGIES[f.strategy].allocate(d, f, f.size)
            for antigo, novo in zip(alocacoes_por_arquivo[f]["data"], f.alloc["data"]):
                registro = d.blocks[novo]
                dados, usados, hash_oficial, tinha_hash = dados_antigos[(f, antigo)]
                registro["dados"] = dados
                registro["usados"] = usados
                if tinha_hash:
                    fs.integridade[novo] = hash_oficial
    except Exception:
        d.blocks[:] = snapshot
        fs.integridade.clear()
        fs.integridade.update(integridade)
        for f, alloc in alocacoes_antigas:
            f.alloc = alloc
        raise

    movidos = 0
    for f, alloc_antiga in alocacoes_antigas:
        alocacao_nova = f.alloc
        antigos = ([alloc_antiga["inode"]] if alloc_antiga["inode"] is not None else [])
        novos = ([alocacao_nova["inode"]] if alocacao_nova["inode"] is not None else [])
        antigos.extend(alloc_antiga["data"])
        novos.extend(alocacao_nova["data"])
        movidos += sum(1 for antigo, novo in zip(antigos, novos) if antigo != novo)
        movidos += abs(len(antigos) - len(novos))

    if movidos == 0:
        return "Compactação desnecessária: disco já está compactado."

    livres = d.free_runs()
    if livres:
        inicio, tamanho = livres[0]
        espaco_livre = f"blocos {inicio}..{inicio + tamanho - 1}"
    else:
        espaco_livre = "nenhum bloco livre"
    return (f"Compactação concluída: {movidos} blocos movidos. "
            f"Espaço livre agora contíguo: {espaco_livre}.")
