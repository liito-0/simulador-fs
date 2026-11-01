# Simulador de Sistema de Arquivos (FS)

Trabalho de Sistemas Operacionais — **Etapa 1: Sistema de Arquivos**.

Simulador em Python (3.8+, sem dependências) com:

- **Hierarquia em árvore** com caminhos absolutos e relativos
- **CRUD** de diretórios e arquivos
- **Disco simulado em blocos** de tamanho fixo
- **Alocação física:** contígua, encadeada (linked list/FAT) e indexada (i-node)
- **Diagnóstico do disco:** mapa de blocos, fragmentação interna/externa e necessidade de compactação

## Equipe
- Miguel Monteiro
- Giovanna Costa

## Como executar
```bash
python src/main.py                                  # modo interativo
python src/main.py --script exemplos/demo.txt       # roda um roteiro
python src/main.py --blocks 16 --block-size 4096 --alloc indexada
python -m unittest discover tests                   # testes
```

## Comandos
| Comando | Descrição |
|---|---|
| `mkdir [-p] <caminho>` | cria diretório |
| `create <caminho> --size 10KB [--alloc contigua\|encadeada\|indexada]` | cria arquivo |
| `ls`, `cd`, `pwd`, `tree` | navegação |
| `read <arquivo>` | metadados e blocos |
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
  diagnostico.py   mapa, fragmentação, compactação
  main.py          shell de comandos
exemplos/demo.txt  roteiro de demonstração
tests/             testes automatizados
```

## Divisão de tarefas
Veja [CONTRIBUINDO.md](CONTRIBUINDO.md).

## Status
- [x] Árvore + CRUD
- [x] Disco em blocos
- [x] Alocação contígua e indexada
- [x] Mapa do disco
- [ ] Alocação encadeada
- [ ] Relatório de fragmentação
- [ ] Compactação
