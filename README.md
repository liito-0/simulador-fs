# Simulador de Sistema de Arquivos (FS)

Trabalho de Sistemas Operacionais — **Etapa 2: Sistema de Arquivos e E/S** (entrega parcial).

Simulador em Python (3.8+, sem dependências) com:

- **Hierarquia em árvore** com caminhos absolutos e relativos
- **CRUD** de diretórios e arquivos
- **Disco simulado em blocos** de tamanho fixo
- **Alocação física:** contígua, encadeada (linked list/FAT) e indexada (i-node)
- **Diagnóstico do disco:** mapa de blocos, fragmentação interna/externa e necessidade de compactação
- **Integração FS → E/S:** cada operação de arquivo gera requisições traduzidas em operações do dispositivo escolhido
- **HDD:** fila de requisições por trilha e escalonamento do braço (FCFS, SSTF, SCAN e C-SCAN) com deslocamento total
- **SSD:** acesso por páginas/blocos, invalidação de páginas, garbage collection, TRIM e wear leveling
- **RAID 5:** distribuição em stripes com paridade rotativa, falha de disco e reconstrução via XOR

## Equipe
- Miguel Monteiro
- Giovanna Costa

## Como executar
```bash
python src/main.py                                  # modo interativo (HDD)
python src/main.py --script exemplos/demo.txt       # roda um roteiro
python src/main.py --blocks 16 --block-size 4096 --alloc indexada
python -m unittest discover tests                   # testes
```

### Escolha do dispositivo de armazenamento
A opção `--device` define para onde vai a E/S gerada pelo sistema de arquivos:

| Dispositivo | Comando | O que o `write_file`/`read_file`/`update` mostra |
|---|---|---|
| HDD (padrão) | `python src/main.py --blocks 200 --script exemplos/demo_io.txt` | Trilhas pendentes e posição da cabeça; depois `disk_sched` calcula o deslocamento do braço |
| SSD | `python src/main.py --device ssd --blocks 16 --script exemplos/demo_ssd.txt` | Bloco → página lógica → página física, páginas invalidadas, GC e apagamentos por bloco (wear leveling) |
| RAID 5 | `python src/main.py --device raid5 --blocks 32 --script exemplos/demo_raid.txt` | Distribuição de dados e paridade por disco, teste de falha e reconstrução via XOR |

Opção extra: `--raid-disks N` define a quantidade de discos do RAID 5 (padrão 3, mínimo 3).

## Comandos
| Comando | Descrição |
|---|---|
| `mkdir [-p] <caminho>` | cria diretório |
| `create <caminho> --size 10KB [--alloc contigua\|encadeada\|indexada]` | cria arquivo |
| `write_file <caminho> --size 8KB [--alloc ...]` | cria arquivo e gera E/S de escrita no dispositivo ativo |
| `ls`, `cd`, `pwd`, `tree` | navegação |
| `read <arquivo>` | metadados e blocos |
| `read_file <arquivo>` | lê metadados e gera E/S de leitura no dispositivo ativo |
| `update <arquivo> --size 20KB` | redimensiona (regrava os blocos) |
| `mv <origem> <destino>` | move/renomeia |
| `rm [-r] <caminho>` | remove (no SSD faz TRIM; no RAID remove arquivos, inclusive ao usar `rm -r`) |
| `alloc <estrategia>` | estratégia padrão de alocação |
| `fs_status [--details]` | mapa do disco + fragmentação |
| `compact` | compacta o disco |

### E/S e escalonamento (HDD)
| Comando | Descrição |
|---|---|
| `io_queue`, `io_clear` | lista ou limpa a fila de E/S |
| `disk_sched <fcfs\|sstf\|scan\|cscan\|all>` | escalona a fila; aceita `--head`, `--dir up\|down`, `--tracks 98,183,...` e `--max-track` |

Exemplo (Exemplo 2.1 do enunciado):
```
disk_sched all --head 53 --max-track 199 --tracks 98,183,37,122,14
```
SSTF: `53 -> 37 -> 14 -> 98 -> 122 -> 183`, total de 208 trilhas.

Nos modos `ssd` e `raid5` não há fila de trilhas; `disk_sched` só funciona com `--tracks`.

### SSD
| Comando | Descrição |
|---|---|
| `ssd_write <pagina> <conteúdo>` | grava em uma página lógica |
| `ssd_read <pagina>` | lê uma página lógica |
| `ssd_trim <pagina>` | invalida uma página |
| `ssd_status` | páginas válidas/inválidas/livres, leituras, escritas, apagamentos e GC |
| `ssd_wear` | apagamentos por bloco (wear leveling) |

### RAID 5
Os discos são numerados **a partir de 1**.

| Comando | Descrição |
|---|---|
| `raid_write <id> <conteúdo>` | grava um conteúdo no arranjo |
| `raid_read <id>` | lê (reconstrói via XOR se houver disco com falha) |
| `raid_fail <disco>` | simula a falha de um disco |
| `raid_recover <disco>` | reconstrói o disco via XOR |
| `raid_status` | estado do arranjo |

Com `--device raid5`, o `write_file` imprime automaticamente a distribuição em disco e um teste de falha simulado.
No RAID, `mv` atualiza os identificadores dos arquivos movidos no arranjo, e `rm -r` remove do RAID todos os arquivos da árvore removida.

## Etapa 3: controle de acesso, criptografia e antivírus

- Permissões rwx em modo octal com `chmod`, consulta por `acl` e listagem detalhada com `ls -l`. Diretórios começam em `755`, arquivos em `644`; `chown` exige MODO_KERNEL.
- `create` e `write_file` aceitam `--content "texto"` (o tamanho é calculado em bytes); o conteúdo é gravado nos blocos lógicos do disco.
- `encrypt_file <caminho> --key K`, `decrypt_file <caminho> --key K` e `cat <caminho> [--key K]` usam uma simulação didática de criptografia em repouso. A chave não é armazenada. Esta cifra não é apropriada para produção.
- `antivirus_scan [caminho]` e `disk_tamper <caminho|--block N> [--data TEXTO]` exigem MODO_KERNEL. O scanner valida hashes de blocos e assinaturas fictícias.
- O antivírus cobre somente o disco lógico (`disk.blocks`). A camada não inspeciona nem valida conteúdo diretamente no SSD ou nos discos do RAID; o comportamento de SSD/RAID permanece independente.

## Etapa 4: gerenciamento de memória

O shell oferece uma área reservada contígua para processos críticos e deixa o roteamento da região dinâmica preparado para a implementação de memória virtual.

Opções de inicialização: `--ram 8MB`, `--reserved 4MB`, `--page-size 4KB` e `--report-every 5` (zero desliga os relatórios periódicos).

| Comando | Descrição |
|---|---|
| `create_process --name N --size 512KB --type critical\|normal` | Criar processo; tipo crítico exige MODO_KERNEL |
| `terminate_process --name N` | Encerrar processo (usuário comum só encerra seus processos normais) |
| `ps` | Listar processos, região e dono |
| `memory_status [--reserved\|--virtual]` | Visão geral ou estado/mapa de uma região |
| `memory_compact --reserved` | Compactar a região reservada (exige MODO_KERNEL) |
| `memory_report` | Diagnóstico de fragmentação externa e interna |
| `translate_address --process N --page K` | Delegar tradução para a memória virtual |
| `execute_step --process N --instruction "LOAD_DATA Página 2"` | Delegar a instrução para a memória virtual |

Execução do roteiro: `python src/main.py --script exemplos/demo_memoria_reservada.txt`.

## Estrutura
```
src/
  disk.py          camada física (blocos)
  allocation.py    estratégias de alocação
  fs.py            árvore + CRUD + tradução da E/S para HDD/SSD/RAID
  io_request.py    requisição de E/S por bloco/trilha
  scheduler.py     escalonamento do braço de HDD
  ssd.py           SSD: páginas, GC, TRIM e wear leveling
  raid.py          RAID 5: stripes, paridade XOR, falha e recuperação
  diagnostico.py   mapa, fragmentação, compactação
  processo.py      registro de processos
  mem_reservada.py alocação contígua da região reservada
  memoria.py       gerenciador e integração opcional com memória virtual
  main.py          shell de comandos
exemplos/
  demo.txt         alocação, diagnóstico e compactação
  demo_io.txt      E/S e escalonamento de HDD
  demo_ssd.txt     E/S em SSD com GC e wear leveling
  demo_raid.txt    E/S em RAID 5 com falha e recuperação
tests/             testes automatizados
```

## Divisão de tarefas
Veja [CONTRIBUINDO.md](CONTRIBUINDO.md).

## Status
- [x] Árvore + CRUD
- [x] Disco em blocos
- [x] Alocação contígua, encadeada e indexada
- [x] Mapa do disco, relatório de fragmentação e compactação
- [x] Fila de E/S integrada a create/update/read
- [x] Escalonadores HDD FCFS, SSTF, SCAN e C-SCAN
- [x] SSD integrado ao FS (páginas, GC, TRIM, wear leveling)
- [x] RAID 5 integrado ao FS (paridade, falha e reconstrução XOR)
- [x] Etapa 4: região reservada, fragmentação externa e compactação
- [x] Etapa 4: memória virtual (paginação, tradução, page fault, swap, LRU/Segunda Chance/FIFO)