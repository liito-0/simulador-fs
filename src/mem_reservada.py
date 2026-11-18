"""Alocação contígua da região reservada da RAM."""


class MemoriaError(Exception):
    pass


class RegiaoReservada:
    def __init__(self, tamanho=4 * 1024 ** 2, base=1 * 1024 ** 2):
        if tamanho <= 0 or base < 0 or base >= tamanho:
            raise MemoriaError("A região reservada deve ser maior que a base fixa do núcleo.")
        self.tamanho = tamanho
        self.base = base
        self.alocacoes = {}

    @staticmethod
    def formatar_endereco(endereco):
        mb = endereco / (1024 ** 2)
        uma_casa = round(mb, 1)
        if abs(mb - uma_casa) < 0.0000001:
            return f"{uma_casa:.1f} MB"
        return f"{mb:.3f}".rstrip("0").rstrip(".") + " MB"

    @staticmethod
    def _kb(tamanho):
        kb = tamanho / 1024
        return str(int(kb)) if kb.is_integer() else f"{kb:.3f}".rstrip("0").rstrip(".")

    def _ordenadas(self):
        return sorted(
            ((inicio, fim, nome) for nome, (inicio, fim) in self.alocacoes.items()),
            key=lambda item: item[0],
        )

    def lacunas(self):
        lacunas, cursor = [], self.base
        for inicio, fim, _ in self._ordenadas():
            if inicio > cursor:
                lacunas.append((cursor, inicio))
            cursor = fim
        if cursor < self.tamanho:
            lacunas.append((cursor, self.tamanho))
        return lacunas

    @property
    def total_livre(self):
        return sum(fim - inicio for inicio, fim in self.lacunas())

    @property
    def maior_bloco(self):
        return max((fim - inicio for inicio, fim in self.lacunas()), default=0)

    @property
    def fragmentacao_externa(self):
        return len(self.lacunas()) >= 2

    def alocar(self, nome, tamanho):
        if nome == "Núcleo Base do SO":
            raise MemoriaError("O Núcleo Base do SO é fixo e não pode ser alocado.")
        if nome in self.alocacoes:
            raise MemoriaError(f"Já existe uma alocação para '{nome}'.")
        if not isinstance(tamanho, int) or tamanho <= 0:
            raise MemoriaError("O tamanho do processo deve ser um inteiro positivo em bytes.")
        lacunas = self.lacunas()
        total = sum(fim - inicio for inicio, fim in lacunas)
        maior = max((fim - inicio for inicio, fim in lacunas), default=0)
        if total < tamanho:
            raise MemoriaError(
                f"Sem espaço total: há {self._kb(total)} KB livres, "
                f"mas a requisição exige {self._kb(tamanho)} KB."
            )
        if maior < tamanho:
            raise MemoriaError(
                f"fragmentação externa: há {self._kb(total)} KB livres, "
                f"mas o maior bloco contíguo é {self._kb(maior)} KB"
            )
        for inicio, fim in lacunas:
            if fim - inicio >= tamanho:
                alocacao = (inicio, inicio + tamanho)
                self.alocacoes[nome] = alocacao
                return alocacao
        raise MemoriaError("Não foi possível alocar o processo na região reservada.")

    def liberar(self, nome):
        if nome == "Núcleo Base do SO":
            raise MemoriaError("O Núcleo Base do SO é fixo e não pode ser liberado.")
        if nome not in self.alocacoes:
            raise MemoriaError(f"Processo '{nome}' não encontrado na região reservada.")
        return self.alocacoes.pop(nome)

    def compactar(self):
        cursor = self.base
        movimentos = []
        novas_alocacoes = {}
        for inicio, fim, nome in self._ordenadas():
            tamanho = fim - inicio
            novo_inicio, novo_fim = cursor, cursor + tamanho
            novas_alocacoes[nome] = (novo_inicio, novo_fim)
            if (inicio, fim) != (novo_inicio, novo_fim):
                movimentos.append((nome, inicio, fim, novo_inicio, novo_fim))
            cursor = novo_fim
        self.alocacoes = novas_alocacoes
        return movimentos

    def mapa(self):
        processos = self._ordenadas()
        lacunas = self.lacunas()
        total_mb = self.tamanho / (1024 ** 2)
        total_texto = (
            f"{int(total_mb)} MB" if total_mb.is_integer()
            else self.formatar_endereco(self.tamanho)
        )
        linhas = [
            f"--- MAPA DA ÁREA CRÍTICA/RESERVADA DA RAM "
            f"(Total: {total_texto} - Alocação Fixa) ---"
        ]
        segmentos = [(0, self.base, "Núcleo Base do SO", "base")]
        for inicio, fim, nome in processos:
            segmentos.append((inicio, fim, nome, "processo"))
        for indice, (inicio, fim) in enumerate(lacunas, 1):
            rotulo = "Bloco Livre Contíguo" if len(lacunas) == 1 else f"FRAGMENTO LIVRE {indice}"
            segmentos.append((inicio, fim, rotulo, "livre"))
        segmentos.sort(key=lambda item: item[0])
        for inicio, fim, nome, tipo in segmentos:
            estado = "[LIVRE]" if tipo == "livre" and len(lacunas) == 1 else (
                "[LIVRE - LACUNA]" if tipo == "livre" else "[OCUPADO]"
            )
            linhas.append(
                f"[{self.formatar_endereco(inicio)} - {self.formatar_endereco(fim)}] : "
                f"{nome:<20} ({self._kb(fim - inicio)} KB) {estado}"
            )
        return linhas

    def diagnostico(self):
        lacunas = self.lacunas()
        total, maior = self.total_livre, self.maior_bloco
        linhas = [
            "--- DIAGNÓSTICO DE FRAGMENTAÇÃO EXTERNA ---",
            f"Total de Memória Livre na Área Reservada : {self._kb(total)} KB "
            f"({self.formatar_endereco(total)})",
            f"Maior Bloco Contíguo Disponível          : {self._kb(maior)} KB "
            f"({self.formatar_endereco(maior)})",
            "Fragmentação Externa Detectada           : "
            + (f"SIM ({len(lacunas)} fragmentos não contíguos)"
               if len(lacunas) >= 2 else "NÃO"),
        ]
        if len(lacunas) >= 2:
            meio = (maior + total) // 2
            unidade = 4 * 1024
            requisicao = ((meio + unidade // 2) // unidade) * unidade
            linhas.append(
                f"Status: Uma requisição contígua de {self._kb(requisicao)} KB "
                "falhará por ausência de bloco único."
            )
        else:
            linhas.append(
                f"Status: Sem fragmentação externa: qualquer requisição de até "
                f"{self._kb(maior)} KB cabe em bloco único."
            )
        return linhas
