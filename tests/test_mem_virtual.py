import contextlib
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from disk import Disk
from fs import FileSystem
from main import executar
from mem_reservada import MemoriaError
from mem_virtual import MemoriaVirtual
from memoria import GerenciadorMemoria
from processo import Processo
from seguranca import PrivilegeError, Seguranca

KB = 1024


def texto(linhas):
    return "\n".join(linhas)


def nova(molduras=3, swap_paginas=16, politica="lru"):
    vm = MemoriaVirtual(molduras * 4 * KB, 4 * KB, tamanho_swap=swap_paginas * 4 * KB)
    vm.definir_politica(politica)
    return vm


def proc(pid, nome, tamanho):
    return Processo(pid, nome, tamanho, "normal", "root")


class TestPaginacao(unittest.TestCase):
    def test_calculo_de_paginas_e_fragmentacao_interna(self):
        vm = nova()
        saida = texto(vm.criar_processo(proc(100, "App", 10 * KB)))
        self.assertIn("2.5 -> Requer 3 Páginas Lógicas (Páginas 0, 1 e 2)", saida)
        self.assertIn("Página Lógica 2 : 2048 Bytes ocupados (50% de uso)", saida)
        self.assertIn("2048 Bytes de desperdício na Página Lógica 2", saida)
        self.assertIn("sem alocar molduras", saida)
        self.assertEqual(vm.molduras_usadas, 0)  # alocação por demanda

    def test_tamanho_multiplo_nao_desperdiça(self):
        vm = nova()
        saida = texto(vm.criar_processo(proc(100, "App", 8 * KB)))
        self.assertIn("0 Bytes (tamanho múltiplo da página)", saida)

    def test_processo_grande_resume_listagem(self):
        vm = nova(swap_paginas=300)
        saida = texto(vm.criar_processo(proc(100, "Grande", 1024 * KB)))
        self.assertIn("Páginas 0 a 255", saida)
        self.assertIn("omitidas", saida)

    def test_traducao_miss_e_hit(self):
        vm = nova()
        p = proc(100, "App", 8 * KB)
        vm.criar_processo(p)
        self.assertIn("[MISS]", texto(vm.traduzir(p, 1)))
        vm.executar_passo(p, "LOAD_DATA Página 1")
        self.assertIn("Moldura Física 0 (RAM Dinâmica) [HIT]", texto(vm.traduzir(p, 1)))

    def test_traducao_usa_base_fisica(self):
        vm = nova()
        vm.base_fisica = 4 * 1024 * KB
        p = proc(100, "App", 8 * KB)
        vm.criar_processo(p)
        vm.executar_passo(p, "LOAD_DATA Página 0")
        self.assertIn("0x00400000", texto(vm.traduzir(p, 0)))

    def test_pagina_invalida(self):
        vm = nova()
        p = proc(100, "App", 8 * KB)
        vm.criar_processo(p)
        for pag in (2, -1):
            with self.assertRaisesRegex(MemoriaError, "Violação de segmentação"):
                vm.traduzir(p, pag)
        with self.assertRaises(MemoriaError):
            vm.executar_passo(p, "LOAD_DATA Página 9")
        with self.assertRaises(MemoriaError):
            vm.executar_passo(p, "JUMP Página 0")
        with self.assertRaises(MemoriaError):
            vm.executar_passo(p, "LOAD_DATA")

    def test_limite_do_espaco_virtual(self):
        vm = nova(swap_paginas=4)
        vm.criar_processo(proc(100, "A", 12 * KB))
        with self.assertRaisesRegex(MemoriaError, "Memória virtual insuficiente"):
            vm.criar_processo(proc(101, "B", 8 * KB))


class TestPageFault(unittest.TestCase):
    def test_fault_com_moldura_livre_e_hit(self):
        vm = nova()
        p = proc(100, "App", 8 * KB)
        vm.criar_processo(p)
        s1 = texto(vm.executar_passo(p, "LOAD_DATA Página 0"))
        self.assertIn("[PAGE FAULT DETECTADO]", s1)
        self.assertIn("sem substituição", s1)
        s2 = texto(vm.executar_passo(p, "LOAD_DATA Página 0"))
        self.assertIn("[HIT]", s2)
        self.assertEqual((vm.acessos, vm.hits, vm.faults), (2, 1, 1))

    def test_lru_remove_a_menos_recente_e_salva_no_swap(self):
        vm = nova(molduras=3)
        p = proc(100, "App", 16 * KB)
        vm.criar_processo(p)
        for pag in (0, 1, 2):
            vm.executar_passo(p, f"LOAD_DATA Página {pag}")
        vm.executar_passo(p, "LOAD_DATA Página 0")   # 0 volta a ser recente; 1 é a mais antiga
        saida = texto(vm.executar_passo(p, "LOAD_DATA Página 3"))
        self.assertIn("Memória RAM cheia", saida)
        self.assertIn("Página Lógica 1 de 'App' (PID 100) não é usada há", saida)
        self.assertIn("Salvando no Swap", saida)
        self.assertIsNone(vm.tabelas[100][1].frame)
        self.assertIsNotNone(vm.tabelas[100][1].slot)
        self.assertEqual(vm.swap_out, 1)

    def test_pagina_trazida_de_volta_do_swap(self):
        vm = nova(molduras=1)
        p = proc(100, "App", 8 * KB)
        vm.criar_processo(p)
        vm.executar_passo(p, "LOAD_DATA Página 0")
        vm.executar_passo(p, "LOAD_DATA Página 1")
        saida = texto(vm.executar_passo(p, "LOAD_DATA Página 0"))
        self.assertIn("do Swap", saida)
        self.assertEqual(vm.swap_in, 1)

    def test_pagina_limpa_com_copia_no_swap_e_descartada(self):
        vm = nova(molduras=1)
        p = proc(100, "App", 8 * KB)
        vm.criar_processo(p)
        vm.executar_passo(p, "LOAD_DATA Página 0")
        vm.executar_passo(p, "LOAD_DATA Página 1")   # 0 -> swap (sem cópia)
        vm.executar_passo(p, "LOAD_DATA Página 0")   # 1 -> swap, 0 volta limpa
        saida = texto(vm.executar_passo(p, "LOAD_DATA Página 1"))
        self.assertIn("descartada sem escrita", saida)
        self.assertEqual(vm.descartes, 1)

    def test_pagina_suja_e_regravada(self):
        vm = nova(molduras=1)
        p = proc(100, "App", 8 * KB)
        vm.criar_processo(p)
        vm.executar_passo(p, "LOAD_DATA Página 0")
        vm.executar_passo(p, "LOAD_DATA Página 1")
        vm.executar_passo(p, "STORE_DATA Página 0")  # traz 0 e suja
        saida = texto(vm.executar_passo(p, "LOAD_DATA Página 1"))
        self.assertIn("(modificada)", saida)

    def test_substituicao_global_entre_processos(self):
        vm = nova(molduras=2)
        a, b = proc(100, "A", 4 * KB), proc(101, "B", 8 * KB)
        vm.criar_processo(a)
        vm.criar_processo(b)
        vm.executar_passo(a, "LOAD_DATA Página 0")
        vm.executar_passo(b, "LOAD_DATA Página 0")
        saida = texto(vm.executar_passo(b, "LOAD_DATA Página 1"))
        self.assertIn("Página Lógica 0 do PID 100", saida)

    def test_fifo_ignora_acessos_recentes(self):
        vm = nova(molduras=2, politica="fifo")
        p = proc(100, "App", 12 * KB)
        vm.criar_processo(p)
        vm.executar_passo(p, "LOAD_DATA Página 0")
        vm.executar_passo(p, "LOAD_DATA Página 1")
        vm.executar_passo(p, "LOAD_DATA Página 0")   # LRU poparia a 1; FIFO tira a 0
        vm.executar_passo(p, "LOAD_DATA Página 2")
        self.assertIsNone(vm.tabelas[100][0].frame)
        self.assertIsNotNone(vm.tabelas[100][1].frame)

    def test_segunda_chance(self):
        vm = nova(molduras=2, politica="second_chance")
        p = proc(100, "App", 12 * KB)
        vm.criar_processo(p)
        vm.executar_passo(p, "LOAD_DATA Página 0")
        vm.executar_passo(p, "LOAD_DATA Página 1")
        saida = texto(vm.executar_passo(p, "LOAD_DATA Página 2"))
        # ambas com R=1: ambas ganham segunda chance e a primeira da fila é vítima
        self.assertEqual(saida.count("SEGUNDA CHANCE"), 2)
        self.assertIn("R=0 -> VÍTIMA", saida)
        self.assertIsNone(vm.tabelas[100][0].frame)

    def test_segunda_chance_poupa_pagina_referenciada(self):
        vm = nova(molduras=2, politica="second_chance")
        p = proc(100, "App", 16 * KB)
        vm.criar_processo(p)
        vm.executar_passo(p, "LOAD_DATA Página 0")
        vm.executar_passo(p, "LOAD_DATA Página 1")
        vm.executar_passo(p, "LOAD_DATA Página 2")   # varre, limpa R, vítima = pág 0
        vm.executar_passo(p, "LOAD_DATA Página 1")   # R(1)=1 de novo
        vm.executar_passo(p, "LOAD_DATA Página 3")   # fila: 1(R=1), 2(R=1) -> poupa 1, 2; depois vítima 1
        self.assertEqual(vm.faults, 4)
        self.assertIsNotNone(vm.tabelas[100][2].frame)   # poupada
        self.assertIsNotNone(vm.tabelas[100][3].frame)   # recém-carregada
        self.assertIsNone(vm.tabelas[100][1].frame)      # vítima após a volta completa

    def test_politica_invalida(self):
        with self.assertRaises(MemoriaError):
            nova().definir_politica("optimal")

    def test_encerrar_libera_molduras_e_swap(self):
        vm = nova(molduras=1)
        p = proc(100, "App", 8 * KB)
        vm.criar_processo(p)
        vm.executar_passo(p, "LOAD_DATA Página 0")
        vm.executar_passo(p, "LOAD_DATA Página 1")
        livres_antes = len(vm.slots_livres)
        saida = texto(vm.encerrar_processo(p))
        self.assertIn("1 moldura(s)", saida)
        self.assertEqual(vm.molduras_livres, 1)
        self.assertEqual(len(vm.slots_livres), livres_antes + 1)
        self.assertEqual(vm.paginas_alocadas, 0)
        self.assertEqual(len(vm.fila), 0)

    def test_status_e_relatorio(self):
        vm = nova()
        self.assertIn("Nenhum processo", texto(vm.relatorio_fragmentacao_interna()))
        p = proc(100, "App", 10 * KB)
        vm.criar_processo(p)
        vm.executar_passo(p, "STORE_DATA Página 2")
        status = texto(vm.status())
        self.assertIn("Page faults: 1", status)
        self.assertIn("[RM]", status)
        self.assertIn("desperdício 2048 B", texto(vm.relatorio_fragmentacao_interna()))


class TestIntegracaoShell(unittest.TestCase):
    def setUp(self):
        self.sec = Seguranca(iteracoes=1000)
        self.fs = FileSystem(Disk(16, 4096), seguranca=self.sec)
        # RAM dinâmica com 2 molduras
        self.fs.mem = GerenciadorMemoria(4 * 1024 * KB + 8 * KB, 4 * 1024 * KB, 4 * KB,
                                         self.sec, 0)
        self.sec.login("root", "root")

    def cmd(self, linha):
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            executar(self.fs, linha)
        return saida.getvalue()

    def test_fluxo_completo(self):
        self.assertEqual(self.fs.mem.virtual.base_fisica, 4 * 1024 * KB)
        self.cmd("create_process --name Nav --size 10KB --type normal")
        self.assertIn("[MISS]", self.cmd("translate_address --process Nav --page 0"))
        for pag in (0, 1, 2):
            self.cmd(f'execute_step --process Nav --instruction "LOAD_DATA Página {pag}"')
        status = self.cmd("memory_status --virtual")
        self.assertIn("Page faults: 3", status)
        self.assertIn("Swap-out: 1", status)
        self.assertIn("Moldura", self.cmd("memory_status"))
        self.assertIn("FRAGMENTAÇÃO INTERNA", self.cmd("memory_report"))
        self.assertIn("LRU", self.cmd("memory_policy"))
        self.assertIn("Segunda Chance", self.cmd("memory_policy second_chance"))
        eventos = [e["evento"] for e in self.sec.auditoria]
        self.assertIn("MEM_PAGE_FAULT", eventos)
        self.assertIn("MEM_SWAP_OUT", eventos)
        self.assertIn("liberada", self.cmd("terminate_process --name Nav"))

    def test_trocar_politica_exige_kernel(self):
        self.sec.useradd("alice", "alice123")
        self.sec.logout()
        self.sec.login("alice", "alice123")
        with self.assertRaises(PrivilegeError):
            executar(self.fs, "memory_policy fifo")
        self.assertIn("LRU", self.cmd("memory_policy"))

    def test_nao_cria_processo_maior_que_espaco_virtual(self):
        fs_mem = GerenciadorMemoria(4 * 1024 * KB + 8 * KB, 4 * 1024 * KB, 4 * KB,
                                    self.sec, 0, tamanho_swap=8 * KB)
        with self.assertRaises(MemoriaError):
            fs_mem.criar_processo("Grande", 64 * KB, "normal", "root")


if __name__ == "__main__":
    unittest.main()
