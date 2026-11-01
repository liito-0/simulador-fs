import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from allocation import STRATEGIES
from diagnostico import compactar, relatorio_fragmentacao
from disk import Disk, DiskError
from fs import FileSystem


def novo(estrategia="indexada", blocos=16):
    return FileSystem(Disk(blocos, 4096), estrategia)


class TestEncadeada(unittest.TestCase):
    def test_aloca_em_blocos_dispersos_e_finaliza_encadeamento(self):
        fs = novo("contigua", blocos=8)
        fs.create("/a", 4096)
        fs.create("/b", 4096)
        fs.remove("/a")

        f = fs.create("/encadeado", 8192, "encadeada")

        self.assertEqual(f.alloc, {"inode": None, "data": [1, 3]})
        self.assertEqual(fs.disk.blocks[1]["detalhe"], "-> próximo: Bloco 03")
        self.assertEqual(fs.disk.blocks[3]["detalhe"], "-> FIM")
        self.assertIs(STRATEGIES["encadeada"], STRATEGIES[f.strategy])

    def test_disco_cheio(self):
        fs = novo(blocos=4)
        fs.create("/ocupado", 3 * 4096, "encadeada")

        with self.assertRaisesRegex(
                DiskError, "Disco cheio: precisa de 1 blocos, só há 0 livres\\."):
            fs.create("/sem-espaco", 4096, "encadeada")


class TestDiagnostico(unittest.TestCase):
    def test_relatorio_fragmentacao_interna_do_app_log(self):
        fs = novo()
        f = fs.create("/app.log", 10240)

        relatorio = relatorio_fragmentacao(fs)

        self.assertEqual(f.alloc["data"], [2, 3, 4])
        self.assertIn("Tamanho Real do Arquivo 'app.log': 10240 bytes (10 KB)", relatorio)
        self.assertIn("Espaço Alocado no Disco         : 12288 bytes (3 blocos de 4 KB)",
                      relatorio)
        self.assertIn("Fragmentação Interna            : 2048 bytes "
                      "(50% de desperdício no Bloco 04)", relatorio)
        self.assertIn("Fragmentação Externa            : 0 bytes", relatorio)

    def test_fragmentacao_externa_exige_compactacao_contigua(self):
        fs = novo("contigua", blocos=8)
        for nome in "abc":
            fs.create(f"/{nome}", 4096)
        fs.remove("/b")

        relatorio = relatorio_fragmentacao(fs)

        self.assertIn("Fragmentação Externa            : 4096 bytes", relatorio)
        self.assertIn("Necessidade de Compactação      : SIM", relatorio)

    def test_compacta_e_permite_criar_arquivo_grande(self):
        fs = novo("contigua", blocos=8)
        for nome in "abc":
            fs.create(f"/{nome}", 4096)
        fs.remove("/b")
        with self.assertRaises(DiskError):
            fs.create("/grande", 5 * 4096)

        resultado = compactar(fs)

        self.assertIn("Compactação concluída: 1 blocos movidos.", resultado)
        self.assertLessEqual(len(fs.disk.free_runs()), 1)
        arquivo = fs.create("/grande", 5 * 4096)
        self.assertEqual(len(arquivo.alloc["data"]), 5)


if __name__ == "__main__":
    unittest.main()
