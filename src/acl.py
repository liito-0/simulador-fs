"""Controle didático de permissões POSIX rwx."""
from seguranca import MODO_KERNEL, SecurityError


class AclError(SecurityError):
    """Ação negada pelas permissões do objeto."""


ACOES = {
    "r": ("LEITURA", "leitura", 4),
    "w": ("ESCRITA", "escrita", 2),
    "x": ("EXECUÇÃO", "execução", 1),
}


def perm_str(mode):
    return "".join(letra if bits & bit else "-"
                   for bits in (mode >> 6, mode >> 3, mode)
                   for letra, bit in (("r", 4), ("w", 2), ("x", 1)))


def _caminho(node):
    partes = []
    while node.parent is not None:
        partes.append(node.name)
        node = node.parent
    return "/" + "/".join(reversed(partes))


def _permissoes(sec, node):
    usuario = sec.efetivo
    if usuario.nome == node.owner:
        return (node.mode >> 6) & 7
    if node.group in ({usuario.grupo} | set(usuario.grupos)):
        return (node.mode >> 3) & 7
    return node.mode & 7


def checar(sec, node, acao):
    if acao not in ACOES:
        raise ValueError("Ação ACL inválida.")
    if sec.modo == MODO_KERNEL:
        return
    _, descricao, bit = ACOES[acao]
    if _permissoes(sec, node) & bit:
        return

    nome_acao = ACOES[acao][0]
    caminho = _caminho(node)
    usuario = sec.efetivo
    mensagem = (
        "[SISTEMA DE SEGURANÇA - VERIFICAÇÃO DE ACL]\n"
        f"Objeto      : {caminho}\n"
        f"Proprietário: {node.owner} (Grupo: {node.group})\n"
        f"Permissões  : {perm_str(node.mode)} ({node.mode:03o})\n"
        f"Ação Pedida : {nome_acao} por '{usuario.nome}' (Grupo: {usuario.grupo})\n\n"
        f"[NEGADO]: O usuário '{usuario.nome}' não possui permissão de {descricao} "
        f"no objeto '{caminho}'.\n"
        "Tentativa não autorizada registrada nos logs do sistema."
    )
    sec.auditar("ACL_NEGADO", f"{nome_acao} em '{caminho}'")
    raise AclError(mensagem)


def relatorio(sec, node, acao):
    nome_acao, descricao, _ = ACOES[acao]
    usuario = sec.efetivo
    caminho = _caminho(node)
    return (
        "[SISTEMA DE SEGURANÇA - VERIFICAÇÃO DE ACL]\n"
        f"Objeto      : {caminho}\n"
        f"Proprietário: {node.owner} (Grupo: {node.group})\n"
        f"Permissões  : {perm_str(node.mode)} ({node.mode:03o})\n"
        f"Ação Pedida : {nome_acao} por '{usuario.nome}' (Grupo: {usuario.grupo})\n\n"
        f"[PERMITIDO]: O usuário '{usuario.nome}' pode {descricao} "
        f"o objeto '{caminho}'."
    )


def matriz(node):
    return [
        f"Dono    : {node.owner}",
        f"Grupo   : {node.group}",
        f"Modo    : {perm_str(node.mode)} ({node.mode:03o})",
        "          r w x",
        f"Proprietário: {' '.join('rwx'[i] if (node.mode >> 6) & (4 >> i) else '-' for i in range(3))}",
        f"Grupo       : {' '.join('rwx'[i] if (node.mode >> 3) & (4 >> i) else '-' for i in range(3))}",
        f"Outros      : {' '.join('rwx'[i] if node.mode & (4 >> i) else '-' for i in range(3))}",
    ]
