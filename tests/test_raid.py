import os, sys, unittest
import re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from disk import Disk
from fs import FileSystem
from fs import FSError
from main import executar
from raid import RAID5, RAIDError


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

    def test_mv_arquivo_preserva_integridade_e_remove_do_raid(self):
        fs = novo()
        fs.create("/a.txt", 4096)
        quantidade = fs.raid.status()["arquivos"]
        fs.move("/a.txt", "/b.txt")
        fs.dev_log.clear()
        fs.read("/b.txt")
        self.assertIn("integridade: [OK]", "\n".join(fs.dev_log))
        self.assertEqual(fs.raid.status()["arquivos"], quantidade)
        self.assertIn("/b.txt", fs.raid.files)
        fs.remove("/b.txt")
        self.assertEqual(fs.raid.files, {})

    def test_mv_para_diretorio_e_diretorio_com_arquivos(self):
        fs = novo()
        fs.mkdir("/destino")
        fs.mkdir("/pasta")
        fs.mkdir("/pasta/sub")
        fs.create("/a.txt", 4096)
        fs.create("/pasta/x.txt", 4096)
        fs.create("/pasta/sub/y.txt", 4096)
        fs.move("/a.txt", "/destino")
        fs.move("/pasta", "/destino/nova")
        self.assertIn("/destino/a.txt", fs.raid.files)
        self.assertIn("/destino/nova/x.txt", fs.raid.files)
        self.assertIn("/destino/nova/sub/y.txt", fs.raid.files)
        fs.dev_log.clear()
        fs.read("/destino/nova/sub/y.txt")
        self.assertIn("integridade: [OK]", "\n".join(fs.dev_log))

    def test_rm_recursivo_remove_arquivos_do_raid(self):
        fs = novo()
        fs.mkdir("/pasta")
        fs.mkdir("/pasta/sub")
        fs.create("/pasta/a", 4096)
        fs.create("/pasta/sub/b", 4096)
        fs.remove("/pasta", recursive=True)
        self.assertEqual(fs.raid.files, {})

    def test_escritas_bloqueadas_com_disco_falho_sem_alteracoes(self):
        fs = novo()
        fs.create("/existente", 4096)
        fs.raid.fail_disk(0)
        arvore = fs.tree()
        arquivos = dict(fs.raid.files)
        blocos = list(fs.disk.blocks)
        fila = list(fs.io_queue)
        log = list(fs.dev_log)
        erro = "Há disco com falha no RAID; recupere-o (raid_recover) antes de gravar."
        with self.assertRaisesRegex(FSError, re.escape(erro)):
            fs.create("/novo", 4096)
        with self.assertRaisesRegex(FSError, re.escape(erro)):
            executar(fs, "write_file /escrita --size 4KB", raid=fs.raid)
        with self.assertRaisesRegex(FSError, re.escape(erro)):
            fs.update("/existente", 8192)
        self.assertEqual(fs.tree(), arvore)
        self.assertEqual(fs.raid.files, arquivos)
        self.assertEqual(fs.disk.blocks, blocos)
        self.assertEqual(fs.io_queue, fila)
        self.assertEqual(fs.dev_log, log)

        fs.dev_log.clear()
        fs.read("/existente")
        texto = "\n".join(fs.dev_log)
        self.assertIn("reconstruídos via XOR", texto)
        self.assertIn("integridade: [OK]", texto)

        fs.raid.recover(0)
        fs.create("/novo", 4096)
        self.assertIn("/novo", fs.raid.files)

    def test_rollback_de_create_e_update_se_raid_falhar(self):
        fs = novo()
        fs.create("/existente", 4096)
        estado_disco = list(fs.disk.blocks)
        arquivos_raid = dict(fs.raid.files)
        gravar = fs.raid.write

        def falhar(*args, **kwargs):
            raise RAIDError("falha simulada")

        fs.raid.write = falhar
        with self.assertRaisesRegex(RAIDError, "falha simulada"):
            fs.create("/novo", 4096)
        with self.assertRaises(FSError):
            fs.resolve("/novo")
        self.assertEqual(fs.disk.blocks, estado_disco)
        self.assertEqual(fs.raid.files, arquivos_raid)

        fs.raid.write = gravar
        fs.update("/existente", 8192)
        estado_disco = list(fs.disk.blocks)
        tamanho = fs.resolve("/existente").size
        meta = dict(fs.raid.files["/existente"])
        fs.raid.write = falhar
        with self.assertRaisesRegex(RAIDError, "falha simulada"):
            fs.update("/existente", 12288)
        self.assertEqual(fs.disk.blocks, estado_disco)
        self.assertEqual(fs.resolve("/existente").size, tamanho)
        self.assertEqual(fs.raid.files["/existente"], meta)


if __name__ == "__main__":
    unittest.main()
