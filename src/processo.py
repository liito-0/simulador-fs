"""Representação de um processo do simulador."""
from dataclasses import dataclass


@dataclass
class Processo:
    pid: int
    nome: str
    tamanho: int
    tipo: str
    dono: str
