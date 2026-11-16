"""Assinaturas fictícias para simulação de antivírus; não correspondem a ameaças reais."""
import hashlib

ASSINATURAS = {
    "SIM-MALWARE-01": b"SIM-MALWARE-SIG-001",
    "SIM-RANSOM-01": b"SIM-RANSOM-SIG-002",
}


def varrer(fs, caminho="/"):
    from fs import File

    fs.sec.exigir_kernel("antivirus_scan")
    alvo = fs.resolve(caminho)
    if isinstance(alvo, File):
        arquivos = [alvo]
    else:
        arquivos = sorted(fs.all_files(alvo), key=fs.path_of)
    fs.sec.auditar("AV_SCAN", caminho)
    linhas = [
        "[MÓDULO DE SEGURANÇA - VARREDURA DE INTEGRIDADE]",
        f"Analisando {len(arquivos)} arquivos em busca de assinaturas maliciosas e hashes corrompidos...",
    ]
    largura = max((len(fs.path_of(f)) for f in arquivos), default=0)
    tem_hash_alerta = False
    arquivos_assinatura = set()

    for arquivo in arquivos:
        caminho_arquivo = fs.path_of(arquivo)
        alertas_hash = []
        blocos = arquivo.alloc["data"]
        for bloco in blocos:
            registro = fs.disk.blocks[bloco]
            dados = registro.get("dados") if registro else None
            hash_oficial = fs.integridade.get(bloco)
            if dados is None or hash_oficial is None:
                alertas_hash.append(f"Bloco sem dados ou registro oficial! (bloco {bloco})")
            elif hashlib.sha256(dados).hexdigest() != hash_oficial:
                alertas_hash.append(
                    f"Hash do bloco difere do registro oficial! (bloco {bloco})"
                )
        if alertas_hash:
            tem_hash_alerta = True
            for alerta in alertas_hash:
                linhas.append(f"- {caminho_arquivo:<{largura}}  : [ALERTA] {alerta}")
                fs.sec.auditar("AV_ALERTA", f"{caminho_arquivo}: {alerta}")
        elif arquivo.cripto is not None:
            linhas.append(f"- {caminho_arquivo:<{largura}}  : [OK - Criptografado e íntegro]")
        else:
            conteudo = fs._ler_conteudo(arquivo)
            encontradas = [nome for nome, assinatura in ASSINATURAS.items()
                           if assinatura in conteudo]
            if encontradas:
                arquivos_assinatura.add(caminho_arquivo)
                for nome in encontradas:
                    linhas.append(
                        f"- {caminho_arquivo:<{largura}}  : "
                        f"[ALERTA] Assinatura maliciosa detectada: {nome}"
                    )
                    fs.sec.auditar("AV_ALERTA", f"{caminho_arquivo}: {nome}")
            else:
                linhas.append(f"- {caminho_arquivo:<{largura}}  : [OK - Íntegro]")

    if tem_hash_alerta:
        linhas.append("Resultado: Possível modificação direta não autorizada no bloco do disco.")
    if arquivos_assinatura:
        linhas.append(
            f"Resultado: Assinatura maliciosa encontrada em {len(arquivos_assinatura)} arquivo(s)."
        )
    if not tem_hash_alerta and not arquivos_assinatura:
        linhas.append("Resultado: Nenhuma anomalia encontrada.")
    return linhas


def adulterar(fs, caminho=None, bloco=None, dados=None):
    fs.sec.exigir_kernel("disk_tamper")
    from fs import FSError
    if bloco is None:
        from fs import File
        arquivo = fs.resolve(caminho)
        if not isinstance(arquivo, File):
            raise FSError("O caminho deve identificar um arquivo.")
        if not arquivo.alloc["data"]:
            raise FSError("O arquivo não possui blocos de dados.")
        bloco = arquivo.alloc["data"][0]
    if not isinstance(bloco, int) or not 0 <= bloco < fs.disk.total_blocks:
        raise FSError("Número de bloco fora dos limites do disco.")
    registro = fs.disk.blocks[bloco]
    if registro is None or registro["tipo"] != "DADO":
        raise FSError(f"O bloco {bloco} não contém dados de arquivo.")
    conteudo = b"DISK-TAMPER" if dados is None else dados.encode("utf-8")
    if len(conteudo) > fs.disk.block_size:
        raise FSError("Os dados excedem o tamanho do bloco.")
    registro["dados"] = conteudo
    registro["usados"] = len(conteudo)
    fs.sec.auditar("DISK_TAMPER", f"bloco {bloco}")
    return bloco
