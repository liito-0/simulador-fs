"""Criptografia simulada para fins didáticos; NÃO usar em produção."""
import hashlib
import hmac
import os


class CriptoError(Exception):
    pass


def _derivar_chave(chave, salt):
    return hashlib.pbkdf2_hmac("sha256", chave.encode("utf-8"), salt, 200_000)


def _fluxo(chave_derivada, nonce, tamanho):
    fluxo = bytearray()
    contador = 0
    while len(fluxo) < tamanho:
        fluxo.extend(hashlib.sha256(
            chave_derivada + nonce + contador.to_bytes(8, "big")
        ).digest())
        contador += 1
    return bytes(fluxo[:tamanho])


def cifrar(dados, chave):
    salt, nonce = os.urandom(16), os.urandom(16)
    chave_derivada = _derivar_chave(chave, salt)
    fluxo = _fluxo(chave_derivada, nonce, len(dados))
    cifrado = bytes(a ^ b for a, b in zip(dados, fluxo))
    registro = {
        "salt": salt.hex(),
        "nonce": nonce.hex(),
        "verificador": hmac.new(
            chave_derivada, b"verificacao", hashlib.sha256
        ).hexdigest(),
    }
    return cifrado, registro


def decifrar(dados, chave, registro):
    salt, nonce = bytes.fromhex(registro["salt"]), bytes.fromhex(registro["nonce"])
    chave_derivada = _derivar_chave(chave, salt)
    esperado = hmac.new(chave_derivada, b"verificacao", hashlib.sha256).hexdigest()
    if not hmac.compare_digest(esperado, registro["verificador"]):
        raise CriptoError("Chave incorreta.")
    fluxo = _fluxo(chave_derivada, nonce, len(dados))
    return bytes(a ^ b for a, b in zip(dados, fluxo))
