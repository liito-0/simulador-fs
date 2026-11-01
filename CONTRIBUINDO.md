# Divisão de tarefas e fluxo de trabalho

| Responsável | Tarefa | Onde |
|---|---|---|
| Miguel Monteiro | Árvore, CRUD, disco, alocação contígua/indexada, mapa, shell | `fs.py`, `disk.py`, `allocation.py`, `main.py`, `diagnostico.mapa_disco` |
| Giovanna Costa | Alocação encadeada | `allocation.Encadeada` |
| Giovanna Costa | Relatório de fragmentação | `diagnostico.relatorio_fragmentacao` |
| Giovanna Costa | Compactação | `diagnostico.compactar` |

Os pontos pendentes têm `TODO (Giovanna)` com dicas no docstring.

## Fluxo com Git
1. `main` fica sempre funcionando.
2. Cada pessoa trabalha na sua branch (`giovanna/fragmentacao`, `giovanna/encadeada`, ...).
3. Commits pequenos e com mensagem clara (ex.: `feat: implementa alocação encadeada`).
4. Antes de abrir Pull Request: `python -m unittest discover tests` e `python src/main.py --script exemplos/demo.txt`.
5. A outra pessoa revisa e faz o merge.