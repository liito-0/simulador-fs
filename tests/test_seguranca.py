import contextlib, io, os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from disk import Disk
from fs import FileSystem, FSError
from main import executar
from seguranca import (Seguranca, SecurityError, AuthError, PrivilegeError, gerar_hash,
                       verificar_hash, MODO_USUARIO, MODO_KERNEL)


def sistema():
    """Como o shell: sem sessão, exige login. (Poucas iterações só para acelerar os testes.)"""
    sec = Seguranca(iteracoes=1000)
    return FileSystem(Disk(16, 4096), "indexada", seguranca=sec), sec


def sh(fs, linha):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        executar(fs, linha)
    return buf.getvalue()


def com_usuarios():
    fs, sec = sistema()
    sec.login("root", "root")
    sec.groupadd("devs")
    sec.useradd("carlos", "carlos123", "devs")
    sec.useradd("ana", "ana123", "admin")
    sec.logout()
    return fs, sec


class TestHash(unittest.TestCase):
    def test_salt_diferente_gera_hash_diferente(self):
        a, b = gerar_hash("mesma", iteracoes=1000), gerar_hash("mesma", iteracoes=1000)
        self.assertNotEqual(a["salt"], b["salt"])
        self.assertNotEqual(a["hash"], b["hash"])

    def test_verificacao(self):
        r = gerar_hash("segredo", iteracoes=1000)
        self.assertTrue(verificar_hash("segredo", r))
        self.assertFalse(verificar_hash("Segredo", r))

    def test_senha_nao_fica_em_texto(self):
        fs, sec = com_usuarios()
        for u in sec.usuarios.values():
            self.assertNotIn("carlos123", repr(u.senha))
            self.assertNotIn("carlos123", repr(u))
        sec.login("root", "root")
        self.assertNotIn("carlos123", "".join(sec.shadow()))


class TestIdentidade(unittest.TestCase):
    def test_login_logout(self):
        fs, sec = com_usuarios()
        u = sec.login("carlos", "carlos123")
        self.assertEqual((u.grupo, sec.modo), ("devs", MODO_USUARIO))
        sec.logout()
        self.assertIsNone(sec.modo)

    def test_login_invalido_e_auditado(self):
        fs, sec = com_usuarios()
        with self.assertRaises(AuthError):
            sec.login("carlos", "errada")
        with self.assertRaises(AuthError):   # mesma mensagem para usuário inexistente
            sec.login("fantasma", "qualquer")
        self.assertEqual([e["evento"] for e in sec.auditoria[-2:]], ["LOGIN_FALHA"] * 2)

    def test_root_em_modo_kernel(self):
        fs, sec = sistema()
        sec.login("root", "root")
        self.assertEqual(sec.modo, MODO_KERNEL)

    def test_nao_loga_duas_vezes(self):
        fs, sec = com_usuarios()
        sec.login("ana", "ana123")
        with self.assertRaises(AuthError):
            sec.login("carlos", "carlos123")

    def test_usuarios_e_grupos(self):
        fs, sec = com_usuarios()
        sec.login("root", "root")
        sec.usermod("carlos", adicionar="admin")
        self.assertIn("admin", sec.usuarios["carlos"].grupos)
        with self.assertRaises(SecurityError):
            sec.useradd("carlos", "outra123")        # duplicado
        with self.assertRaises(SecurityError):
            sec.useradd("x", "123")                  # senha curta
        with self.assertRaises(SecurityError):
            sec.useradd("Inválido!", "senha123")
        with self.assertRaises(SecurityError):
            sec.groupdel("devs")                     # primário de carlos
        with self.assertRaises(SecurityError):
            sec.userdel("root")
        sec.userdel("carlos")
        sec.groupdel("devs")
        self.assertNotIn("devs", sec.grupos)

    def test_passwd(self):
        fs, sec = com_usuarios()
        sec.login("carlos", "carlos123")
        with self.assertRaises(AuthError):
            sec.passwd("carlos", "nova1234", "errada")
        sec.passwd("carlos", "nova1234", "carlos123")
        with self.assertRaises(PrivilegeError):      # senha de outro exige kernel
            sec.passwd("ana", "hack1234")
        sec.logout()
        sec.login("carlos", "nova1234")


class TestPrivilegios(unittest.TestCase):
    def test_usuario_comum_nao_executa_operacoes_criticas(self):
        fs, sec = com_usuarios()
        sec.login("carlos", "carlos123")
        for op in (lambda: sec.useradd("x", "senha123"), lambda: sec.groupadd("g"),
                   lambda: sec.shadow(), lambda: sec.linhas_auditoria()):
            with self.assertRaises(PrivilegeError):
                op()
        self.assertIn("NEGADO", [e["evento"] for e in sec.auditoria])

    def test_compactar_exige_kernel_na_api(self):
        from diagnostico import compactar
        fs, sec = com_usuarios()
        sec.login("carlos", "carlos123")
        with self.assertRaises(PrivilegeError):
            compactar(fs)

    def test_sudo(self):
        fs, sec = com_usuarios()
        sec.login("ana", "ana123")
        with sec.sudo("ana123"):
            self.assertEqual(sec.modo, MODO_KERNEL)
            sec.groupadd("novo")
        self.assertEqual(sec.modo, MODO_USUARIO)
        with self.assertRaises(AuthError):
            with sec.sudo("errada"):
                pass
        sec.logout()
        sec.login("carlos", "carlos123")             # fora do grupo admin
        with self.assertRaises(PrivilegeError):
            with sec.sudo("carlos123"):
                pass

    def test_sem_login_nada_funciona(self):
        fs, sec = sistema()
        for chamada in (lambda: fs.mkdir("/a"), lambda: fs.create("/a", 10), lambda: fs.ls("/"),
                        lambda: fs.tree()):
            with self.assertRaises(AuthError):
                chamada()


class TestIntegracaoFS(unittest.TestCase):
    def test_dono_e_grupo_dos_arquivos(self):
        fs, sec = com_usuarios()
        sec.login("root", "root")
        fs.mkdir("/pasta")
        fs.chown("/pasta", "carlos", "devs")
        fs.chmod("/pasta", 0o755)
        sec.logout()
        sec.login("carlos", "carlos123")
        f = fs.create("/pasta/a.txt", 100)
        self.assertEqual((fs.resolve("/pasta").owner, f.owner, f.group), ("carlos", "carlos", "devs"))
        self.assertIn("Dono    : carlos (Grupo: devs)", fs.read("/pasta/a.txt"))
        self.assertEqual((fs.root.owner, fs.root.group), ("root", "admin"))

    def test_api_programatica_continua_root(self):
        fs = FileSystem(Disk(16, 4096))
        self.assertEqual(fs.sec.modo, MODO_KERNEL)
        self.assertEqual(fs.create("/x", 10).owner, "root")

    def test_shell_fluxo_completo(self):
        fs, sec = sistema()
        with self.assertRaises(AuthError):
            sh(fs, "ls /")
        out = sh(fs, "login --user root --password root")
        self.assertIn("Modo: MODO_KERNEL", out)
        sh(fs, "groupadd devs")
        sh(fs, "useradd carlos --group devs --password carlos123")
        sh(fs, "logout")
        out = sh(fs, "login --user carlos --password carlos123")
        self.assertIn("Usuário: 'carlos' | Grupo: 'devs' | Modo: MODO_USUARIO", out)
        with self.assertRaises(PrivilegeError) as cm:
            sh(fs, "compact")
        self.assertIn("[NEGADO]", str(cm.exception))
        self.assertIn("registrada nos logs", str(cm.exception))
        for cmd in ("alloc contigua", "io_clear", "ssd_status", "raid_status", "shadow"):
            with self.assertRaises(PrivilegeError):
                sh(fs, cmd)
        self.assertIn("MODO_USUARIO", sh(fs, "whoami"))
        sh(fs, "logout")
        sh(fs, "login --user root --password root")
        self.assertIn("NEGADO", sh(fs, "audit_log"))

    def test_senha_exigida_em_modo_script(self):
        fs, sec = sistema()
        with self.assertRaises(SecurityError):
            sh(fs, "login --user root")


if __name__ == "__main__":
    unittest.main()
