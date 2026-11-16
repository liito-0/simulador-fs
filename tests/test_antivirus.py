import contextlib
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from antivirus import ASSINATURAS, varrer
from diagnostico import compactar
from disk import Disk
from fs import FileSystem
from main import executar
from seguranca import PrivilegeError, Seguranca


def shell(fs, linha):
    saida = io.StringIO()
    with contextlib.redirect_stdout(saida):
        executar(fs, linha)
    return saida.getvalue()


class TestAntivirus(unittest.TestCase):
    def setUp(self):
        sec = Seguranca(iteracoes=1000)
        self.fs = FileSystem(Disk(24, 16), "contigua", seguranca=sec)
        sec.login("root", "root")

    def test_integridade_adulteracao_assinatura_e_shell(self):
        self.fs.create("/limpo", content="arquivo limpo")
        self.fs.create("/assinatura", content="antes" + ASSINATURAS["SIM-MALWARE-01"].decode())
        antes = "\n".join(varrer(self.fs))
        self.assertIn("[OK - Íntegro]", antes)
        self.assertIn("SIM-MALWARE-01", antes)
        shell(self.fs, "disk_tamper /limpo --data adulterado")
        resultado = shell(self.fs, "antivirus_scan /")
        self.assertIn("Hash do bloco difere", resultado)
        self.assertIn("Possível modificação direta", resultado)
        self.assertIn("AV_SCAN", [e["evento"] for e in self.fs.sec.auditoria])
        self.assertIn("AV_ALERTA", [e["evento"] for e in self.fs.sec.auditoria])

    def test_scan_negado_a_usuario_comum(self):
        self.fs.sec.useradd("ana", "ana123")
        self.fs.sec.logout()
        self.fs.sec.login("ana", "ana123")
        with self.assertRaises(PrivilegeError):
            shell(self.fs, "antivirus_scan /")

    def test_compact_preserva_bytes_e_registros_de_integridade(self):
        a = self.fs.create("/a", content="primeiro arquivo")
        self.fs.create("/gap", content="remover")
        b = self.fs.create("/b", content="segundo arquivo")
        antes = {f.name: self.fs._ler_conteudo(f) for f in (a, b)}
        hashes = {f.name: [self.fs.integridade[bloco] for bloco in f.alloc["data"]]
                  for f in (a, b)}
        self.fs.remove("/gap")
        compactar(self.fs)
        self.assertEqual({f.name: self.fs._ler_conteudo(f) for f in (a, b)}, antes)
        for f in (a, b):
            self.assertEqual(
                [self.fs.integridade[bloco] for bloco in f.alloc["data"]], hashes[f.name]
            )
        self.assertIn("[OK - Íntegro]", "\n".join(varrer(self.fs)))


if __name__ == "__main__":
    unittest.main()
