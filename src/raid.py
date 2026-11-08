
class RAIDError(Exception):
    """Erro nas operações do RAID."""
    pass


class RAID5:
    def __init__(self, total_disks=3, block_size=4096):
        if total_disks < 3:
            raise RAIDError("RAID 5 exige pelo menos 3 discos.")

        if block_size <= 0:
            raise RAIDError("O tamanho do bloco deve ser positivo.")

        self.total_disks = total_disks
        self.block_size = block_size

        # Cada posição representa um disco físico.
        # Cada disco armazena os blocos correspondentes às stripes.
        self.disks = [[] for _ in range(total_disks)]

        self.failed_disks = set()

        # Metadados dos arquivos armazenados.
        self.files = {}

        self.next_file_id = 1

    def _xor(self, blocks):
        """Calcula o XOR entre blocos de mesmo tamanho."""
        result = bytearray(self.block_size)

        for block in blocks:
            if block is None or len(block) != self.block_size:
                raise RAIDError("Não foi possível calcular a paridade.")

            for i in range(self.block_size):
                result[i] ^= block[i]

        return bytes(result)

    def _parity_disk(self, stripe):
        """Distribui a posição da paridade entre os discos."""
        return self.total_disks - 1 - (stripe % self.total_disks)

    def _data_disks(self, stripe):
        """Retorna os discos destinados aos dados da stripe."""
        parity_disk = self._parity_disk(stripe)

        return [
            disk
            for disk in range(self.total_disks)
            if disk != parity_disk
        ]

    def _get_block(self, disk_index, stripe):
        """Obtém um bloco, reconstruindo-o se houver uma falha."""

        if disk_index in self.failed_disks:
            if len(self.failed_disks) > 1:
                raise RAIDError(
                    "RAID 5 não suporta falha de mais de um disco."
                )

            available = [
                self.disks[i][stripe]
                for i in range(self.total_disks)
                if i != disk_index
            ]

            return self._xor(available)

        return self.disks[disk_index][stripe]

    def write(self, data, file_id=None):
        """Grava um arquivo, distribuindo dados e paridade."""

        if self.failed_disks:
            raise RAIDError(
                "Não é possível gravar enquanto houver disco com falha."
            )

        if isinstance(data, str):
            content = data.encode("utf-8")
            is_text = True
        elif isinstance(data, bytes):
            content = data
            is_text = False
        else:
            raise RAIDError("Os dados devem ser str ou bytes.")

        if file_id is None:
            file_id = f"arquivo_{self.next_file_id}"
            self.next_file_id += 1
        elif not isinstance(file_id, str) or not file_id:
            raise RAIDError("Identificador de arquivo inválido.")

        if file_id in self.files:
            raise RAIDError("Já existe um arquivo com esse identificador.")

        original_size = len(content)

        # Divide os dados em blocos.
        data_blocks = [
            content[i:i + self.block_size]
            for i in range(0, original_size, self.block_size)
        ]

        # Cada stripe armazena dados em N-1 discos.
        data_per_stripe = self.total_disks - 1

        # Preenche o último bloco de cada arquivo, se necessário.
        if data_blocks and len(data_blocks[-1]) < self.block_size:
            data_blocks[-1] += (
                b"\0" * (self.block_size - len(data_blocks[-1]))
            )

        start_stripe = len(self.disks[0])
        stripe_count = 0

        for i in range(0, len(data_blocks), data_per_stripe):
            group = data_blocks[i:i + data_per_stripe]

            while len(group) < data_per_stripe:
                group.append(bytes(self.block_size))

            stripe = len(self.disks[0])
            parity_disk = self._parity_disk(stripe)
            data_disks = self._data_disks(stripe)

            parity = self._xor(group)

            # Distribui os blocos de dados.
            for disk_index, block in zip(data_disks, group):
                self.disks[disk_index].append(block)

            # Armazena a paridade no disco correspondente.
            self.disks[parity_disk].append(parity)

            stripe_count += 1

        self.files[file_id] = {
            "inicio": start_stripe,
            "stripes": stripe_count,
            "tamanho": original_size,
            "texto": is_text
        }

        return file_id

    def read(self, file_id):
        """Lê um arquivo e reconstrói dados quando necessário."""

        if file_id not in self.files:
            raise RAIDError("Arquivo não encontrado.")

        if len(self.failed_disks) > 1:
            raise RAIDError(
                "Dados indisponíveis: mais de um disco falhou."
            )

        metadata = self.files[file_id]

        start = metadata["inicio"]
        count = metadata["stripes"]

        result = bytearray()

        for stripe in range(start, start + count):
            for disk_index in self._data_disks(stripe):
                block = self._get_block(disk_index, stripe)
                result.extend(block)

        # Remove o preenchimento adicionado na gravação.
        result = bytes(result[:metadata["tamanho"]])

        if metadata["texto"]:
            return result.decode("utf-8")

        return result

    def fail_disk(self, disk_index):
        """Simula a falha física de um disco."""

        if not isinstance(disk_index, int):
            raise RAIDError("Índice de disco inválido.")

        if not 0 <= disk_index < self.total_disks:
            raise RAIDError("Índice de disco fora do limite.")

        if disk_index in self.failed_disks:
            raise RAIDError("Esse disco já está com falha.")

        if self.failed_disks:
            raise RAIDError(
                "RAID 5 não suporta falha simultânea de dois discos."
            )

        self.failed_disks.add(disk_index)

        # Simula a perda física dos dados.
        self.disks[disk_index] = [
            None for _ in self.disks[disk_index]
        ]

    def recover(self, disk_index):
        """Reconstrói integralmente um disco utilizando XOR."""

        if disk_index not in self.failed_disks:
            raise RAIDError("O disco informado não está com falha.")

        if len(self.failed_disks) > 1:
            raise RAIDError(
                "Não é possível reconstruir mais de um disco."
            )

        recovered = []

        for stripe in range(len(self.disks[disk_index])):
            available = [
                self.disks[i][stripe]
                for i in range(self.total_disks)
                if i != disk_index
            ]

            recovered.append(self._xor(available))

        self.disks[disk_index] = recovered
        self.failed_disks.remove(disk_index)

        return True

    def status(self):
        """Retorna informações do arranjo RAID."""

        return {
            "nivel": "RAID 5",
            "discos": self.total_disks,
            "tamanho_bloco": self.block_size,
            "discos_com_falha": sorted(self.failed_disks),
            "arquivos": len(self.files),
            "stripes_por_disco": [
                len(disk) for disk in self.disks
            ]
        }