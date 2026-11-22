"""Memória virtual paginada da região dinâmica da RAM (Etapa 4, parte B)."""

from collections import deque

from mem_reservada import MemoriaError

POLITICAS = ("lru", "second_chance", "fifo")
NOMES_POLITICA = {
    "lru": "LRU (Least Recently Used)",
    "second_chance": "Segunda Chance (Clock)",
    "fifo": "FIFO",
}
MS_POR_ACESSO = 5
LEITURA = {"LOAD_DATA", "LOAD", "READ", "READ_DATA", "FETCH"}
ESCRITA = {"STORE_DATA", "STORE", "WRITE", "WRITE_DATA"}
LIMITE_LISTAGEM = 8        # páginas listadas individualmente ao criar processo
LIMITE_MOLDURAS = 32       # molduras listadas em memory_status --virtual


class Pagina:
    """Entrada da tabela de páginas."""
    __slots__ = ("frame", "slot", "ref", "sujo", "ultimo_acesso", "carregada_em")

    def __init__(self):
        self.frame = None          # moldura física (None = ausente da RAM)
        self.slot = None           # posição no swap (None = sem cópia no swap)
        self.ref = False           # bit de referência (Segunda Chance)
        self.sujo = False          # bit de modificação (dirty)
        self.ultimo_acesso = 0     # ms simulados
        self.carregada_em = 0


def _kb(valor):
    kb = valor / 1024
    return str(int(kb)) if float(kb).is_integer() else f"{kb:.3f}".rstrip("0").rstrip(".")


def _intervalo_paginas(n):
    if n == 1:
        return "Página 0"
    if n == 2:
        return "Páginas 0 e 1"
    if n <= LIMITE_LISTAGEM:
        return "Páginas " + ", ".join(str(i) for i in range(n - 1)) + f" e {n - 1}"
    return f"Páginas 0 a {n - 1}"


class MemoriaVirtual:
    def __init__(self, tamanho_dinamico, tamanho_pagina, sec=None, tamanho_swap=None):
        if not isinstance(tamanho_pagina, int) or tamanho_pagina <= 0:
            raise MemoriaError("O tamanho da página deve ser um inteiro positivo em bytes.")
        if not isinstance(tamanho_dinamico, int) or tamanho_dinamico < tamanho_pagina:
            raise MemoriaError("A região dinâmica deve comportar ao menos uma moldura.")
        if tamanho_swap is None:
            tamanho_swap = 4 * tamanho_dinamico
        if not isinstance(tamanho_swap, int) or tamanho_swap < tamanho_pagina:
            raise MemoriaError("O swap deve comportar ao menos uma página.")
        self.tamanho_dinamico = tamanho_dinamico
        self.tamanho_pagina = tamanho_pagina
        self.sec = sec
        self.base_fisica = 0                         # preenchido pelo gerenciador
        self.total_molduras = tamanho_dinamico // tamanho_pagina
        self.swap_paginas = tamanho_swap // tamanho_pagina
        self.politica = "lru"
        self.molduras = [None] * self.total_molduras  # (pid, pagina) ou None
        self.fila = deque()                          # ordem de carga (FIFO / Clock)
        self.tabelas = {}                            # pid -> list[Pagina]
        self.processos = {}                          # pid -> Processo
        self.slots_livres = list(range(self.swap_paginas - 1, -1, -1))
        self.relogio = 0
        self.acessos = self.hits = self.faults = 0
        self.swap_in = self.swap_out = self.descartes = 0
        self.faults_por_pid = {}

    # utilidades
    def _auditar(self, evento, detalhe):
        if self.sec is not None:
            self.sec.auditar(evento, detalhe)

    def definir_politica(self, nome):
        nome = str(nome).lower().replace("-", "_")
        if nome in ("segunda_chance", "clock"):
            nome = "second_chance"
        if nome not in POLITICAS:
            raise MemoriaError(
                "Política inválida: use " + ", ".join(POLITICAS) + "."
            )
        self.politica = nome
        self._auditar("MEM_POLITICA", nome)
        return [f"Algoritmo de substituição de páginas: {NOMES_POLITICA[nome]}."]

    @property
    def molduras_livres(self):
        return sum(1 for m in self.molduras if m is None)

    @property
    def molduras_usadas(self):
        return self.total_molduras - self.molduras_livres

    @property
    def paginas_alocadas(self):
        return sum(len(t) for t in self.tabelas.values())

    def _proc(self, proc):
        if proc.pid not in self.tabelas:
            raise MemoriaError(f"Processo '{proc.nome}' não possui tabela de páginas.")
        return self.tabelas[proc.pid]

    @staticmethod
    def _paginas_de(proc, tamanho_pagina):
        return -(-proc.tamanho // tamanho_pagina)

    def _bytes_uteis(self, proc, indice):
        restante = proc.tamanho - indice * self.tamanho_pagina
        return max(0, min(self.tamanho_pagina, restante))

    def _validar_pagina(self, proc, tabela, pagina):
        if not isinstance(pagina, int) or isinstance(pagina, bool):
            raise MemoriaError("A página deve ser um número inteiro.")
        if pagina < 0 or pagina >= len(tabela):
            self._auditar("MEM_VIOLACAO", f"{proc.nome} (pid {proc.pid}) acessou página {pagina}")
            raise MemoriaError(
                f"Violação de segmentação: página lógica {pagina} fora do espaço de "
                f"endereçamento de '{proc.nome}' (válidas: 0 a {len(tabela) - 1})."
            )

    # criar / encerrar
    def criar_processo(self, proc):
        n = self._paginas_de(proc, self.tamanho_pagina)
        if self.paginas_alocadas + n > self.swap_paginas:
            raise MemoriaError(
                f"Memória virtual insuficiente: '{proc.nome}' precisa de {n} página(s), "
                f"restam {self.swap_paginas - self.paginas_alocadas} no espaço virtual "
                f"(swap de {self.swap_paginas} páginas)."
            )
        self.tabelas[proc.pid] = [Pagina() for _ in range(n)]
        self.processos[proc.pid] = proc
        self.faults_por_pid[proc.pid] = 0
        pg = self.tamanho_pagina
        linhas = [
            "[CRIAÇÃO DE PROCESSO NÃO CRÍTICO - MEMÓRIA VIRTUAL]",
            f"Tamanho do Processo : {_kb(proc.tamanho)} KB ({proc.tamanho} Bytes)",
            f"Tamanho da Página   : {_kb(pg)} KB ({pg} Bytes)",
            f"Cálculo de Páginas  : {_kb(proc.tamanho)} KB / {_kb(pg)} KB = "
            f"{proc.tamanho / pg:.4g} -> Requer {n} Página{'s' if n > 1 else ''} "
            f"Lógica{'s' if n > 1 else ''} ({_intervalo_paginas(n)}).",
            "",
            "--- ANÁLISE DE FRAGMENTAÇÃO INTERNA ---",
        ]
        indices = list(range(n))
        omitir = n > LIMITE_LISTAGEM
        for i in indices:
            if omitir and 2 <= i < n - 1:
                if i == 2:
                    linhas.append(f"... ({n - 3} páginas cheias omitidas) ...")
                continue
            uteis = self._bytes_uteis(proc, i)
            linhas.append(
                f"Página Lógica {i} : {uteis} Bytes ocupados ({uteis / pg * 100:.0f}%"
                + ("" if uteis == pg else " de uso") + ")"
            )
        desperdicio = n * pg - proc.tamanho
        if desperdicio:
            linhas.append(
                f"Fragmentação Interna Total: {desperdicio} Bytes de desperdício "
                f"na Página Lógica {n - 1}."
            )
        else:
            linhas.append("Fragmentação Interna Total: 0 Bytes (tamanho múltiplo da página).")
        linhas.append(
            "Status: Tabela de Páginas gerada sem alocar molduras na RAM (Alocação por demanda)."
        )
        self._auditar("VM_CRIADO", f"{proc.nome} (pid {proc.pid}): {n} página(s)")
        return linhas

    def encerrar_processo(self, proc):
        tabela = self._proc(proc)
        liberadas = swap_liberado = 0
        for i, entrada in enumerate(tabela):
            if entrada.frame is not None:
                self.molduras[entrada.frame] = None
                try:
                    self.fila.remove(entrada.frame)
                except ValueError:
                    pass
                liberadas += 1
            if entrada.slot is not None:
                self.slots_livres.append(entrada.slot)
                swap_liberado += 1
        del self.tabelas[proc.pid]
        del self.processos[proc.pid]
        self.faults_por_pid.pop(proc.pid, None)
        self._auditar("VM_ENCERRADO", f"{proc.nome} (pid {proc.pid})")
        return [
            f"Memória virtual liberada: {liberadas} moldura(s) devolvida(s) à RAM dinâmica "
            f"e {swap_liberado} página(s) removida(s) do swap."
        ]

    # tradução
    def traduzir(self, proc, pagina):
        tabela = self._proc(proc)
        self._validar_pagina(proc, tabela, pagina)
        entrada = tabela[pagina]
        linhas = ["[TRADUÇÃO DE ENDEREÇO: PÁGINA LÓGICA -> MOLDURA FÍSICA]"]
        if entrada.frame is not None:
            fisico = self.base_fisica + entrada.frame * self.tamanho_pagina
            linhas.append(
                f"Solicitação: Página Lógica {pagina} -> Mapeada na Moldura Física "
                f"{entrada.frame} (RAM Dinâmica) [HIT]"
            )
            linhas.append(
                f"Endereço físico da moldura: 0x{fisico:08X} "
                f"(= {self.base_fisica} + {entrada.frame} x {self.tamanho_pagina})"
            )
        else:
            onde = (f"cópia no swap (slot {entrada.slot})" if entrada.slot is not None
                    else "ainda nunca carregada")
            linhas.append(
                f"Solicitação: Página Lógica {pagina} -> NÃO MAPEADA na RAM [MISS] ({onde})"
            )
            linhas.append(
                "A tradução apenas consulta a tabela de páginas; um acesso real "
                "(execute_step) causará PAGE FAULT."
            )
        return linhas

    # execução / fault
    def _parse_instrucao(self, instrucao):
        partes = instrucao.replace(",", " ").split()
        if not partes:
            raise MemoriaError("Instrução vazia. Ex.: LOAD_DATA Página 2")
        verbo = partes[0].upper()
        if verbo in LEITURA:
            escrita = False
        elif verbo in ESCRITA:
            escrita = True
        else:
            raise MemoriaError(
                f"Instrução desconhecida '{partes[0]}'. Use LOAD_DATA/READ (leitura) "
                "ou STORE_DATA/WRITE (escrita), seguidos de 'Página N'."
            )
        numero = None
        for token in reversed(partes[1:]):
            if token.lstrip("-").isdigit():
                numero = int(token)
                break
        if numero is None:
            raise MemoriaError("Informe a página na instrução. Ex.: LOAD_DATA Página 2")
        return verbo, escrita, numero

    def executar_passo(self, proc, instrucao):
        tabela = self._proc(proc)
        verbo, escrita, pagina = self._parse_instrucao(instrucao)
        self._validar_pagina(proc, tabela, pagina)
        self.relogio += MS_POR_ACESSO
        self.acessos += 1
        entrada = tabela[pagina]
        tipo = "escrita" if escrita else "leitura"
        linhas = [
            "[CPU - REFERÊNCIA DE MEMÓRIA EM EXECUÇÃO]",
            f"{proc.nome} requisita acesso à Página Lógica {pagina} ({verbo}, {tipo})...",
        ]
        if entrada.frame is not None:
            self.hits += 1
            linhas.append(
                f"- Consulta Tabela de Páginas -> Página Lógica {pagina} presente na "
                f"Moldura Física {entrada.frame} [HIT]"
            )
        else:
            linhas.append(
                f"- Consulta Tabela de Páginas -> Página Lógica {pagina} NÃO ESTÁ NA RAM!"
            )
            linhas.append("")
            self._tratar_page_fault(proc, pagina, entrada, linhas)
        entrada.ref = True
        entrada.ultimo_acesso = self.relogio
        if escrita:
            entrada.sujo = True
            linhas.append(f"- Página {pagina} marcada como modificada (dirty).")
        return linhas

    def _tratar_page_fault(self, proc, pagina, entrada, linhas):
        self.faults += 1
        self.faults_por_pid[proc.pid] = self.faults_por_pid.get(proc.pid, 0) + 1
        self._auditar("MEM_PAGE_FAULT", f"{proc.nome} (pid {proc.pid}) página {pagina}")
        linhas.append(f"[PAGE FAULT DETECTADO]: Página Lógica {pagina} ausente na RAM!")
        livre = next((i for i, m in enumerate(self.molduras) if m is None), None)
        if livre is None:
            linhas.append(
                f"Memória RAM cheia. Executando Substituição de Página "
                f"(Algoritmo {NOMES_POLITICA[self.politica]}):"
            )
            livre = self._substituir(linhas)
        else:
            linhas.append(f"Há moldura livre na RAM dinâmica: Moldura Física {livre} (sem substituição).")
        if entrada.slot is not None:
            self.swap_in += 1
            linhas.append(
                f"- Lendo Página Lógica {pagina} de '{proc.nome}' do Swap (slot {entrada.slot})."
            )
        else:
            linhas.append(
                f"- Página Lógica {pagina} de '{proc.nome}' lida da memória secundária "
                "(primeira referência)."
            )
        self.molduras[livre] = (proc.pid, pagina)
        self.fila.append(livre)
        entrada.frame = livre
        entrada.ref = False
        entrada.sujo = False
        entrada.carregada_em = self.relogio
        linhas.append(
            f"- Carregando Página Lógica {pagina} de {proc.nome} na Moldura Física "
            f"{livre} (RAM Dinâmica)."
        )
        linhas.append(
            f"- Tabela de Páginas atualizada: Página Lógica {pagina} ---> Moldura Física {livre}."
        )

    # substituição
    def _descrever(self, frame):
        pid, pag = self.molduras[frame]
        return f"Página Lógica {pag} de '{self.processos[pid].nome}' (PID {pid})"

    def _escolher_vitima(self, linhas):
        ocupadas = [f for f, m in enumerate(self.molduras) if m is not None]
        if self.politica == "lru":
            def chave(f):
                pid, pag = self.molduras[f]
                e = self.tabelas[pid][pag]
                return (e.ultimo_acesso, e.carregada_em, f)
            vitima = min(ocupadas, key=chave)
            pid, pag = self.molduras[vitima]
            idade = self.relogio - self.tabelas[pid][pag].ultimo_acesso
            linhas.append(
                f"- Analisando histórico de acesso: {self._descrever(vitima)} "
                f"não é usada há {idade}ms (Mais antiga)."
            )
            return vitima
        if self.politica == "fifo":
            vitima = self.fila[0]
            linhas.append(
                f"- Fila de carga: {self._descrever(vitima)} é a mais antiga na RAM "
                "(primeira a entrar)."
            )
            return vitima
        # segunda chance
        linhas.append("- Varredura da fila circular (bit de referência R):")
        while True:
            f = self.fila[0]
            pid, pag = self.molduras[f]
            e = self.tabelas[pid][pag]
            if e.ref:
                e.ref = False
                self.fila.rotate(-1)
                linhas.append(
                    f"  Moldura {f} ({self._descrever(f)}): R=1 -> recebe SEGUNDA CHANCE "
                    "(R=0, vai para o fim da fila)."
                )
            else:
                linhas.append(f"  Moldura {f} ({self._descrever(f)}): R=0 -> VÍTIMA.")
                return f

    def _substituir(self, linhas):
        vitima = self._escolher_vitima(linhas)
        pid, pag = self.molduras[vitima]
        proc_v = self.processos[pid]
        e = self.tabelas[pid][pag]
        self.fila.remove(vitima)
        if e.sujo or e.slot is None:
            if e.slot is None:
                if not self.slots_livres:
                    raise MemoriaError("Swap cheio: não há slot livre para a página vítima.")
                e.slot = self.slots_livres.pop()
            self.swap_out += 1
            motivo = "modificada" if e.sujo else "sem cópia no swap"
            linhas.append(
                f"- Removendo Página Lógica {pag} do PID {pid} da RAM -> "
                f"Salvando no Swap (Disco), slot {e.slot} ({motivo})."
            )
        else:
            self.descartes += 1
            linhas.append(
                f"- Removendo Página Lógica {pag} do PID {pid} da RAM -> página limpa, "
                f"cópia válida já no Swap (slot {e.slot}): descartada sem escrita."
            )
        e.frame = None
        e.ref = False
        e.sujo = False
        self.molduras[vitima] = None
        self._auditar("MEM_SWAP_OUT", f"{proc_v.nome} (pid {pid}) página {pag} slot {e.slot}")
        return vitima

    # relatórios
    def status(self):
        usadas, total = self.molduras_usadas, self.total_molduras
        pct = usadas / total * 100
        cheio = round(pct / 5)
        swap_usado = self.swap_paginas - len(self.slots_livres)
        taxa = (self.faults / self.acessos * 100) if self.acessos else 0.0
        linhas = [
            "--- MEMÓRIA VIRTUAL (REGIÃO DINÂMICA - PAGINADA) ---",
            f"Região dinâmica         : {_kb(self.tamanho_dinamico)} KB em {total} molduras "
            f"de {_kb(self.tamanho_pagina)} KB",
            f"Molduras ocupadas/livres: {usadas}/{self.molduras_livres} ({pct:.1f}% usada)",
            f"[{'#' * cheio}{'.' * (20 - cheio)}]",
            f"Espaço virtual alocado  : {self.paginas_alocadas}/{self.swap_paginas} páginas "
            f"({self.paginas_alocadas * self.tamanho_pagina // 1024} KB de "
            f"{self.swap_paginas * self.tamanho_pagina // 1024} KB)",
            f"Swap em uso             : {swap_usado}/{self.swap_paginas} slots",
            f"Algoritmo de substituição: {NOMES_POLITICA[self.politica]}",
            f"Acessos: {self.acessos} | Hits: {self.hits} | Page faults: {self.faults} "
            f"({taxa:.1f}%)",
            f"Swap-in: {self.swap_in} | Swap-out: {self.swap_out} | "
            f"Descartes de páginas limpas: {self.descartes}",
        ]
        if not self.processos:
            linhas.append("Nenhum processo normal na memória virtual.")
            return linhas
        linhas.append("")
        linhas.append("Processos (páginas residentes na RAM / total, page faults):")
        for pid in sorted(self.processos):
            p = self.processos[pid]
            tab = self.tabelas[pid]
            res = sum(1 for e in tab if e.frame is not None)
            sw = sum(1 for e in tab if e.slot is not None and e.frame is None)
            linhas.append(
                f"  PID {pid:<5} {p.nome:<20} residentes {res}/{len(tab)}  "
                f"no swap {sw}  faults {self.faults_por_pid.get(pid, 0)}"
            )
        ocupadas = [(f, m) for f, m in enumerate(self.molduras) if m is not None]
        if ocupadas:
            linhas.append("")
            linhas.append("Mapa de molduras ocupadas (R=referenciada, M=modificada):")
            for f, (pid, pag) in ocupadas[:LIMITE_MOLDURAS]:
                e = self.tabelas[pid][pag]
                marcas = ("R" if e.ref else "-") + ("M" if e.sujo else "-")
                linhas.append(
                    f"  Moldura {f:<5} <- {self.processos[pid].nome} (PID {pid}) "
                    f"pág {pag} [{marcas}] último acesso: {e.ultimo_acesso}ms"
                )
            if len(ocupadas) > LIMITE_MOLDURAS:
                linhas.append(f"  ... mais {len(ocupadas) - LIMITE_MOLDURAS} moldura(s).")
        return linhas

    def relatorio_fragmentacao_interna(self):
        linhas = ["--- FRAGMENTAÇÃO INTERNA (MEMÓRIA VIRTUAL) ---"]
        if not self.processos:
            linhas.append("Nenhum processo paginado: sem fragmentação interna.")
            return linhas
        total_desp = total_alocado = 0
        for pid in sorted(self.processos):
            p = self.processos[pid]
            n = len(self.tabelas[pid])
            alocado = n * self.tamanho_pagina
            desp = alocado - p.tamanho
            total_desp += desp
            total_alocado += alocado
            detalhe = (f"na Página Lógica {n - 1} (uso de "
                       f"{self._bytes_uteis(p, n - 1) / self.tamanho_pagina * 100:.0f}%)"
                       if desp else "nenhum")
            linhas.append(
                f"{p.nome} (PID {pid}): {n} página(s), {p.tamanho} B úteis de {alocado} B "
                f"alocados -> desperdício {desp} B ({desp / alocado * 100:.1f}%) {detalhe}"
            )
        linhas.append(
            f"Total: {total_desp} Bytes desperdiçados em {total_alocado} Bytes alocados "
            f"({total_desp / total_alocado * 100:.1f}%)."
        )
        return linhas
