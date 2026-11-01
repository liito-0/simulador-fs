"""Camada física: disco simulado dividido em blocos de tamanho fixo."""
import math


class DiskError(Exception):
    pass


def fmt_bytes(n):
    if n > 0 and n % 1024 == 0:
        return f"{n // 1024} KB"
    return f"{n} B"


class Disk:
    def __init__(self, total_blocks=16, block_size=4096):
        self.total_blocks = total_blocks
        self.block_size = block_size
        # Cada posição é None (livre) ou um dict:
        # {"tipo": "INODE_RAIZ"|"INODE"|"DADO", "dono": Node, "usados": int, "seq": int, "detalhe": str}
        self.blocks = [None] * total_blocks

    def blocks_needed(self, size):
        return math.ceil(size / self.block_size) if size > 0 else 0

    def free_list(self):
        return [i for i, b in enumerate(self.blocks) if b is None]

    def free_runs(self):
        """Lista de (inicio, tamanho) dos trechos livres contíguos."""
        runs, start = [], None
        for i, b in enumerate(self.blocks + [True]):  # sentinela fecha o último trecho
            if b is None and start is None:
                start = i
            elif b is not None and start is not None:
                runs.append((start, i - start))
                start = None
        return runs

    def find_contiguous(self, n):
        """First-fit: início do primeiro trecho livre com >= n blocos (ou None)."""
        for start, length in self.free_runs():
            if length >= n:
                return start
        return None

    def set_block(self, i, tipo, dono, usados=0, seq=None, detalhe=""):
        self.blocks[i] = {"tipo": tipo, "dono": dono, "usados": usados,
                          "seq": seq, "detalhe": detalhe}

    def release(self, i):
        self.blocks[i] = None
