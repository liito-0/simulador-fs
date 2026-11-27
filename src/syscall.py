"""Syscalls simuladas e eventos de bloqueio/desbloqueio."""
import heapq
import itertools
from dataclasses import dataclass


class SyscallError(ValueError):
    pass


@dataclass
class Syscall:
    tipo: str
    instante_disparo: int
    duracao_bloqueio: int
    status: str = "PENDENTE"

    @property
    def tipo_operacao(self):
        return self.tipo

    @property
    def instante_disparo_cpu(self):
        return self.instante_disparo

    @property
    def duracao_bloqueio_simulada(self):
        return self.duracao_bloqueio

    @property
    def executada(self):
        return self.status == "EXECUTADA"

    def validar(self):
        if not isinstance(self.tipo, str) or not self.tipo.strip():
            raise SyscallError("O tipo da syscall não pode estar vazio.")
        if (not isinstance(self.instante_disparo, int)
                or isinstance(self.instante_disparo, bool)
                or self.instante_disparo < 0):
            raise SyscallError("O instante de disparo não pode ser negativo.")
        if (not isinstance(self.duracao_bloqueio, int)
                or isinstance(self.duracao_bloqueio, bool)
                or self.duracao_bloqueio <= 0):
            raise SyscallError("A duração do bloqueio deve ser positiva.")
        if self.status not in ("PENDENTE", "BLOQUEADA", "EXECUTADA"):
            raise SyscallError(f"Status de syscall inválido: {self.status}.")

    def marcar_executada(self):
        if self.status == "EXECUTADA":
            raise SyscallError("A syscall já foi executada.")
        if self.status not in ("PENDENTE", "BLOQUEADA"):
            raise SyscallError(f"Status de syscall inválido: {self.status}.")
        self.status = "EXECUTADA"


class GerenciadorEventos:
    """Agenda apenas bloqueios virtuais; não cria threads ou relógios reais."""

    def __init__(self):
        self._eventos = []
        self._sequencia = itertools.count()

    def bloquear(self, processo, motivo, duracao, instante_global,
                 syscall=None):
        if processo.estado != "EXECUTANDO":
            raise SyscallError("Somente processo EXECUTANDO pode ser bloqueado.")
        if syscall is not None:
            syscall.validar()
            if syscall.status != "PENDENTE":
                raise SyscallError("Somente syscalls pendentes podem ser disparadas.")
        if not isinstance(motivo, str) or not motivo.strip():
            raise SyscallError("O motivo do bloqueio não pode estar vazio.")
        if (not isinstance(duracao, int) or isinstance(duracao, bool)
                or duracao <= 0):
            raise SyscallError("A duração do bloqueio deve ser um inteiro positivo.")
        if (not isinstance(instante_global, int)
                or isinstance(instante_global, bool)
                or instante_global < 0):
            raise SyscallError("O instante global deve ser um inteiro não negativo.")

        instante_desbloqueio = instante_global + duracao
        identificador = next(self._sequencia)
        processo.transicionar_para("BLOQUEADO")
        if syscall is not None:
            syscall.status = "BLOQUEADA"
            processo.syscalls_executadas.append(syscall)
        processo.informacoes_bloqueio = {
            "motivo": motivo,
            "instante_desbloqueio": instante_desbloqueio,
            "syscall": syscall,
            "identificador_evento": identificador,
        }
        heapq.heappush(
            self._eventos,
            (instante_desbloqueio, identificador, processo, motivo, syscall),
        )
        return instante_desbloqueio

    def eventos_pendentes(self):
        return [
            {
                "processo": processo,
                "motivo": motivo,
                "instante": instante,
            }
            for instante, _, processo, motivo, _ in sorted(self._eventos)
        ]

    def consultar_eventos_pendentes(self):
        return self.eventos_pendentes()

    def registrar_bloqueio(self, processo, motivo, duracao,
                           instante_global, syscall=None):
        return self.bloquear(
            processo, motivo, duracao, instante_global, syscall
        )

    def eventos_no_instante_atual(self, instante_atual):
        return self.eventos_no_instante(instante_atual)

    def eventos_no_instante(self, instante_atual):
        self._validar_instante(instante_atual)
        return [evento for evento in self.eventos_pendentes()
                if evento["instante"] <= instante_atual]

    def processar_eventos(self, instante_atual):
        self._validar_instante(instante_atual)
        desbloqueados = []
        while self._eventos and self._eventos[0][0] <= instante_atual:
            evento = self._eventos[0]
            _, identificador, processo, _, syscall = evento
            bloqueio = processo.informacoes_bloqueio
            if (processo.estado == "BLOQUEADO"
                    and bloqueio.get("identificador_evento") == identificador):
                if syscall is not None:
                    if syscall.status != "BLOQUEADA":
                        raise SyscallError(
                            "O estado da syscall bloqueada foi alterado inesperadamente."
                        )
                    syscall.marcar_executada()
                processo.desbloquear()
                desbloqueados.append(processo)
            heapq.heappop(self._eventos)
        return desbloqueados

    @staticmethod
    def _validar_instante(instante):
        if (not isinstance(instante, int) or isinstance(instante, bool)
                or instante < 0):
            raise SyscallError("O instante atual deve ser um inteiro não negativo.")
