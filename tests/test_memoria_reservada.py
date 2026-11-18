import contextlib
import io
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import memoria
from disk import Disk
from fs import FileSystem
from main import executar
from mem_reservada import MemoriaError, RegiaoReservada
from memoria import GerenciadorMemoria
from seguranca import PrivilegeError, Seguranca

KB = 1024
MB = 1024 * KB


class MemoriaVirtualFalsa:
    def __init__(self, tamanho_dinamico, tamanho_pagina, sec=None):
        self.processos = {}

    def criar_processo(self, proc):
        self.processos[proc.nome] = proc
        return ["Processo virtual criado."]

    def encerrar_processo(self, proc):
        del self.processos[proc.nome]
        return ["Processo virtual encerrado."]

    def traduzir(self, proc, pagina):
        return [f"Tradução de {proc.nome}, página {pagina}."]

    def executar_passo(self, proc, instrucao):
        return [f"{proc.nome}: {instrucao}"]

    def status(self):
        return ["Status virtual."]

    def relatorio_fragmentacao_interna(self):
        return ["Fragmentação interna virtual: 0 KB."]


def capturar_comando(fs, linha):
    saida = io.StringIO()
    with contextlib.redirect_stdout(saida):
        executar(fs, linha)
    return saida.getvalue()


class TestRegiaoReservada(unittest.TestCase):
    def setUp(self):
        self.regiao = RegiaoReservada()

    def test_enderecos_exemplo_e_diagnostico(self):
        self.regiao.alocar("Kernel_DiskDriver", 512 * KB)
        self.regiao.alocar("Kernel_NetDriver", MB)
        self.regiao.alocar("Kernel_CryptoEngine", 512 * KB)
        self.regiao.liberar("Kernel_NetDriver")
        self.assertEqual(self.regiao.alocacoes["Kernel_DiskDriver"], (MB, 1536 * KB))
        self.assertEqual(self.regiao.alocacoes["Kernel_CryptoEngine"], (2560 * KB, 3 * MB))
        diagnostico = "\n".join(self.regiao.diagnostico())
        self.assertIn("2048 KB (2.0 MB)", diagnostico)
        self.assertIn("1024 KB (1.0 MB)", diagnostico)
        self.assertIn("SIM (2 fragmentos não contíguos)", diagnostico)
        self.assertIn("requisição contígua de 1536 KB falhará", diagnostico)

    def test_compactacao_move_crypto_e_reaproveita_lacuna(self):
        self.regiao.alocar("Disk", 512 * KB)
        self.regiao.alocar("Net", MB)
        self.regiao.alocar("Crypto", 512 * KB)
        self.regiao.liberar("Net")
        movimentos = self.regiao.compactar()
        self.assertEqual(movimentos, [("Crypto", 2560 * KB, 3 * MB, 1536 * KB, 2 * MB)])
        self.assertEqual(self.regiao.maior_bloco, 2 * MB)
        self.assertFalse(self.regiao.fragmentacao_externa)
        self.regiao.liberar("Disk")
        self.assertEqual(self.regiao.alocar("Novo", 1024 * KB), (2 * MB, 3 * MB))

    def test_first_fit_junta_lacunas_e_nome_unico(self):
        self.regiao.alocar("A", 512 * KB)
        self.regiao.alocar("B", 512 * KB)
        self.regiao.alocar("C", 512 * KB)
        self.regiao.liberar("A")
        self.regiao.liberar("B")
        self.assertEqual(self.regiao.alocar("D", 768 * KB), (MB, 1792 * KB))
        with self.assertRaisesRegex(MemoriaError, "Já existe"):
            self.regiao.alocar("D", KB)
        self.regiao.liberar("C")
        self.regiao.liberar("D")
        self.assertEqual(self.regiao.lacunas(), [(MB, 4 * MB)])

    def test_falha_por_fragmentacao_externa_e_nucleo_protegido(self):
        for nome, tamanho in (("A", 512 * KB), ("B", MB),
                              ("C", 512 * KB), ("D", MB)):
            self.regiao.alocar(nome, tamanho)
        self.regiao.liberar("B")
        self.regiao.liberar("D")
        with self.assertRaisesRegex(
                MemoriaError, "fragmentação externa: há 2048 KB livres, "
                              "mas o maior bloco contíguo é 1024 KB"):
            self.regiao.alocar("E", 1536 * KB)
        with self.assertRaisesRegex(MemoriaError, "fixo"):
            self.regiao.liberar("Núcleo Base do SO")
        with self.assertRaisesRegex(MemoriaError, "fixo"):
            self.regiao.alocar("Núcleo Base do SO", KB)


class TestIntegracaoMemoria(unittest.TestCase):
    def setUp(self):
        self.patch_virtual = patch.object(memoria, "MemoriaVirtual", MemoriaVirtualFalsa)
        self.patch_virtual.start()
        self.addCleanup(self.patch_virtual.stop)
        self.sec = Seguranca(iteracoes=1000)
        self.fs = FileSystem(Disk(16, 4096), seguranca=self.sec)
        self.fs.mem = GerenciadorMemoria(sec=self.sec, relatorio_a_cada=0)
        self.sec.login("root", "root")

    def test_privilégios_dono_auditoria_e_compactacao_com_sudo(self):
        self.sec.useradd("alice", "alice123", "admin")
        self.sec.useradd("bob", "bob123")
        self.sec.logout()
        self.sec.login("alice", "alice123")
        with self.assertRaises(PrivilegeError):
            executar(self.fs, "create_process --name critical --size 1KB --type critical")
        with self.assertRaises(PrivilegeError):
            executar(self.fs, "memory_compact --reserved")
        capturar_comando(
            self.fs, "create_process --name normal --size 2KB --type normal"
        )
        self.sec.logout()
        self.sec.login("bob", "bob123")
        with self.assertRaises(PrivilegeError):
            executar(self.fs, "terminate_process --name normal")
        self.assertEqual(self.sec.auditoria[-1]["evento"], "PROC_NEGADO")
        self.sec.logout()
        self.sec.login("alice", "alice123")
        capturar_comando(self.fs, "terminate_process --name normal")
        capturar_comando(self.fs, "sudo --password alice123 memory_compact --reserved")
        eventos = [item["evento"] for item in self.sec.auditoria]
        self.assertIn("PROC_CRIADO", eventos)
        self.assertIn("PROC_ENCERRADO", eventos)
        self.assertIn("MEM_COMPACT", eventos)

    def test_shell_exemplo_reservada_compactacao_e_relatorio_periodico(self):
        self.fs.mem.relatorio_a_cada = 0
        capturar_comando(self.fs, "create_process --name Kernel_DiskDriver "
                                  "--size 512KB --type critical")
        capturar_comando(self.fs, "create_process --name Kernel_NetDriver "
                                  "--size 1MB --type critical")
        capturar_comando(self.fs, "create_process --name Kernel_CryptoEngine "
                                  "--size 512KB --type critical")
        encerramento = capturar_comando(
            self.fs, "terminate_process --name Kernel_NetDriver"
        )
        self.assertIn("[ENCERRAMENTO DE PROCESSO CRÍTICO] Processo 'Kernel_NetDriver' finalizado.",
                      encerramento)
        mapa = capturar_comando(self.fs, "memory_status --reserved")
        self.assertIn("[1.5 MB - 2.5 MB] : FRAGMENTO LIVRE 1", mapa)
        self.assertIn("SIM (2 fragmentos não contíguos)", mapa)
        compactacao = capturar_comando(self.fs, "memory_compact --reserved")
        self.assertIn("[2.5 MB a 3.0 MB] -> Ajustado para: [1.5 MB a 2.0 MB]",
                      compactacao)
        self.assertIn("Maior bloco contíguo: 2048 KB.", compactacao)
        self.fs.mem.relatorio_a_cada = 1
        relatorio = capturar_comando(
            self.fs, "create_process --name Kernel_New --size 4KB --type critical"
        )
        self.assertIn("--- RELATÓRIO PERIÓDICO DE FRAGMENTAÇÃO ---", relatorio)

    def test_falha_auditada_e_shell_normal_roteado(self):
        self.fs.mem.relatorio_a_cada = 0
        self.fs.mem.criar_processo("A", 2 * MB, "critical", "root")
        with self.assertRaises(MemoriaError):
            self.fs.mem.criar_processo("B", 2 * MB, "critical", "root")
        self.assertEqual(self.sec.auditoria[-1]["evento"], "MEM_FALHA")
        saida = capturar_comando(
            self.fs, "create_process --name normal --size 1KB --type normal"
        )
        self.assertIn("Processo virtual criado.", saida)
        traduzida = capturar_comando(
            self.fs, "translate_address --process normal --page 2"
        )
        self.assertIn("página 2", traduzida)
        instrucao = capturar_comando(
            self.fs, 'execute_step --process normal --instruction "LOAD_DATA Página 2"'
        )
        self.assertIn("normal: LOAD_DATA Página 2", instrucao)
        processos = capturar_comando(self.fs, "ps")
        self.assertIn("PID", processos)
        self.assertIn("normal", processos)

    def test_virtual_indisponivel_tem_erro_claro(self):
        with patch.object(memoria, "MemoriaVirtual", None):
            sem_virtual = GerenciadorMemoria(sec=self.sec)
            with self.assertRaisesRegex(MemoriaError, "módulo da parte B ainda não integrado"):
                sem_virtual.criar_processo("normal", KB, "normal", "root")


if __name__ == "__main__":
    unittest.main()
