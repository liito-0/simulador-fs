import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from disk import Disk
from fs import FileSystem
from raid import RAID5


def novo():
    fs = FileSystem(Disk(32, 4096))
    fs.device, fs.raid = "raid5", RAID5(3, 4096)
    return fs


class TestRAIDIntegrado(unittest.TestCase):
    def test_write_distribui_dados_e_paridade(self):
        fs = novo()
        fs.create("/p.csv", 8192)
        self.assertEqual(fs.io_queue, [])
        texto = "\n".join(fs.dev_log)
        self.assertIn("Arranjo Ativo: RAID 5 (3 Discos Físicos, Blocos de 4 KB)", texto)
        self.assertIn("Disco 3: [PARIDADE : XOR(Bloco 01, Bloco 02)]", texto)
        self.assertIn("Reconstrução [OK]", texto)
        self.assertIn("/p.csv", fs.raid.files)

    def test_leitura_com_disco_falho_reconstroi(self):
        fs = novo()
        fs.create("/p.csv", 10000)
        fs.raid.fail_disk(1)
        fs.dev_log.clear()
        fs.read("/p.csv")
        texto = "\n".join(fs.dev_log)
        self.assertIn("reconstruídos via XOR", texto)
        self.assertIn("integridade: [OK]", texto)

    def test_update_e_remove(self):
        fs = novo()
        fs.create("/a", 4096)
        fs.update("/a", 12288)
        self.assertEqual(fs.raid.files["/a"]["tamanho"], 12288)
        fs.remove("/a")
        self.assertNotIn("/a", fs.raid.files)

    def test_escrita_bloqueada_com_disco_falho(self):
        fs = novo()
        fs.create("/a", 4096)
        fs.raid.fail_disk(0)
        fs.dev_log.clear()
        fs.update("/a", 4096)
        self.assertIn("ERRO RAID", "\n".join(fs.dev_log))


if __name__ == "__main__":
    unittest.main()
