import contextlib
import io
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from disk import Disk
from fs import FSError, FileSystem
from main import executar, mascarar
from seguranca import Seguranca


def shell(fs, linha):
    saida = io.StringIO()
    with contextlib.redirect_stdout(saida):
        executar(fs, linha)
    return saida.getvalue()


class TestCriptografia(unittest.TestCase):
    def setUp(self):
        sec = Seguranca(iteracoes=1000)
        self.fs = FileSystem(Disk(16, 16), seguranca=sec)
        sec.login("root", "root")
        self.arquivo = self.fs.create("/segredo", content="texto confidencial")
        self.chave = "chave-teste-123"

    def test_cifrar_descriptografar_e_blocos_fisicos(self):
        claro = self.fs.cat("/segredo").encode("utf-8")
        saida = shell(self.fs, "encrypt_file /segredo --key " + self.chave)
        self.assertRegex(saida, re.compile(r"0x[0-9A-F]{7} "))
        cifrado = self.fs._ler_conteudo(self.arquivo)
        self.assertNotEqual(cifrado, claro)
        self.assertEqual(self.fs.cat("/segredo"), cifrado.hex().upper())
        self.assertEqual(self.fs.cat("/segredo", self.chave), claro.decode())
        with self.assertRaises(FSError):
            self.fs.decrypt_file("/segredo", "chave-errada")
        self.assertEqual(self.fs.cat("/segredo", self.chave), claro.decode())
        self.assertIn("DECRYPT_FALHA", [e["evento"] for e in self.fs.sec.auditoria])
        self.assertNotIn(self.chave, repr(self.fs.__dict__))
        self.assertNotIn(self.chave, repr(self.fs.sec.auditoria))
        shell(self.fs, "decrypt_file /segredo --key " + self.chave)
        self.assertEqual(self.fs._ler_conteudo(self.arquivo), claro)
        self.assertIsNone(self.arquivo.cripto)

    def test_chave_mascarada_e_create_content_shell(self):
        self.assertNotIn(self.chave, mascarar("encrypt_file /segredo --key " + self.chave))
        shell(self.fs, 'create /novo --content "texto do shell"')
        self.assertEqual(self.fs.cat("/novo"), "texto do shell")

    def test_update_recusa_arquivo_criptografado(self):
        self.fs.encrypt_file("/segredo", self.chave)
        with self.assertRaises(FSError):
            self.fs.update("/segredo", 4)


if __name__ == "__main__":
    unittest.main()
