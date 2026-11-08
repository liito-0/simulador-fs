
import os
import sys
import unittest

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "src")
)

from ssd import SSD, SSDError


class TestSSD(unittest.TestCase):

    def setUp(self):
        self.ssd = SSD(total_blocks=4, pages_per_block=4)

    def test_escrita_e_leitura(self):
        self.ssd.write(0, "Olá")

        self.assertEqual(self.ssd.read(0), "Olá")
        self.assertEqual(self.ssd.write_count, 1)
        self.assertEqual(self.ssd.read_count, 1)

    def test_sobrescrita_invalida_pagina_antiga(self):
        pagina_antiga = self.ssd.write(0, "Antigo")
        pagina_nova = self.ssd.write(0, "Novo")

        self.assertNotEqual(pagina_antiga, pagina_nova)
        self.assertFalse(self.ssd.pages[pagina_antiga]["valid"])
        self.assertTrue(self.ssd.pages[pagina_nova]["valid"])
        self.assertEqual(self.ssd.read(0), "Novo")

    def test_leitura_de_pagina_inexistente(self):
        with self.assertRaises(SSDError):
            self.ssd.read(10)

    def test_trim_invalida_pagina(self):
        self.ssd.write(0, "Dados")
        self.ssd.trim(0)

        self.assertNotIn(0, self.ssd.mapping)
        self.assertEqual(self.ssd.status()["paginas_invalidas"], 1)

    def test_coleta_de_lixo(self):
        self.ssd.write(0, "A")
        self.ssd.write(1, "B")
        self.ssd.write(2, "C")

        for i in range(20):
            self.ssd.write(0, f"Atualização {i}")

        status = self.ssd.status()

        self.assertGreater(status["coletas_lixo"], 0)
        self.assertGreater(status["apagamentos"], 0)
        self.assertEqual(self.ssd.read(0), "Atualização 19")
        self.assertEqual(self.ssd.read(1), "B")
        self.assertEqual(self.ssd.read(2), "C")

    def test_distribuicao_do_wear_leveling(self):
        for i in range(20):
            self.ssd.write(0, f"Atualização {i}")

        desgaste = [
            item["apagamentos"]
            for item in self.ssd.wear_report()
        ]

        self.assertGreater(sum(desgaste), 0)
        self.assertLessEqual(
            max(desgaste) - min(desgaste), 1
        )

    def test_capacidade_logica(self):
        ssd = SSD(total_blocks=2, pages_per_block=2)

        for i in range(ssd.capacity_pages):
            ssd.write(i, f"Dado {i}")

        with self.assertRaises(SSDError):
            ssd.write(ssd.capacity_pages, "Sem espaço")


if __name__ == "__main__":
    unittest.main()
