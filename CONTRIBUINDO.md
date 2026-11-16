# Divisão de tarefas e fluxo de trabalho

| Responsável | Tarefa | Onde |
|---|---|---|
| Miguel Monteiro | Árvore, CRUD, disco, alocação contígua/indexada, mapa, shell | `fs.py`, `disk.py`, `allocation.py`, `main.py`, `diagnostico.mapa_disco` |
| Giovanna Costa | Alocação encadeada | `allocation.Encadeada` |
| Giovanna Costa | Relatório de fragmentação | `diagnostico.relatorio_fragmentacao` |
| Giovanna Costa | Compactação | `diagnostico.compactar` |
| Miguel Monteiro | Fila de E/S e escalonadores de HDD (FCFS, SSTF, SCAN, C-SCAN) | `io_request.py`, `scheduler.py`, comandos `disk_sched`/`io_queue` em `main.py` |
| Giovanna Costa | SSD: páginas, GC, TRIM e wear leveling | `ssd.py` |
| Giovanna Costa | RAID 5: stripes, paridade XOR, falha e recuperação | `raid.py` |
| Miguel Monteiro | ACL, criptografia, anti-vírus | `acl.py`, `cripto.py`, `antivirus.py` |

## Fluxo com Git
1. `main` fica sempre funcionando.
2. Cada pessoa trabalha na sua branch (`miguel/estapa2-escalonamento`, `giovanna/etapa2-raid`, ...).
3. Commits pequenos e com mensagem clara (ex.: `feat: integra raid ao sistema de arquivos`).
4. A outra pessoa revisa e faz o merge.