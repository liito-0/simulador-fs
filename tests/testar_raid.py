
import unittest

from src.raid import RAID5, RAIDError


class TestRAID5(unittest.TestCase):

    def test_escrita_e_leitura(self):
        raid = RAID5()

        arquivo = raid.write("Minha planilha")

        self.assertEqual(raid.read(arquivo), "Minha planilha")

    def test_distribuicao_de_paridade(self):
        raid = RAID5()

        raid.write("A" * 8192)

        # Com três discos, a paridade deve alternar de disco.
        self.assertEqual(
            [raid._parity_disk(i) for i in range(3)],
            [2, 1, 0]
        )

    def test_recuperacao_de_falha(self):
        raid = RAID5()

        arquivo = raid.write("Dados importantes")

        raid.fail_disk(1)

        self.assertEqual(raid.read(arquivo), "Dados importantes")

        raid.recover(1)

        self.assertEqual(raid.read(arquivo), "Dados importantes")

    def test_falha_de_dois_discos(self):
        raid = RAID5()

        raid.write("Dados importantes")

        raid.fail_disk(0)

        with self.assertRaises(RAIDError):
            raid.fail_disk(1)

    def test_arquivo_binario(self):
        raid = RAID5()

        conteudo = bytes([0, 1, 2, 0, 255, 0])

        arquivo = raid.write(conteudo)

        self.assertEqual(raid.read(arquivo), conteudo)

    def test_multiplos_arquivos(self):
        raid = RAID5()

        arquivo1 = raid.write("Primeiro arquivo")
        arquivo2 = raid.write("Segundo arquivo")

        self.assertEqual(raid.read(arquivo1), "Primeiro arquivo")
        self.assertEqual(raid.read(arquivo2), "Segundo arquivo")

    def test_disco_invalido(self):
        raid = RAID5()

        with self.assertRaises(RAIDError):
            raid.fail_disk(5)


if __name__ == "__main__":
    unittest.main()