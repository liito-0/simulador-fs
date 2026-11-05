import contextlib
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from disk import Disk
from fs import FileSystem, FSError
from io_request import IORequest
from main import executar
from scheduler import fcfs, sstf, scan, cscan


class TestEscalonamento(unittest.TestCase):
    def setUp(self):
        self.tracks = [98, 183, 37, 122, 14]

    def test_fcfs(self):
        order, movements, total = fcfs(self.tracks, 53, 199)
        self.assertEqual(order, self.tracks)
        self.assertEqual(total, 469)
        self.assertEqual(movements, self.tracks)

    def test_sstf_exemplo(self):
        order, movements, total = sstf(self.tracks, 53, 199)
        self.assertEqual(order, [37, 14, 98, 122, 183])
        self.assertEqual(movements, order)
        self.assertEqual(total, 208)

    def test_scan_subindo(self):
        order, movements, total = scan(self.tracks, 53, 199)
        self.assertEqual(order, [98, 122, 183, 37, 14])
        self.assertEqual(movements, [98, 122, 183, 199, 37, 14])
        self.assertEqual(total, 331)

    def test_cscan_subindo_inclui_salto(self):
        order, movements, total = cscan(self.tracks, 53, 199)
        self.assertEqual(order, [98, 122, 183, 14, 37])
        self.assertEqual(movements, [98, 122, 183, 199, 0, 14, 37])
        self.assertEqual(total, 382)

    def test_duplicadas_sao_atendidas_sem_movimento(self):
        order, movements, total = fcfs([2, 2, 1], 2, 10)
        self.assertEqual(order, [2, 2, 1])
        self.assertEqual(movements, [2, 2, 1])
        self.assertEqual(total, 1)

    def test_fila_vazia(self):
        for scheduler in (fcfs, sstf, scan, cscan):
            self.assertEqual(scheduler([], 53, 199), ([], [], 0))


class TestIntegracaoIO(unittest.TestCase):
    def setUp(self):
        self.fs = FileSystem(Disk(20, 4096), "indexada")

    def test_create_e_read_enfileiram_blocos(self):
        self.fs.create("/arquivo", 4096)
        self.assertEqual(self.fs.io_queue, [
            IORequest("W", 1, 1, "/arquivo"),
            IORequest("W", 2, 2, "/arquivo"),
        ])
        self.fs.read("/arquivo")
        self.assertEqual([request.op for request in self.fs.io_queue], ["W", "W", "R", "R"])
        self.assertEqual([request.block for request in self.fs.io_queue[-2:]], [1, 2])

    def test_write_file_via_executar(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            executar(self.fs, "write_file /dados.bin --size 8KB")
        self.assertEqual([request.op for request in self.fs.io_queue], ["W", "W", "W"])
        self.assertIn("[E/S] Requisições de leitura/escrita pendentes nas trilhas: [1, 2, 3]",
                      output.getvalue())

    def test_update_enfileira_escritas_depois_de_concluir(self):
        self.fs.create("/arquivo", 4096)
        self.fs.io_queue.clear()
        self.fs.update("/arquivo", 8192)
        self.assertEqual([(request.op, request.block) for request in self.fs.io_queue],
                         [("W", 1), ("W", 2), ("W", 3)])

    def test_disk_sched_tracks_explicitas_preservam_fila(self):
        self.fs.create("/arquivo", 4096)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            executar(self.fs, "disk_sched sstf --head 53 --max-track 199 "
                              "--tracks 98,183,37,122,14")
        self.assertIn("Ordem de Atendimento : 53 -> 37 -> 14 -> 98 -> 122 -> 183",
                      output.getvalue())
        self.assertIn("208 trilhas", output.getvalue())
        self.assertEqual(self.fs.disk.head, 183)
        self.assertEqual(len(self.fs.io_queue), 2)

    def test_disk_sched_rejeita_trilha_fora_do_limite(self):
        with self.assertRaises(FSError):
            executar(self.fs, "disk_sched fcfs --tracks 200 --max-track 199")

    def test_fila_vazia_pode_ser_escalonada(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            executar(self.fs, "disk_sched all")
        self.assertIn("0 trilhas", output.getvalue())


if __name__ == "__main__":
    unittest.main()
