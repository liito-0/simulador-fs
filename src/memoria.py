"""Gerenciamento de memória reservada e roteamento opcional à Parte B.

Contrato esperado para mem_virtual.MemoriaVirtual:
MemoriaVirtual(tamanho_dinamico, tamanho_pagina, sec=None[, tamanho_swap]), com
criar_processo(proc), encerrar_processo(proc), traduzir(proc, pagina),
executar_passo(proc, instrucao), status() e relatorio_fragmentacao_interna().
Cada método devolve list[str]. A paginação e sua política pertencem à Parte B.
"""
from mem_reservada import MemoriaError, RegiaoReservada
from processo import Processo
from seguranca import PrivilegeError

try:
    from mem_virtual import MemoriaVirtual
except ImportError:
    MemoriaVirtual = None


class GerenciadorMemoria:
    def __init__(self, ram_total=8 * 1024 ** 2, reservada=4 * 1024 ** 2,
                 tamanho_pagina=4 * 1024, sec=None, relatorio_a_cada=5,
                 tamanho_swap=None, politica="lru"):
        if not isinstance(ram_total, int) or ram_total <= 0:
            raise MemoriaError("A RAM total deve ser um inteiro positivo em bytes.")
        if not isinstance(reservada, int) or reservada <= 0 or reservada >= ram_total:
            raise MemoriaError("A região reservada deve ser positiva e menor que a RAM total.")
        if not isinstance(tamanho_pagina, int) or tamanho_pagina <= 0:
            raise MemoriaError("O tamanho da página deve ser um inteiro positivo em bytes.")
        if not isinstance(relatorio_a_cada, int) or relatorio_a_cada < 0:
            raise MemoriaError("O intervalo do relatório deve ser um inteiro não negativo.")
        self.ram_total = ram_total
        self.tamanho_reservado = reservada
        self.tamanho_dinamico = ram_total - reservada
        self.tamanho_pagina = tamanho_pagina
        self.sec = sec
        self.relatorio_a_cada = relatorio_a_cada
        self.reservada = RegiaoReservada(reservada)
        self.virtual = None
        if MemoriaVirtual is not None:
            extras = {} if tamanho_swap is None else {"tamanho_swap": tamanho_swap}
            self.virtual = MemoriaVirtual(self.tamanho_dinamico, tamanho_pagina,
                                          sec=sec, **extras)
            # a região dinâmica começa logo após a região reservada
            if hasattr(self.virtual, "base_fisica"):
                self.virtual.base_fisica = reservada
            if hasattr(self.virtual, "definir_politica"):
                self.virtual.definir_politica(politica)
        self.processos = {}
        self.operacoes = 0
        self._proximo_pid = 100
        self._relatorio_pendente = []
        self._saida_virtual_pendente = []

    def criar_processo(self, nome, tamanho, tipo, dono):
        self._saida_virtual_pendente = []
        if tipo not in ("critical", "normal"):
            raise MemoriaError("O tipo de processo deve ser 'critical' ou 'normal'.")
        if nome in self.processos:
            raise MemoriaError(f"Já existe um processo chamado '{nome}' na memória.")
        if not isinstance(tamanho, int) or tamanho <= 0:
            raise MemoriaError("O tamanho do processo deve ser um inteiro positivo em bytes.")
        proc = Processo(self._proximo_pid, nome, tamanho, tipo, dono)
        if tipo == "critical":
            try:
                self.reservada.alocar(nome, tamanho)
            except MemoriaError as erro:
                if self.sec is not None:
                    self.sec.auditar("MEM_FALHA", f"alocação crítica de '{nome}': {erro}")
                raise
        else:
            if self.virtual is None:
                erro = MemoriaError(
                    "Memória virtual indisponível: módulo da parte B ainda não integrado."
                )
                if self.sec is not None:
                    self.sec.auditar("MEM_FALHA", f"alocação virtual de '{nome}': {erro}")
                raise erro
            self._saida_virtual_pendente = self.virtual.criar_processo(proc)
        self._proximo_pid += 1
        self.processos[nome] = proc
        if self.sec is not None:
            self.sec.auditar("PROC_CRIADO", f"{nome} (pid {proc.pid}, tipo {tipo})")
        self._operacao_concluida()
        return proc

    def encerrar_processo(self, nome):
        if nome not in self.processos:
            raise MemoriaError(f"Processo '{nome}' não encontrado.")
        proc = self.processos[nome]
        if self.sec is not None and self.sec.modo != "MODO_KERNEL":
            if proc.tipo != "normal" or proc.dono != self.sec.efetivo.nome:
                detalhe = f"'{self.sec.efetivo.nome}' tentou encerrar '{nome}'"
                self.sec.auditar("PROC_NEGADO", detalhe)
                raise PrivilegeError(
                    f"Permissão negada: '{self.sec.efetivo.nome}' só pode encerrar "
                    "os próprios processos normais."
                )
        if proc.tipo == "critical":
            intervalo = self.reservada.liberar(nome)
            saida_virtual = []
        else:
            saida_virtual = self.virtual.encerrar_processo(proc)
            intervalo = None
        del self.processos[nome]
        if self.sec is not None:
            self.sec.auditar("PROC_ENCERRADO", f"{nome} (pid {proc.pid})")
        self._operacao_concluida()
        return proc, intervalo, saida_virtual

    def localizacao(self, proc):
        if proc.tipo == "critical":
            return self.reservada.alocacoes.get(proc.nome)
        return None

    def relatorio_fragmentacao(self):
        linhas = self.reservada.diagnostico()
        if self.virtual is None:
            linhas.append("Memória virtual: não disponível")
        else:
            linhas.extend(self.virtual.relatorio_fragmentacao_interna())
        return linhas

    def consumir_relatorio_periodico(self):
        linhas = self._relatorio_pendente
        self._relatorio_pendente = []
        return linhas

    def consumir_saida_virtual(self):
        linhas = self._saida_virtual_pendente
        self._saida_virtual_pendente = []
        return linhas

    def _operacao_concluida(self):
        self.operacoes += 1
        if self.relatorio_a_cada and self.operacoes % self.relatorio_a_cada == 0:
            self._relatorio_pendente = [
                "--- RELATÓRIO PERIÓDICO DE FRAGMENTAÇÃO ---"
            ] + self.relatorio_fragmentacao()
