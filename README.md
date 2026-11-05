# Simulador de Sistema de Arquivos (FS)

Trabalho de Sistemas Operacionais — **Etapa 2: Sistema de Arquivos e E/S**.

Simulador em Python (3.8+, sem dependências) com:

- **Hierarquia em árvore** com caminhos absolutos e relativos
- **CRUD** de diretórios e arquivos
- **Disco simulado em blocos** de tamanho fixo
- **Alocação física:** contígua, encadeada (linked list/FAT) e indexada (i-node)
- **Diagnóstico do disco:** mapa de blocos, fragmentação interna/externa e necessidade de compactação
- **E/S e HDD:** fila de requisições por trilha e escalonadores FCFS, SSTF, SCAN e C-SCAN

## Equipe
- Miguel Monteiro
- Giovanna Costa

## Como executar
```bash
python src/main.py                                  # modo interativo
python src/main.py --script exemplos/demo.txt       # roda um roteiro
python src/main.py --blocks 200 --script exemplos/demo_io.txt
python src/main.py --blocks 16 --block-size 4096 --alloc indexada
python -m unittest discover tests                   # testes
```

## Comandos
| Comando | Descrição |
|---|---|
| `mkdir [-p] <caminho>` | cria diretório |
| `create <caminho> --size 10KB [--alloc contigua\|encadeada\|indexada]` | cria arquivo |
| `write_file <caminho> --size 8KB [--alloc ...]` | cria arquivo e registra escritas na fila de E/S |
| `ls`, `cd`, `pwd`, `tree` | navegação |
| `read <arquivo>` | metadados e blocos |
| `read_file <arquivo>` | lê metadados e registra leituras na fila de E/S |
| `io_queue`, `io_clear` | lista ou limpa a fila de E/S |
| `disk_sched <fcfs\|sstf\|scan\|cscan\|all>` | escalona a fila; aceita `--head`, `--dir`, `--tracks` e `--max-track` |
| `update <arquivo> --size 20KB` | redimensiona |
| `mv <origem> <destino>` | move/renomeia |
| `rm [-r] <caminho>` | remove |
| `alloc <estrategia>` | estratégia padrão |
| `fs_status [--details]` | mapa do disco + fragmentação |
| `compact` | compacta o disco |

## Estrutura
```
src/
  disk.py          camada física (blocos)
  allocation.py    estratégias de alocação
  fs.py            árvore + CRUD
  io_request.py    requisição de E/S por bloco/trilha
  scheduler.py     escalonamento do braço de HDD
  diagnostico.py   mapa, fragmentação, compactação
  main.py          shell de comandos
exemplos/demo.txt  roteiro de demonstração
exemplos/demo_io.txt roteiro de E/S e escalonamento
tests/             testes automatizados
```

## Divisão de tarefas
Veja [CONTRIBUINDO.md](CONTRIBUINDO.md).

## Status
- **Etapa 2 (E/S e HDD): concluída.** RAID e SSD não fazem parte desta etapa.
- [x] Árvore + CRUD
- [x] Disco em blocos
- [x] Alocação contígua e indexada
- [x] Mapa do disco
- [x] Alocação encadeada
- [x] Relatório de fragmentação
- [x] Compactação
- [x] Fila de E/S integrada a create/update/read
- [x] Escalonadores HDD FCFS, SSTF, SCAN e C-SCAN
