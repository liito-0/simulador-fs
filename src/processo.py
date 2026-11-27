"""Representação de processos e suas informações de execução simulada."""
from dataclasses import dataclass, field
from typing import Optional


class ProcessoError(ValueError):
    pass


@dataclass
class Processo:
    pid: int
    nome: str
    tamanho: int
    tipo: str
    dono: str
    burst: Optional[int] = None
    prioridade: int = 0
    syscalls: list = field(default_factory=list)
    referencias_paginas: list = field(default_factory=list)
    tempo_chegada: int = 0

    estado: str = field(init=False, default="NOVO")
    burst_restante: Optional[int] = field(init=False, default=None)
    tempo_cpu: int = field(init=False, default=0)
    syscalls_executadas: list = field(init=False, default_factory=list)
    indice_referencia: int = field(init=False, default=0)
    informacoes_bloqueio: dict = field(init=False, default_factory=dict)
    threads: list = field(init=False, default_factory=list)

    ESTADOS = ("NOVO", "PRONTO", "EXECUTANDO", "BLOQUEADO", "CONCLUIDO")

    @property
    def burst_time(self):
        return self.burst

    @burst_time.setter
    def burst_time(self, valor):
        self.burst = valor

    @property
    def burst_restante_atual(self):
        return self.burst_restante

    @property
    def remaining_burst_time(self):
        return self.burst_restante

    @property
    def arrival_time(self):
        return self.tempo_chegada

    @property
    def cpu_time(self):
        return self.tempo_cpu

    @property
    def tempo_cpu_executado(self):
        return self.tempo_cpu

    @property
    def syscalls_configuradas(self):
        return self.syscalls

    @property
    def sequencia_paginas(self):
        return self.referencias_paginas

    def __post_init__(self):
        if self.tipo not in ("critical", "normal"):
            raise ProcessoError("O tipo de processo deve ser 'critical' ou 'normal'.")
        if not isinstance(self.tamanho, int) or isinstance(self.tamanho, bool) or self.tamanho <= 0:
            raise ProcessoError("O tamanho do processo deve ser um inteiro positivo em bytes.")
        if not isinstance(self.prioridade, int) or isinstance(self.prioridade, bool) or not 0 <= self.prioridade <= 31:
            raise ProcessoError("A prioridade deve ser um inteiro entre 0 e 31.")
        if not isinstance(self.tempo_chegada, int) or isinstance(self.tempo_chegada, bool) or self.tempo_chegada < 0:
            raise ProcessoError("O tempo de chegada não pode ser negativo.")

        if self.burst is None:
            self.burst = 1
        if not isinstance(self.burst, int) or isinstance(self.burst, bool) or self.burst <= 0:
            raise ProcessoError("O burst time deve ser um inteiro positivo.")
        self.burst_restante = self.burst

        validadas = []
        for syscall in self.syscalls:
            if hasattr(syscall, "validar"):
                syscall.validar()
            else:
                raise ProcessoError("Syscalls configuradas devem ser objetos Syscall.")
            validadas.append(syscall)
        self.syscalls = validadas
        if not isinstance(self.referencias_paginas, list):
            raise ProcessoError("As referências de páginas devem ser fornecidas em uma lista.")
        if any(not isinstance(pagina, int) or isinstance(pagina, bool) or pagina < 0
               for pagina in self.referencias_paginas):
            raise ProcessoError("As páginas referenciadas devem ser inteiros não negativos.")

    def transicionar_para(self, novo_estado):
        if novo_estado not in self.ESTADOS:
            raise ProcessoError(f"Estado inválido: {novo_estado}.")
        if self.estado not in self.ESTADOS:
            raise ProcessoError(f"Estado atual inválido: {self.estado}.")
        transicoes = {
            "NOVO": ("PRONTO",),
            "PRONTO": ("EXECUTANDO", "CONCLUIDO"),
            "EXECUTANDO": ("PRONTO", "BLOQUEADO", "CONCLUIDO"),
            "BLOQUEADO": ("PRONTO", "CONCLUIDO"),
            "CONCLUIDO": (),
        }
        if novo_estado not in transicoes[self.estado]:
            raise ProcessoError(
                f"Transição inválida de {self.estado} para {novo_estado}."
            )
        self.estado = novo_estado

    def aceitar(self):
        if self.estado == "NOVO":
            self.transicionar_para("PRONTO")

    def desbloquear(self):
        if self.estado != "BLOQUEADO":
            raise ProcessoError("Somente processos bloqueados podem ser desbloqueados.")
        self.informacoes_bloqueio = {}
        self.transicionar_para("PRONTO")

    def consultar_syscalls_pendentes(self):
        return [s for s in self.syscalls if s.status == "PENDENTE"]

    def disparar_syscalls_pendentes(self, instante_global, gerenciador_eventos=None):
        for syscall in list(self.syscalls):
            if syscall.status == "PENDENTE" and self.tempo_cpu >= syscall.instante_disparo:
                if gerenciador_eventos is None:
                    raise ProcessoError(
                        "Syscalls exigem GerenciadorEventos para agendar o desbloqueio."
                    )
                gerenciador_eventos.bloquear(
                    self,
                    motivo=syscall.tipo,
                    duracao=syscall.duracao_bloqueio,
                    instante_global=instante_global,
                    syscall=syscall,
                )
                return

    def avancar_cpu(self, tempo_ms, memoria_virtual=None, gerenciador_eventos=None,
                    instante_global=None):
        """Avança até ``tempo_ms`` ou até o próximo bloqueio/conclusão.

        ``instante_global`` representa o início da fatia; o escalonador pode
        determinar o tempo consumido pela diferença em ``tempo_cpu``.
        """
        if (not isinstance(tempo_ms, int) or isinstance(tempo_ms, bool)
                or tempo_ms <= 0):
            raise ProcessoError("O tempo de execução deve ser um inteiro positivo.")
        if instante_global is not None and (
                not isinstance(instante_global, int)
                or isinstance(instante_global, bool)
                or instante_global < 0):
            raise ProcessoError("O instante global deve ser um inteiro não negativo.")
        if self.estado != "EXECUTANDO":
            return []
        if self.consultar_syscalls_pendentes():
            if gerenciador_eventos is None:
                raise ProcessoError(
                    "Informe GerenciadorEventos para executar processos com syscalls pendentes."
                )
            if instante_global is None:
                raise ProcessoError(
                    "Informe o instante global para agendar syscalls pendentes."
                )
        instante_inicio = self.tempo_cpu if instante_global is None else instante_global
        saida_memoria = []
        self.disparar_syscalls_pendentes(instante_inicio, gerenciador_eventos)
        if self.estado == "BLOQUEADO":
            return saida_memoria
        if self.burst_restante == 0:
            self.transicionar_para("CONCLUIDO")
            return saida_memoria

        consumido = 0
        while consumido < tempo_ms and self.estado == "EXECUTANDO":
            if memoria_virtual is not None and self.referencias_paginas:
                posicao = self.indice_referencia % len(self.referencias_paginas)
                pagina = self.referencias_paginas[posicao]
                saida_memoria.extend(
                    memoria_virtual.executar_passo(
                        self, f"LOAD_DATA Página {pagina}"
                    )
                )
                self.indice_referencia += 1

            self.tempo_cpu += 1
            self.burst_restante -= 1
            consumido += 1
            self.disparar_syscalls_pendentes(
                instante_inicio + consumido, gerenciador_eventos
            )
            if self.estado == "BLOQUEADO":
                break
            if self.burst_restante == 0:
                self.transicionar_para("CONCLUIDO")
        return saida_memoria

    def consultar_referencia_pagina(self):
        if not self.referencias_paginas:
            return None
        posicao = self.indice_referencia % len(self.referencias_paginas)
        return self.referencias_paginas[posicao]

    def executar_referencia_pagina(self, memoria_virtual, pagina=None):
        avancar_indice = pagina is None
        if pagina is None:
            pagina = self.consultar_referencia_pagina()
            if pagina is None:
                raise ProcessoError(
                    "O processo não possui sequência de referências configurada."
                )
        if not isinstance(pagina, int) or isinstance(pagina, bool):
            raise ProcessoError("A página deve ser um inteiro.")
        resultado = memoria_virtual.executar_passo(
            self, f"LOAD_DATA Página {pagina}"
        )
        if avancar_indice:
            self.indice_referencia += 1
        return resultado
