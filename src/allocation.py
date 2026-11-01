"""Estratégias de alocação física de arquivos no disco.

Cada estratégia devolve um dict:  {"inode": int | None, "data": [blocos de dados]}
"""
from disk import DiskError


class Strategy:
    nome = ""

    def allocate(self, disk, owner, size):
        raise NotImplementedError

    def release(self, disk, alloc):
        blocos = ([alloc["inode"]] if alloc["inode"] is not None else []) + alloc["data"]
        for b in blocos:
            disk.release(b)

    @staticmethod
    def _marcar_dados(disk, owner, data, size, extra=lambda k: ""):
        for k, b in enumerate(data):
            usados = min(disk.block_size, size - k * disk.block_size)
            disk.set_block(b, "DADO", owner, usados=usados, seq=k + 1, detalhe=extra(k))


class Contigua(Strategy):
    nome = "contigua"

    def allocate(self, disk, owner, size):
        n = disk.blocks_needed(size)
        if n == 0:
            return {"inode": None, "data": []}
        start = disk.find_contiguous(n)
        if start is None:
            livres = len(disk.free_list())
            if livres >= n:
                raise DiskError(f"Fragmentação externa: há {livres} blocos livres, mas nenhum "
                                f"trecho contíguo de {n}. Compacte o disco (comando 'compact').")
            raise DiskError(f"Disco cheio: precisa de {n} blocos, só há {livres} livres.")
        data = list(range(start, start + n))
        self._marcar_dados(disk, owner, data, size)
        return {"inode": None, "data": data}


class Indexada(Strategy):
    nome = "indexada"

    def allocate(self, disk, owner, size):
        n = disk.blocks_needed(size)
        livres = disk.free_list()
        if len(livres) < n + 1:  # +1 bloco para o i-node
            raise DiskError(f"Disco cheio: precisa de {n + 1} blocos (1 i-node + {n} dados), "
                            f"só há {len(livres)} livres.")
        inode, data = livres[0], livres[1:n + 1]
        disk.set_block(inode, "INODE", owner, detalhe="índice -> " + (str(data) if data else "[]"))
        self._marcar_dados(disk, owner, data, size)
        return {"inode": inode, "data": data}


class Encadeada(Strategy):
    """Alocação Encadeada: cada bloco de dados aponta para o próximo."""
    nome = "encadeada"

    def allocate(self, disk, owner, size):
        n = disk.blocks_needed(size)
        if n == 0:
            return {"inode": None, "data": []}
        livres = disk.free_list()
        if len(livres) < n:
            raise DiskError(f"Disco cheio: precisa de {n} blocos, só há {len(livres)} livres.")
        data = livres[:n]
        self._marcar_dados(
            disk, owner, data, size,
            extra=lambda k: (f"-> próximo: Bloco {data[k + 1]:02d}"
                             if k + 1 < len(data) else "-> FIM"),
        )
        return {"inode": None, "data": data}


STRATEGIES = {s.nome: s() for s in (Contigua, Indexada, Encadeada)}
