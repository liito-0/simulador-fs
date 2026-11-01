import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from disk import Disk, DiskError
from fs import FileSystem, FSError


def novo(estrategia="indexada", blocos=16):
    return FileSystem(Disk(blocos, 4096), estrategia)


class TestArvore(unittest.TestCase):
    def test_mkdir_e_caminhos_relativos(self):
        fs = novo()
        fs.mkdir("/sistema"); fs.mkdir("/sistema/logs")
        fs.cd("/sistema"); fs.cd("logs"); fs.cd("..")
        self.assertEqual(fs.path_of(fs.cwd), "/sistema")

    def test_duplicado(self):
        fs = novo(); fs.mkdir("/a")
        with self.assertRaises(FSError):
            fs.mkdir("/a")


class TestIndexada(unittest.TestCase):
    def test_exemplo_enunciado(self):
        fs = novo()
        fs.mkdir("/sistema"); fs.mkdir("/sistema/logs")
        f = fs.create("/sistema/logs/app.log", 10240)
        self.assertEqual(f.alloc["inode"], 1)
        self.assertEqual(f.alloc["data"], [2, 3, 4])

    def test_remover_libera_blocos(self):
        fs = novo(); fs.create("/a", 5000); fs.remove("/a")
        self.assertEqual(len(fs.disk.free_list()), 15)  # só a raiz ocupa


class TestContigua(unittest.TestCase):
    def test_fragmentacao_externa(self):
        fs = novo("contigua", blocos=8)
        for n in "abc":
            fs.create(f"/{n}", 4096)
        fs.remove("/b")
        with self.assertRaises(DiskError):
            fs.create("/grande", 5 * 4096)   # 5 livres (1 + 4), mas não contíguos

    def test_update_falho_desfaz(self):
        fs = novo("contigua", blocos=4)
        fs.create("/a", 4096)
        antes = list(fs.disk.blocks)
        with self.assertRaises(DiskError):
            fs.update("/a", 10 * 4096)
        self.assertEqual(fs.disk.blocks, antes)


if __name__ == "__main__":
    unittest.main()
