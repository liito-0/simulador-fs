import contextlib
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from processo import Processo, ProcessoError
from syscall import Syscall, SyscallError, GerenciadorEventos
from mutex import Mutex, MutexError, ThreadSimulada
from mem_virtual import MemoriaVirtual
from memoria import GerenciadorMemoria
from mem_reservada import MemoriaError
from main import executar, parse_syscalls
from disk import Disk
from fs import FileSystem
from seguranca import Seguranca


KB = 1024


class TestProcessoEtapa5(unittest.TestCase):
    def test_construtor_legado_e_valores_padrao(self):
        processo = Processo(100, "Legado", 8 * KB, "normal", "root")
        self.assertEqual(processo.estado, "NOVO")
        self.assertEqual(processo.burst, 1)
        self.assertEqual(processo.burst_restante, 1)
        self.assertEqual(processo.prioridade, 0)
        processo.aceitar()
        self.assertEqual(processo.estado, "PRONTO")

    def test_construtor_expandido(self):
        syscall = Syscall("read_disk", 3, 4)
        processo = Processo(
            101, "App", 12 * KB, "normal", "root",
            burst=8, prioridade=2, syscalls=[syscall],
            referencias_paginas=[0, 1], tempo_chegada=5,
        )
        processo.aceitar()
        processo.transicionar_para("EXECUTANDO")
        self.assertEqual(processo.burst_time, 8)
        self.assertEqual(processo.remaining_burst_time, 8)
        self.assertEqual(processo.cpu_time, 0)
        self.assertEqual(processo.arrival_time, 5)
        self.assertEqual(processo.estado, "EXECUTANDO")

    def test_parametros_invalidos(self):
        with self.assertRaises(ProcessoError):
            Processo(1, "A", 10, "normal", "root", burst=0)
        with self.assertRaises(ProcessoError):
            Processo(1, "A", 10, "normal", "root", prioridade=-1)
        with self.assertRaises(SyscallError):
            syscall = Syscall("read_disk", -1, 4)
            syscall.validar()
        with self.assertRaises(SyscallError):
            parse_syscalls(["read_disk:-1:4"])

    def test_transicao_invalida(self):
        processo = Processo(1, "A", 10, "normal", "root")
        with self.assertRaises(ProcessoError):
            processo.transicionar_para("EXECUTANDO")
        with self.assertRaises(TypeError):
            Processo(2, "B", 10, "normal", "root", estado="EXECUTANDO")

    def test_pagina_configurada_invalida(self):
        with self.assertRaises(ProcessoError):
            Processo(3, "C", 10, "normal", "root", referencias_paginas=[-1])


class TestSyscallsEventos(unittest.TestCase):
    def novo_processo(self, burst=8):
        processo = Processo(
            100, "App", 8 * KB, "normal", "root",
            burst=burst,
            syscalls=[Syscall("read_disk", 3, 4)],
        )
        processo.aceitar()
        processo.transicionar_para("EXECUTANDO")
        return processo

    def test_disparo_pelo_cpu_acumulado_e_bloqueio(self):
        processo = self.novo_processo()
        eventos = GerenciadorEventos()
        processo.avancar_cpu(3, gerenciador_eventos=eventos, instante_global=0)
        self.assertEqual(processo.estado, "BLOQUEADO")
        self.assertEqual(processo.tempo_cpu, 3)
        self.assertEqual(processo.burst_restante, 5)
        self.assertEqual(processo.informacoes_bloqueio["instante_desbloqueio"], 7)
        processo.avancar_cpu(4, gerenciador_eventos=eventos, instante_global=3)
        self.assertEqual(processo.tempo_cpu, 3)
        self.assertEqual(processo.burst_restante, 5)

    def test_fatia_longa_para_no_instante_exato_da_syscall(self):
        processo = self.novo_processo()
        eventos = GerenciadorEventos()
        processo.avancar_cpu(
            5, gerenciador_eventos=eventos, instante_global=10
        )
        self.assertEqual(processo.tempo_cpu, 3)
        self.assertEqual(processo.burst_restante, 5)
        self.assertEqual(eventos.eventos_pendentes()[0]["instante"], 17)

    def test_syscall_pendente_exige_agendador_de_eventos(self):
        processo = self.novo_processo()
        with self.assertRaises(ProcessoError):
            processo.avancar_cpu(5)
        self.assertEqual(processo.estado, "EXECUTANDO")
        self.assertEqual(processo.tempo_cpu, 0)
        self.assertEqual(processo.burst_restante, 8)
        with self.assertRaises(ProcessoError):
            processo.avancar_cpu(5, gerenciador_eventos=GerenciadorEventos())
        self.assertEqual(processo.tempo_cpu, 0)

    def test_desbloqueio_no_instante_e_retorno_ao_pronto(self):
        processo = self.novo_processo()
        eventos = GerenciadorEventos()
        processo.avancar_cpu(3, gerenciador_eventos=eventos, instante_global=0)
        self.assertEqual(eventos.processar_eventos(6), [])
        desbloqueados = eventos.processar_eventos(7)
        self.assertEqual(desbloqueados, [processo])
        self.assertEqual(processo.estado, "PRONTO")

    def test_syscall_apenas_uma_vez(self):
        processo = self.novo_processo()
        eventos = GerenciadorEventos()
        processo.avancar_cpu(3, gerenciador_eventos=eventos, instante_global=0)
        eventos.processar_eventos(7)
        processo.transicionar_para("EXECUTANDO")
        processo.avancar_cpu(5, gerenciador_eventos=eventos, instante_global=12)
        self.assertEqual(len([s for s in processo.syscalls
                             if s.status == "EXECUTADA"]), 1)

    def test_syscalls_com_mesmo_instante_nao_consumem_cpu_entre_si(self):
        processo = Processo(
            101, "App2", 8 * KB, "normal", "root",
            burst=8,
            syscalls=[Syscall("disk_a", 3, 4), Syscall("disk_b", 3, 2)],
        )
        processo.aceitar()
        processo.transicionar_para("EXECUTANDO")
        eventos = GerenciadorEventos()
        processo.avancar_cpu(5, gerenciador_eventos=eventos, instante_global=0)
        self.assertEqual(processo.tempo_cpu, 3)
        eventos.processar_eventos(7)
        processo.transicionar_para("EXECUTANDO")
        processo.avancar_cpu(2, gerenciador_eventos=eventos, instante_global=7)
        self.assertEqual(processo.tempo_cpu, 3)
        self.assertEqual(processo.estado, "BLOQUEADO")
        self.assertEqual(eventos.eventos_pendentes()[0]["instante"], 9)

    def test_bloqueio_invalido_nao_altera_estado(self):
        processo = self.novo_processo()
        eventos = GerenciadorEventos()
        with self.assertRaises(SyscallError):
            eventos.bloquear(processo, "io", 0, 0)
        self.assertEqual(processo.estado, "EXECUTANDO")
        self.assertEqual(eventos.eventos_pendentes(), [])

    def test_evento_antigo_nao_desbloqueia_bloqueio_novo(self):
        processo = self.novo_processo()
        eventos = GerenciadorEventos()
        eventos.bloquear(processo, "primeiro", 5, 0)
        processo.desbloquear()
        processo.transicionar_para("EXECUTANDO")
        eventos.bloquear(processo, "segundo", 10, 5)
        self.assertEqual(eventos.processar_eventos(5), [])
        self.assertEqual(processo.estado, "BLOQUEADO")
        self.assertEqual(
            processo.informacoes_bloqueio["instante_desbloqueio"], 15
        )


class TestMemoriaProcesso(unittest.TestCase):
    def test_referencia_chama_memoria_virtual_e_mostra_hit_e_fault(self):
        vm = MemoriaVirtual(2 * 4 * KB, 4 * KB)
        processo = Processo(
            100, "App", 8 * KB, "normal", "root",
            burst=4, referencias_paginas=[0, 0],
        )
        vm.criar_processo(processo)
        processo.aceitar()
        processo.transicionar_para("EXECUTANDO")
        primeira = processo.avancar_cpu(1, memoria_virtual=vm)
        segunda = processo.avancar_cpu(1, memoria_virtual=vm)
        self.assertIn("[PAGE FAULT DETECTADO]", "\n".join(primeira))
        self.assertIn("[HIT]", "\n".join(segunda))

    def test_fatia_de_cpu_realiza_referencia_por_milissegundo(self):
        vm = MemoriaVirtual(2 * 4 * KB, 4 * KB)
        processo = Processo(
            101, "Ciclos", 8 * KB, "normal", "root",
            burst=4, referencias_paginas=[0, 1, 0],
        )
        vm.criar_processo(processo)
        processo.aceitar()
        processo.transicionar_para("EXECUTANDO")
        processo.avancar_cpu(3, memoria_virtual=vm)
        self.assertEqual(vm.acessos, 3)
        self.assertEqual(processo.indice_referencia, 3)

    def test_referencia_invalida_nao_consume_ciclo_cpu(self):
        vm = MemoriaVirtual(2 * 4 * KB, 4 * KB)
        processo = Processo(
            102, "Fora", 4 * KB, "normal", "root",
            burst=4, referencias_paginas=[1],
        )
        vm.criar_processo(processo)
        processo.aceitar()
        processo.transicionar_para("EXECUTANDO")
        with self.assertRaises(MemoriaError):
            processo.avancar_cpu(1, memoria_virtual=vm)
        self.assertEqual(processo.tempo_cpu, 0)
        self.assertEqual(processo.burst_restante, 4)
        self.assertEqual(processo.indice_referencia, 0)

    def test_referencia_manual_invalida_nao_avanca_sequencia(self):
        vm = MemoriaVirtual(2 * 4 * KB, 4 * KB)
        processo = Processo(
            103, "Manual", 4 * KB, "normal", "root",
            burst=4, referencias_paginas=[1],
        )
        vm.criar_processo(processo)
        with self.assertRaises(MemoriaError):
            processo.executar_referencia_pagina(vm)
        self.assertEqual(processo.indice_referencia, 0)

    def test_criacao_pelo_gerenciador_preserva_memoria(self):
        mem = GerenciadorMemoria(
            ram_total=8 * 1024 ** 2,
            reservada=4 * 1024 ** 2,
        )
        processo = mem.criar_processo(
            "App", 8 * KB, "normal", "root",
            burst=6, prioridade=3,
            syscalls=[Syscall("read_disk", 2, 2)],
            referencias_paginas=[0],
        )
        self.assertEqual(processo.estado, "PRONTO")
        self.assertEqual(processo.burst_restante, 6)
        self.assertEqual(processo.prioridade, 3)


class TestCLIProcessoEtapa5(unittest.TestCase):
    def setUp(self):
        self.sec = Seguranca(iteracoes=1000)
        self.fs = FileSystem(Disk(16, 4096), seguranca=self.sec)
        self.fs.mem = GerenciadorMemoria(sec=self.sec, relatorio_a_cada=0)
        self.sec.login("root", "root")

    def executar_sem_saida(self, comando):
        with contextlib.redirect_stdout(io.StringIO()):
            executar(self.fs, comando)

    def test_create_process_parses_profile(self):
        self.executar_sem_saida(
            "create_process --name App --size 8KB --type normal --burst 8 "
            "--priority 1 --arrival 2 --page 0 --page 1 "
            "--syscall read_disk:3:4"
        )
        processo = self.fs.mem.processos["App"]
        self.assertEqual(processo.estado, "PRONTO")
        self.assertEqual(processo.burst, 8)
        self.assertEqual(processo.prioridade, 1)
        self.assertEqual(processo.tempo_chegada, 2)
        self.assertEqual(processo.referencias_paginas, [0, 1])
        self.assertEqual(processo.syscalls[0].instante_disparo, 3)

    def test_cli_rejeita_syscall_invalida_sem_criar_processo(self):
        with self.assertRaises(SyscallError):
            self.executar_sem_saida(
                "create_process --name App --size 8KB --type normal "
                "--syscall read_disk:3:0"
            )
        self.assertNotIn("App", self.fs.mem.processos)

    def test_cli_rejeita_burst_invalido_sem_criar_processo(self):
        with self.assertRaises(ProcessoError):
            self.executar_sem_saida(
                "create_process --name App --size 8KB --type normal --burst 0"
            )
        self.assertNotIn("App", self.fs.mem.processos)


class TestMutex(unittest.TestCase):
    def test_adquire_libera_e_transferencia(self):
        mutex = Mutex("Buffer_Video")
        t1 = ThreadSimulada("T1")
        t2 = ThreadSimulada("T2")
        self.assertTrue(mutex.adquirir(t1))
        self.assertFalse(mutex.adquirir(t2))
        self.assertEqual(t2.estado, "BLOQUEADO")
        self.assertIs(mutex.liberar(t1), t2)
        self.assertIs(mutex.identificar_proprietario(), t2)

    def test_liberacao_por_nao_proprietario(self):
        mutex = Mutex("Arquivo")
        t1 = ThreadSimulada("T1")
        t2 = ThreadSimulada("T2")
        mutex.adquirir(t1)
        with self.assertRaises(MutexError):
            mutex.liberar(t2)

    def test_fila_multipla(self):
        mutex = Mutex("M")
        threads = [ThreadSimulada(str(i)) for i in range(1, 5)]
        mutex.adquirir(threads[0])
        for thread in threads[1:]:
            mutex.adquirir(thread)
        for thread in threads[1:]:
            atual = mutex.identificar_proprietario()
            mutex.liberar(atual)
            self.assertIs(mutex.identificar_proprietario(), thread)

    def test_threads_distintas_com_mesmos_valores_nao_se_perdem(self):
        mutex = Mutex("Duplicados")
        dono = ThreadSimulada("owner")
        primeira = ThreadSimulada("T", estado="PRONTO")
        segunda = ThreadSimulada("T", estado="PRONTO")
        mutex.adquirir(dono)
        mutex.adquirir(primeira)
        mutex.adquirir(segunda)
        self.assertEqual(mutex.waiting_threads, [primeira, segunda])
        mutex.liberar(dono)
        self.assertIs(mutex.owner, primeira)
        mutex.liberar(primeira)
        self.assertIs(mutex.owner, segunda)

    def test_thread_nao_pode_aguardar_dois_mutexes(self):
        mutex_a = Mutex("A")
        mutex_b = Mutex("B")
        t1 = ThreadSimulada("T1")
        t2 = ThreadSimulada("T2")
        dono_b = ThreadSimulada("DonoB")
        mutex_a.adquirir(t1)
        mutex_a.adquirir(t2)
        mutex_b.adquirir(dono_b)
        with self.assertRaises(MutexError):
            mutex_b.adquirir(t2)
        self.assertEqual(mutex_a.waiting_threads, [t2])
        self.assertEqual(mutex_b.waiting_threads, [])

    def test_thread_bloqueada_por_io_nao_pode_adquirir_mutex(self):
        mutex = Mutex("M")
        thread = ThreadSimulada("T", estado="BLOQUEADO")
        with self.assertRaises(MutexError):
            mutex.adquirir(thread)
        self.assertTrue(mutex.livre)
        self.assertEqual(mutex.waiting_threads, [])


if __name__ == "__main__":
    unittest.main()
