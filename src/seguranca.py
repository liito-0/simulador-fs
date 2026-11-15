"""Segurança (Etapa 3): identidade, autenticação, modos de execução e auditoria.

- Usuários e grupos (primário + suplementares).
- Senhas nunca são guardadas em texto: PBKDF2-HMAC-SHA256 com salt aleatório por usuário.
- Dois modos de execução: MODO_USUARIO e MODO_KERNEL (superusuário/root, uid 0).
- Operações críticas chamam `exigir_kernel`; tentativas negadas vão para o log de auditoria.
"""
import hashlib
import hmac
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime

MODO_USUARIO = "MODO_USUARIO"
MODO_KERNEL = "MODO_KERNEL"

ALGORITMO = "pbkdf2_sha256"
ITERACOES_PADRAO = 100_000
TAM_SALT = 16
SENHA_MIN = 4
GRUPO_ADMIN = "admin"
_NOME_VALIDO = re.compile(r"[a-z_][a-z0-9_-]{0,31}")


class SecurityError(Exception):
    pass


class AuthError(SecurityError):
    """Falha de autenticação ou ausência de sessão."""


class PrivilegeError(SecurityError):
    """Operação exige MODO_KERNEL."""


# ---------- hashing de senhas ----------
def gerar_hash(senha, salt=None, iteracoes=ITERACOES_PADRAO):
    """Devolve dict {algoritmo, iteracoes, salt, hash} (salt/hash em hexadecimal)."""
    salt = os.urandom(TAM_SALT) if salt is None else salt
    digest = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), salt, iteracoes)
    return {"algoritmo": ALGORITMO, "iteracoes": iteracoes,
            "salt": salt.hex(), "hash": digest.hex()}


def verificar_hash(senha, registro):
    """Compara em tempo constante o hash da senha informada com o registro guardado."""
    calculado = gerar_hash(senha, bytes.fromhex(registro["salt"]), registro["iteracoes"])
    return hmac.compare_digest(calculado["hash"], registro["hash"])


@dataclass
class Usuario:
    nome: str
    uid: int
    grupo: str                       # grupo primário
    senha: dict = field(repr=False)  # registro de hash (nunca a senha)
    grupos: set = field(default_factory=set)  # grupos suplementares


@dataclass
class Grupo:
    nome: str
    gid: int


class Seguranca:
    def __init__(self, senha_root="root", iteracoes=ITERACOES_PADRAO, autologin_root=False):
        """`autologin_root=True` inicia já em MODO_KERNEL (uso programático/testes);
        o shell cria com False e exige `login`."""
        self.iteracoes = iteracoes
        self.usuarios, self.grupos = {}, {}
        self.auditoria = []
        self._real = None       # usuário que fez login
        self._efetivo = None    # usuário cujos privilégios valem (root durante sudo)
        self._dummy = gerar_hash("dummy", iteracoes=iteracoes)  # evita revelar se o usuário existe
        self.grupos[GRUPO_ADMIN] = Grupo(GRUPO_ADMIN, 0)
        self.usuarios["root"] = Usuario("root", 0, GRUPO_ADMIN,
                                        self._novo_hash(senha_root), {GRUPO_ADMIN})
        if autologin_root:
            self._real = self._efetivo = self.usuarios["root"]

    # ---------- auditoria ----------
    def auditar(self, evento, detalhe="", usuario=None):
        quem = usuario or (self._real.nome if self._real else "-")
        self.auditoria.append({"seq": len(self.auditoria) + 1,
                               "quando": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                               "usuario": quem, "evento": evento, "detalhe": detalhe})

    # ---------- estado da sessão ----------
    @property
    def autenticado(self):
        return self._real is not None

    @property
    def usuario(self):
        """Usuário que fez login (identidade real)."""
        return self._real

    @property
    def efetivo(self):
        """Usuário cujos privilégios estão valendo (root dentro de sudo)."""
        return self._efetivo

    @property
    def modo(self):
        if not self.autenticado:
            return None
        return MODO_KERNEL if self._efetivo.uid == 0 else MODO_USUARIO

    def exigir_login(self):
        if not self.autenticado:
            raise AuthError("Autenticação necessária: use 'login --user <nome>'.")

    def exigir_kernel(self, operacao):
        """Portão de privilégio: só o superusuário (MODO_KERNEL) passa."""
        self.exigir_login()
        if self.modo == MODO_KERNEL:
            return
        u = self._real
        self.auditar("NEGADO", f"operação '{operacao}' exige MODO_KERNEL")
        raise PrivilegeError(
            "[SISTEMA DE SEGURANÇA - VERIFICAÇÃO DE PRIVILÉGIO]\n"
            f"Operação    : {operacao}\n"
            "Exige       : MODO_KERNEL (superusuário root)\n"
            f"Solicitante : '{u.nome}' (Grupo: {u.grupo}) | Modo atual: {self.modo}\n\n"
            f"[NEGADO]: A operação '{operacao}' é crítica e exige privilégios elevados.\n"
            "Tentativa não autorizada registrada nos logs do sistema.")

    # ---------- autenticação ----------
    def _novo_hash(self, senha):
        if len(senha) < SENHA_MIN:
            raise SecurityError(f"A senha deve ter ao menos {SENHA_MIN} caracteres.")
        return gerar_hash(senha, iteracoes=self.iteracoes)

    def _verificar(self, nome, senha):
        u = self.usuarios.get(nome)
        ok = verificar_hash(senha, (u.senha if u else self._dummy))
        return u if (u and ok) else None

    def login(self, nome, senha):
        if self.autenticado:
            raise AuthError(f"Já autenticado como '{self._real.nome}'. Use 'logout' antes.")
        u = self._verificar(nome, senha)
        if u is None:
            self.auditar("LOGIN_FALHA", f"usuário '{nome}'", usuario=nome)
            raise AuthError("Falha de autenticação: usuário ou senha inválidos.")
        self._real = self._efetivo = u
        self.auditar("LOGIN_OK", f"modo {self.modo}")
        return u

    def logout(self):
        self.exigir_login()
        self.auditar("LOGOUT")
        self._real = self._efetivo = None

    @contextmanager
    def sudo(self, senha):
        """Eleva temporariamente para root. Exige ser do grupo 'admin' e reconfirmar a senha."""
        self.exigir_login()
        u = self._real
        if GRUPO_ADMIN not in u.grupos and u.grupo != GRUPO_ADMIN:
            self.auditar("SUDO_NEGADO", f"'{u.nome}' não pertence ao grupo '{GRUPO_ADMIN}'")
            raise PrivilegeError(f"[NEGADO]: '{u.nome}' não pertence ao grupo '{GRUPO_ADMIN}' "
                                 "e não pode elevar privilégios.\n"
                                 "Tentativa não autorizada registrada nos logs do sistema.")
        if self._verificar(u.nome, senha) is None:
            self.auditar("SUDO_FALHA", "senha incorreta")
            raise AuthError("Falha de autenticação: senha incorreta.")
        anterior = self._efetivo
        self._efetivo = self.usuarios["root"]
        self.auditar("SUDO_OK", "elevação para MODO_KERNEL")
        try:
            yield
        finally:
            self._efetivo = anterior

    # ---------- usuários e grupos (operações críticas) ----------
    @staticmethod
    def _validar_nome(nome, tipo):
        if not _NOME_VALIDO.fullmatch(nome or ""):
            raise SecurityError(f"Nome de {tipo} inválido: '{nome}' "
                                "(use minúsculas, dígitos, '_' ou '-', começando por letra).")

    def _grupo(self, nome):
        if nome not in self.grupos:
            raise SecurityError(f"Grupo '{nome}' não existe.")
        return self.grupos[nome]

    def _usuario(self, nome):
        if nome not in self.usuarios:
            raise SecurityError(f"Usuário '{nome}' não existe.")
        return self.usuarios[nome]

    def groupadd(self, nome):
        self.exigir_kernel("groupadd")
        self._validar_nome(nome, "grupo")
        if nome in self.grupos:
            raise SecurityError(f"Grupo '{nome}' já existe.")
        gid = max(g.gid for g in self.grupos.values()) + 1
        self.grupos[nome] = Grupo(nome, gid)
        self.auditar("GROUPADD", nome)
        return self.grupos[nome]

    def groupdel(self, nome):
        self.exigir_kernel("groupdel")
        self._grupo(nome)
        if nome == GRUPO_ADMIN:
            raise SecurityError(f"O grupo '{GRUPO_ADMIN}' não pode ser removido.")
        if any(u.grupo == nome for u in self.usuarios.values()):
            raise SecurityError(f"Grupo '{nome}' é o grupo primário de algum usuário.")
        del self.grupos[nome]
        for u in self.usuarios.values():
            u.grupos.discard(nome)
        self.auditar("GROUPDEL", nome)

    def useradd(self, nome, senha, grupo=None):
        """Cria usuário. Sem `grupo`, cria um grupo primário com o mesmo nome."""
        self.exigir_kernel("useradd")
        self._validar_nome(nome, "usuário")
        if nome in self.usuarios:
            raise SecurityError(f"Usuário '{nome}' já existe.")
        hash_ = self._novo_hash(senha)  # valida a senha antes de criar qualquer coisa
        if grupo is None:
            grupo = nome
            if grupo not in self.grupos:
                self.groupadd(grupo)
        else:
            self._grupo(grupo)
        uid = max(u.uid for u in self.usuarios.values()) + 1
        self.usuarios[nome] = Usuario(nome, uid, grupo, hash_, {grupo})
        self.auditar("USERADD", f"{nome} (uid {uid}, grupo {grupo})")
        return self.usuarios[nome]

    def userdel(self, nome):
        self.exigir_kernel("userdel")
        u = self._usuario(nome)
        if u.uid == 0:
            raise SecurityError("O superusuário 'root' não pode ser removido.")
        if self._real is u:
            raise SecurityError("Não é possível remover o usuário da sessão atual.")
        del self.usuarios[nome]
        self.auditar("USERDEL", nome)

    def usermod(self, nome, adicionar=None, remover=None, primario=None):
        self.exigir_kernel("usermod")
        u = self._usuario(nome)
        if adicionar:
            self._grupo(adicionar)
            u.grupos.add(adicionar)
        if remover:
            self._grupo(remover)
            if remover == u.grupo:
                raise SecurityError(f"'{remover}' é o grupo primário de '{nome}'.")
            if u.uid == 0 and remover == GRUPO_ADMIN:
                raise SecurityError("'root' deve permanecer no grupo 'admin'.")
            u.grupos.discard(remover)
        if primario:
            self._grupo(primario)
            u.grupo = primario
            u.grupos.add(primario)
        self.auditar("USERMOD", nome)

    def passwd(self, nome, nova, antiga=None):
        """Troca de senha. Alterar a de outro usuário exige MODO_KERNEL;
        a própria exige a senha atual."""
        self.exigir_login()
        alvo = self._usuario(nome)
        if alvo is not self._real:
            self.exigir_kernel("passwd (outro usuário)")
        elif self._verificar(alvo.nome, antiga or "") is None:
            self.auditar("PASSWD_FALHA", f"senha atual incorreta para '{nome}'")
            raise AuthError("Falha de autenticação: senha atual incorreta.")
        alvo.senha = self._novo_hash(nova)
        self.auditar("PASSWD", nome)

    # ---------- consultas ----------
    def descrever(self, u=None):
        u = u or self._real
        extras = sorted(u.grupos - {u.grupo})
        return (f"Usuário: '{u.nome}' (uid {u.uid}) | Grupo: '{u.grupo}'"
                + (f" | Outros grupos: {', '.join(extras)}" if extras else "")
                + f" | Modo: {self.modo}")

    def listar_usuarios(self):
        return [f"{u.nome:<12} uid={u.uid:<4} grupo={u.grupo:<10} grupos={sorted(u.grupos)}"
                for u in sorted(self.usuarios.values(), key=lambda x: x.uid)]

    def listar_grupos(self):
        return [f"{g.nome:<12} gid={g.gid:<4} membros="
                f"{sorted(u.nome for u in self.usuarios.values() if g.nome in u.grupos)}"
                for g in sorted(self.grupos.values(), key=lambda x: x.gid)]

    def shadow(self):
        """Visão do armazenamento de senhas (só salt e hash truncado; exige MODO_KERNEL)."""
        self.exigir_kernel("shadow")
        return [f"{u.nome}:${u.senha['algoritmo']}${u.senha['iteracoes']}$"
                f"{u.senha['salt']}${u.senha['hash'][:24]}..." for u in self.usuarios.values()]

    def linhas_auditoria(self):
        self.exigir_kernel("audit_log")
        return [f"#{e['seq']:03d} {e['quando']} | {e['usuario']:<10} | {e['evento']:<12} | {e['detalhe']}"
                for e in self.auditoria]
