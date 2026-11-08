import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from disk import Disk
from fs import FileSystem
from ssd import SSD


def novo(device):
    fs = FileSystem(Disk(16, 4096))
    fs.device, fs.ssd = device, SSD(total_blocks=8, pages_per_block=4)
    return fs


class TestSSDIntegrado(unittest.TestCase):
    def test_hdd_continua_gerando_fila(self):
        fs = novo("hdd")
        fs.create("/a", 8192)
        self.assertEqual(len(fs.io_queue), 3)
        self.assertEqual(fs.ssd.write_count, 0)

    def test_ssd_traduz_blocos_em_paginas(self):
        fs = novo("ssd")
        fs.create("/a", 8192)
        self.assertEqual(fs.io_queue, [])           # sem fila de trilhas
        self.assertEqual(fs.ssd.write_count, 3)     # inode + 2 dados
        fs.read("/a")
        self.assertEqual(fs.ssd.read_count, 3)

    def test_updates_repetidos_causam_gc_e_desgaste(self):
        fs = novo("ssd")
        fs.create("/a", 8192)
        for _ in range(10):
            fs.update("/a", 8192)
        self.assertGreater(fs.ssd.gc_count, 0)
        self.assertGreater(sum(fs.ssd.erase_count), 0)

    def test_remove_faz_trim(self):
        fs = novo("ssd")
        fs.create("/a", 8192)
        fs.remove("/a")
        self.assertEqual(fs.ssd.mapping, {})


if __name__ == "__main__":
    unittest.main()
