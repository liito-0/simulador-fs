import contextlib
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from acl import AclError
from disk import Disk
from fs import FileSystem
from main import executar
from seguranca import PrivilegeError, Seguranca


def shell(fs, linha):
    saida = io.StringIO()
    with contextlib.redirect_stdout(saida):
        executar(fs, linha)
    return saida.getvalue()


class TestACL(unittest.TestCase):
    def setUp(self):
        self.sec = Seguranca(iteracoes=1000)
        self.fs = FileSystem(Disk(32, 32), seguranca=self.sec)
        self.sec.login("root", "root")
        self.sec.groupadd("staff")
        self.sec.useradd("dono", "dono123", "staff")
        self.sec.useradd("colega", "colega123", "staff")
        self.sec.useradd("externo", "externo123")
        self.fs.mkdir("/dados")
        self.arquivo = self.fs.create("/dados/privado", content="conteudo")
        self.fs.chown("/dados/privado", "dono", "staff")
        self.fs.chmod("/dados/privado", 0o640)
        self.sec.logout()

    def test_dono_grupo_outros_e_root(self):
        for nome, senha in (("dono", "dono123"), ("colega", "colega123"), ("root", "root")):
            self.sec.login(nome, senha)
            self.assertIn("Dono    : dono (Grupo: staff)", self.fs.read("/dados/privado"))
            self.sec.logout()
        self.sec.login("externo", "externo123")
        with self.assertRaises(AclError):
            self.fs.read("/dados/privado")

    def test_negacao_acl_nao_muda_arvore_fila_ou_disco_e_audita(self):
        self.sec.login("externo", "externo123")
        antes = (self.fs.tree(), list(self.fs.io_queue), list(self.fs.disk.blocks))
        with self.assertRaises(AclError):
            self.fs.create("/dados/novo", content="x")
        with self.assertRaises(AclError):
            self.fs.read("/dados/privado")
        self.assertEqual((self.fs.tree(), self.fs.io_queue, self.fs.disk.blocks), antes)
        self.assertIn("ACL_NEGADO", [evento["evento"] for evento in self.sec.auditoria])

    def test_chmod_chown_por_shell_com_e_sem_privilegio(self):
        self.sec.login("dono", "dono123")
        shell(self.fs, "chmod 600 /dados/privado")
        with self.assertRaises(PrivilegeError):
            shell(self.fs, "chown externo /dados/privado")
        self.sec.logout()
        self.sec.login("root", "root")
        shell(self.fs, "chown externo /dados/privado")
        self.assertEqual(self.arquivo.owner, "externo")
        self.assertTrue(any(x["evento"] == "CHMOD" for x in self.sec.auditoria))
        self.assertTrue(any(x["evento"] == "CHOWN" for x in self.sec.auditoria))

    def test_shell_ls_l_acl_e_relatorio_de_leitura(self):
        self.sec.login("root", "root")
        saida = shell(self.fs, "ls -l /dados")
        self.assertIn("-rw-r----- dono:staff", saida)
        self.assertIn("-rw-r----- dono:staff", shell(self.fs, "ls -l /dados/privado"))
        self.assertIn("Proprietário", shell(self.fs, "acl /dados/privado"))
        saida = shell(self.fs, "read /dados/privado")
        self.assertIn("[PERMITIDO]", saida)
        self.assertIn("[PERMITIDO]", shell(self.fs, "read_file /dados/privado"))


if __name__ == "__main__":
    unittest.main()
