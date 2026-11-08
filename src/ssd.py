
"""Simulação de gerenciamento de SSD com mapeamento de páginas e Wear Leveling."""


class SSDError(Exception):
    """Erro relacionado às operações do SSD."""
    pass


class SSD:
    def __init__(self, total_blocks=8, pages_per_block=4):
        if total_blocks < 2:
            raise SSDError("O SSD precisa ter pelo menos 2 blocos.")

        if pages_per_block < 1:
            raise SSDError("Cada bloco precisa ter pelo menos 1 página.")

        self.total_blocks = total_blocks
        self.pages_per_block = pages_per_block
        self.total_pages = total_blocks * pages_per_block

        # Reserva um bloco de capacidade física para auxiliar o gerenciamento.
        self.capacity_pages = self.total_pages - pages_per_block

        # Cada posição representa uma página física.
        # None = página livre.
        # Dicionário = página com dados válidos ou inválidos.
        self.pages = [None] * self.total_pages

        # Mapeia páginas lógicas para páginas físicas.
        self.mapping = {}

        # Quantidade de apagamentos de cada bloco.
        self.erase_count = [0] * total_blocks

        # Estatísticas do SSD.
        self.read_count = 0
        self.write_count = 0
        self.erase_operations = 0
        self.gc_count = 0

    def block_of(self, physical_page):
        """Retorna o bloco físico ao qual uma página pertence."""
        return physical_page // self.pages_per_block

    def free_pages(self):
        """Retorna os endereços das páginas físicas livres."""
        return [
            i for i, page in enumerate(self.pages)
            if page is None
        ]

    def _free_pages_by_block(self, exclude_block=None):
        """Agrupa páginas livres por bloco físico."""
        livres = {}

        for page in self.free_pages():
            bloco = self.block_of(page)

            if bloco == exclude_block:
                continue

            livres.setdefault(bloco, []).append(page)

        return livres

    def _allocate_page(self, exclude_block=None):
        """
        Escolhe uma página livre em um bloco com menor desgaste.

        Essa seleção representa o Wear Leveling dinâmico.
        """
        livres = self._free_pages_by_block(exclude_block)

        if not livres:
            raise SSDError("Não existem páginas físicas livres.")

        # Prioriza o bloco com menos apagamentos.
        # Em caso de empate, prioriza o bloco com mais páginas livres.
        bloco = min(
            livres,
            key=lambda b: (
                self.erase_count[b],
                -len(livres[b]),
                b
            )
        )

        return livres[bloco][0]

    def write(self, logical_page, data):
        """Escreve dados em uma página lógica."""
        if logical_page < 0:
            raise SSDError("O endereço lógico não pode ser negativo.")

        if (
            logical_page not in self.mapping
            and len(self.mapping) >= self.capacity_pages
        ):
            raise SSDError("Capacidade lógica do SSD esgotada.")

        # Antes de sobrescrever, invalida a página física antiga.
        pagina_antiga = self.mapping.get(logical_page)

        if pagina_antiga is not None:
            self.pages[pagina_antiga]["valid"] = False

        # Quando o espaço livre fica baixo, tenta coletar lixo.
        if (
            len(self.free_pages()) <= self.pages_per_block
            and any(
                page is not None and not page["valid"]
                for page in self.pages
            )
        ):
            try:
                self.garbage_collect()
            except SSDError:
                # Se ainda houver espaço, a escrita pode continuar.
                if not self.free_pages():
                    if pagina_antiga is not None:
                        self.pages[pagina_antiga]["valid"] = True
                    raise

        try:
            physical_page = self._allocate_page()
        except SSDError:
            if pagina_antiga is not None:
                self.pages[pagina_antiga]["valid"] = True
            raise

        self.pages[physical_page] = {
            "logical_page": logical_page,
            "data": data,
            "valid": True
        }

        self.mapping[logical_page] = physical_page
        self.write_count += 1

        return physical_page

    def read(self, logical_page):
        """Lê os dados associados a uma página lógica."""
        if logical_page not in self.mapping:
            raise SSDError(
                f"Página lógica {logical_page} não encontrada."
            )

        physical_page = self.mapping[logical_page]
        self.read_count += 1

        return self.pages[physical_page]["data"]

    def trim(self, logical_page):
        """Invalida uma página lógica e libera seu mapeamento."""
        if logical_page not in self.mapping:
            raise SSDError("Página lógica não encontrada.")

        physical_page = self.mapping.pop(logical_page)
        self.pages[physical_page]["valid"] = False

    def garbage_collect(self):
        """
        Recolhe páginas inválidas.

        Copia as páginas válidas de um bloco para outros blocos,
        apaga o bloco escolhido e contabiliza o desgaste.
        """
        livres = self.free_pages()

        candidatos = []

        for bloco in range(self.total_blocks):
            inicio = bloco * self.pages_per_block
            fim = inicio + self.pages_per_block

            paginas = self.pages[inicio:fim]

            invalidas = sum(
                1 for p in paginas
                if p is not None and not p["valid"]
            )

            validas = sum(
                1 for p in paginas
                if p is not None and p["valid"]
            )

            livres_fora = sum(
                1 for p in livres
                if self.block_of(p) != bloco
            )

            if invalidas > 0 and livres_fora >= validas:
                candidatos.append(
                    (bloco, invalidas, validas)
                )

        if not candidatos:
            raise SSDError(
                "Não há espaço suficiente para executar a coleta de lixo."
            )

        # Prioriza o bloco com mais páginas inválidas.
        # Em caso de empate, escolhe o menos desgastado.
        bloco, _, _ = max(
            candidatos,
            key=lambda item: (
                item[1],
                -self.erase_count[item[0]]
            )
        )

        inicio = bloco * self.pages_per_block
        fim = inicio + self.pages_per_block

        # Copia as páginas válidas para outros blocos.
        for physical_page in range(inicio, fim):
            pagina = self.pages[physical_page]

            if pagina is not None and pagina["valid"]:
                nova_pagina = self._allocate_page(
                    exclude_block=bloco
                )

                self.pages[nova_pagina] = pagina.copy()

                logical_page = pagina["logical_page"]
                self.mapping[logical_page] = nova_pagina

        # Apaga todas as páginas do bloco escolhido.
        for physical_page in range(inicio, fim):
            self.pages[physical_page] = None

        self.erase_count[bloco] += 1
        self.erase_operations += 1
        self.gc_count += 1

        return bloco

    def status(self):
        """Retorna um resumo do estado atual do SSD."""
        validas = sum(
            1 for p in self.pages
            if p is not None and p["valid"]
        )

        invalidas = sum(
            1 for p in self.pages
            if p is not None and not p["valid"]
        )

        livres = len(self.free_pages())

        return {
            "total_blocos": self.total_blocks,
            "total_paginas": self.total_pages,
            "paginas_validas": validas,
            "paginas_invalidas": invalidas,
            "paginas_livres": livres,
            "leituras": self.read_count,
            "escritas": self.write_count,
            "apagamentos": self.erase_operations,
            "coletas_lixo": self.gc_count
        }

    def wear_report(self):
        """Apresenta o desgaste individual dos blocos."""
        return [
            {
                "bloco": bloco,
                "apagamentos": self.erase_count[bloco]
            }
            for bloco in range(self.total_blocks)
        ]