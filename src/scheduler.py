"""Algoritmos de escalonamento do braço de um HDD."""


def _validate(tracks, head, max_track, direcao):
    if max_track < 0:
        raise ValueError("max_track deve ser maior ou igual a zero.")
    if not 0 <= head <= max_track:
        raise ValueError("A cabeça está fora dos limites do disco.")
    if direcao not in ("up", "down"):
        raise ValueError("A direção deve ser 'up' ou 'down'.")
    if any(not isinstance(track, int) or not 0 <= track <= max_track for track in tracks):
        raise ValueError("Há trilhas fora dos limites do disco.")


def _result(order, path, head):
    positions = [head] + path
    movements = [abs(b - a) for a, b in zip(positions, positions[1:])]
    return order, path, sum(movements)


def fcfs(trilhas, head, max_track, direcao="up"):
    """Atende na ordem de chegada; movimentos contém posições visitadas."""
    _validate(trilhas, head, max_track, direcao)
    return _result(list(trilhas), list(trilhas), head)


def sstf(trilhas, head, max_track, direcao="up"):
    """Atende a requisição mais próxima, desempata pela menor trilha."""
    _validate(trilhas, head, max_track, direcao)
    pending, order, path, current = list(trilhas), [], [], head
    while pending:
        track = min(pending, key=lambda item: (abs(item - current), item))
        pending.remove(track)
        order.append(track)
        path.append(track)
        current = track
    return _result(order, path, head)


def scan(trilhas, head, max_track, direcao="up"):
    """SCAN viaja até a extremidade antes de inverter a direção."""
    _validate(trilhas, head, max_track, direcao)
    if not trilhas:
        return [], [], 0
    at_head = [track for track in trilhas if track == head]
    if direcao == "up":
        first = sorted(track for track in trilhas if track > head)
        second = sorted((track for track in trilhas if track < head), reverse=True)
        edge = max_track
    else:
        first = sorted((track for track in trilhas if track < head), reverse=True)
        second = sorted(track for track in trilhas if track > head)
        edge = 0
    order = at_head + first + second
    path = at_head + first
    if path[-1:] != [edge]:
        path.append(edge)
    path.extend(second)
    return _result(order, path, head)


def cscan(trilhas, head, max_track, direcao="up"):
    """C-SCAN atende em uma direção e retorna à extremidade oposta.

    O deslocamento do salto entre as extremidades é incluído no total.
    """
    _validate(trilhas, head, max_track, direcao)
    if not trilhas:
        return [], [], 0
    at_head = [track for track in trilhas if track == head]
    if direcao == "up":
        first = sorted(track for track in trilhas if track > head)
        second = sorted(track for track in trilhas if track < head)
        edge, opposite = max_track, 0
    else:
        first = sorted((track for track in trilhas if track < head), reverse=True)
        second = sorted((track for track in trilhas if track > head), reverse=True)
        edge, opposite = 0, max_track
    order = at_head + first + second
    path = at_head + first
    if path[-1:] != [edge]:
        path.append(edge)
    # O salto entre extremidades também representa deslocamento do braço.
    path.append(opposite)
    path.extend(second)
    return _result(order, path, head)


_NAMES = {
    "fcfs": "FCFS (First Come First Served)",
    "sstf": "SSTF (Shortest Seek Time First)",
    "scan": "SCAN (Elevator)",
    "cscan": "C-SCAN (Circular SCAN)",
}


def formatar(nome, head, ordem, movimentos, total):
    """Imprime a sequência, os trechos percorridos e o deslocamento total."""
    canonical = nome.lower().replace("-", "")
    titulo = _NAMES.get(canonical, nome)
    points = [head] + list(movimentos)
    distances = [abs(b - a) for a, b in zip(points, points[1:])]
    expressao = " + ".join(f"|{a}-{b}|" for a, b in zip(points, points[1:]))
    if not expressao:
        expressao = "0"
    soma = " + ".join(str(distance) for distance in distances) or "0"
    atendimento = (" -> ".join(str(track) for track in [head] + list(ordem))
                   if ordem else "(nenhuma)")
    print(f"--- ESCALONAMENTO DE DISCO: {titulo} ---")
    print(f"Ordem de Atendimento : {atendimento}")
    print(f"Deslocamento da Cabeça: {expressao}")
    print(f"Total de Movimento   : {soma} = {total} trilhas")
