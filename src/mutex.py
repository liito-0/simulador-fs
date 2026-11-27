"""Mutex didático baseado em threads simuladas, sem threads reais."""
from dataclasses import dataclass
from typing import Optional


class MutexError(ValueError):
    pass


@dataclass(eq=False)
class ThreadSimulada:
    tid: str
    processo: object = None
    estado: str = "PRONTO"
    mutex_aguardado: Optional[object] = None

    @property
    def blocked_on(self):
        return self.mutex_aguardado


class Mutex:
    """Exclusão mútua simplificada para a simulação didática."""

    def __init__(self, nome):
        if not isinstance(nome, str) or not nome.strip():
            raise MutexError("O nome do Mutex não pode estar vazio.")
        self.nome = nome
        self.proprietario: Optional[ThreadSimulada] = None
        self.fila = []

    @property
    def livre(self):
        return self.proprietario is None

    @property
    def ocupado(self):
        return not self.livre

    def esta_livre(self):
        return self.livre

    def is_free(self):
        return self.livre

    @property
    def owner(self):
        return self.proprietario

    @property
    def waiting_threads(self):
        return list(self.fila)

    def adquirir(self, thread):
        if not isinstance(thread, ThreadSimulada):
            raise MutexError("A aquisição requer uma ThreadSimulada.")
        if self.proprietario is thread:
            raise MutexError("A thread já é proprietária deste Mutex.")
        if thread.mutex_aguardado is not None:
            if thread.mutex_aguardado is self and any(
                    aguardando is thread for aguardando in self.fila):
                return False
            raise MutexError("A thread já está aguardando outro Mutex.")
        if thread.estado == "BLOQUEADO":
            raise MutexError("A thread está bloqueada por outra operação.")
        if thread.estado not in ("PRONTO", "EXECUTANDO"):
            raise MutexError("Somente threads ativas podem adquirir o Mutex.")
        if self.livre:
            self.proprietario = thread
            thread.estado = "EXECUTANDO"
            return True
        thread.estado = "BLOQUEADO"
        if not any(aguardando is thread for aguardando in self.fila):
            self.fila.append(thread)
            thread.mutex_aguardado = self
        return False

    def liberar(self, thread):
        if self.proprietario is not thread:
            raise MutexError("Somente o proprietário pode liberar este Mutex.")
        self.proprietario = None
        thread.estado = "PRONTO"
        while self.fila:
            proxima = self.fila.pop(0)
            if proxima.estado == "BLOQUEADO" and proxima.mutex_aguardado is self:
                self.proprietario = proxima
                proxima.estado = "PRONTO"
                proxima.mutex_aguardado = None
                return proxima
            if proxima.mutex_aguardado is self:
                proxima.mutex_aguardado = None
        return None

    def identificar_proprietario(self):
        return self.proprietario
