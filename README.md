# Simulador de Sistema de Arquivos

Simulador didático de Sistemas Operacionais escrito em Python. O projeto reúne em uma interface de comandos:

- hierarquia de diretórios e operações CRUD;
- disco lógico por blocos e alocação contígua, encadeada e indexada;
- requisições de entrada e saída e escalonamento de disco HDD;
- armazenamento em SSD e RAID 5;
- autenticação, privilégios, ACL, criptografia didática e antivírus;
- área reservada contígua e memória virtual paginada.

O estado é mantido em memória enquanto o programa está em execução. Não há montagem de um sistema de arquivos real nem persistência em disco.

## Requisitos

- Python 3.8 ou superior.
- Nenhuma biblioteca externa.

## Instalação

### Windows

```powershell
git clone https://github.com/liito-0/simulador-fs.git
cd simulador-fs
py src/main.py --help
```

### Linux

```bash
git clone https://github.com/liito-0/simulador-fs.git
cd simulador-fs
python3 src/main.py --help
```

Não existe etapa de compilação ou instalação de dependências.

## Execução

### Shell interativo

Windows:

```powershell
py src/main.py
```

Linux:

```bash
python3 src/main.py
```

O shell inicia sem sessão autenticada. Use:

```text
login --user root --password root
help
```

### Roteiros disponíveis

```text
exemplos/demo.txt
exemplos/demo_io.txt
exemplos/demo_ssd.txt
exemplos/demo_raid.txt
exemplos/demo_seguranca.txt
exemplos/demo_acl_cripto_av.txt
exemplos/demo_memoria_reservada.txt
exemplos/demo_memoria_virtual.txt
```

Windows:

```powershell
py src/main.py --script exemplos/demo.txt
py src/main.py --script exemplos/demo_io.txt
py src/main.py --script exemplos/demo_ssd.txt
py src/main.py --script exemplos/demo_raid.txt
py src/main.py --script exemplos/demo_seguranca.txt
py src/main.py --script exemplos/demo_acl_cripto_av.txt
py src/main.py --script exemplos/demo_memoria_reservada.txt
```

Linux substitui `py` por `python3`.

Exemplo curto da memória virtual, com poucas molduras para forçar substituição:

```powershell
py src/main.py --ram 4112KB --reserved 4MB --page-size 4KB --replace lru --script exemplos/demo_memoria_virtual.txt
```

## Opções de inicialização

| Opção | Padrão | Descrição |
|---|---:|---|
| `--blocks N` | `16` | Blocos do disco lógico. |
| `--block-size N` | `4096` | Tamanho de cada bloco em bytes. |
| `--alloc contigua\|encadeada\|indexada` | `indexada` | Estratégia padrão de alocação. |
| `--device hdd\|ssd\|raid5` | `hdd` | Dispositivo usado pelas operações de E/S. |
| `--raid-disks N` | `3` | Quantidade de discos do RAID 5; mínimo 3. |
| `--ram N` | `8MB` | RAM total simulada. |
| `--reserved N` | `4MB` | Área reservada para processos críticos; deve ser maior que 1MB e menor que `--ram`. |
| `--page-size N` | `4KB` | Tamanho das páginas da memória virtual. |
| `--swap N` | `4x` a região dinâmica | Espaço virtual/swap. |
| `--replace lru\|second_chance\|fifo` | `lru` | Política de substituição de páginas. |
| `--report-every N` | `5` | Operações entre relatórios; `0` desativa. |
| `--root-password S` | `root` | Senha inicial do superusuário. |
| `--script caminho` | — | Executa um roteiro de comandos. |

## Arquitetura

### Visão geral

```text
main.py
  └── shell, análise de argumentos e controle de sessão
        ├── fs.py, acl.py
        │     árvore de arquivos e diretórios
        ├── disk.py, allocation.py, diagnostico.py
        │     blocos físicos, alocação e fragmentação
        ├── io_request.py, scheduler.py
        │     fila de E/S e algoritmos HDD
        ├── ssd.py
        │     páginas, TRIM, coleta de lixo e desgaste
        ├── raid.py
        │     distribuição por stripes e paridade XOR
        ├── seguranca.py, cripto.py, antivirus.py
        │     autenticação, privilégios, cifra e integridade
        └── memoria.py
              ├── mem_reservada.py: processos críticos
              └── mem_virtual.py: processos normais
```

### Sistema de arquivos e disco

`Disk` representa posições físicas em blocos. `FileSystem` mantém a árvore em memória e associa cada arquivo à estratégia e aos blocos usados. Diretórios têm modo `755`; arquivos têm modo `644`.

As estratégias suportadas são:

- contígua: requer um trecho único de blocos livres;
- encadeada: liga blocos de dados por referências;
- indexada: reserva um bloco i-node e blocos de dados.

`diagnostico.py` calcula mapa físico, fragmentação interna e externa e executa compactação.

### Entrada e saída

Toda criação, atualização ou leitura de arquivo pode gerar `IORequest` com operação `R` ou `W`, número do bloco e trilha correspondente.

- no HDD, a fila é processada por FCFS, SSTF, SCAN ou C-SCAN;
- no SSD, blocos lógicos são convertidos em páginas físicas; sobrescritas invalidam páginas e podem disparar coleta de lixo;
- no RAID 5, dados são distribuídos em stripes com paridade rotativa; a leitura reconstrói blocos por XOR após uma falha.

### Segurança

`Seguranca` controla identidade real e efetiva, login/logout, `sudo`, usuários, grupos e auditoria. Operações críticas exigem `MODO_KERNEL`.

As ACLs permitem leitura, escrita e execução por usuário, grupo e outros. `chmod` altera o modo octal e `chown` exige privilégio de kernel.

Criptografia e antivírus são componentes didáticos. Os dados não são persistidos e a cifra não deve ser considerada criptografia segura para produção.

### Memória reservada

`RegiaoReservada` contém o núcleo fixo e aloca processos críticos por first-fit em intervalos contíguos.

O estado pode ter espaço livre total suficiente, mas fragmentação externa impede alocação quando não existe um único bloco contíguo suficientemente grande. `memory_compact --reserved` move os processos para compactar essas lacunas.

### Memória virtual

`MemoriaVirtual` administra a região dinâmica da RAM.

- processos normais são divididos em páginas;
- uma tabela associa páginas lógicas a molduras físicas;
- a alocação física é por demanda;
- acessos ausentes geram `PAGE FAULT`;
- referências à memória podem levar páginas para o swap;
- substituição global suporta LRU, FIFO e Segunda Chance;
- páginas sujas são gravadas no swap; páginas limpas podem ser descartadas.

Os endereços físicos da região dinâmica começam após a área reservada.

## Comandos principais

Os comandos são texto sequencial. Argumentos são separados por espaços e opções usam `--opcao valor`.

### Arquivos e diretórios

| Comando | Finalidade |
|---|---|
| `mkdir [-p] <caminho>` | cria diretório |
| `create <caminho> --size N [--alloc ...] [--content "texto"]` | cria arquivo |
| `write_file <caminho> --size N\|--content "texto" [--alloc ...]` | cria arquivo e gera E/S |
| `ls [-l] [caminho]`, `cd`, `pwd`, `tree` | navega e lista |
| `read <arquivo>`, `read_file <arquivo>` | consulta metadados; leitura gera E/S |
| `update <arquivo> --size N` | altera tamanho |
| `mv <origem> <destino>`, `rm [-r] <caminho>` | move, renomeia ou remove |
| `alloc contigua\|encadeada\|indexada` | muda a alocação padrão |
| `fs_status [--details]`, `compact` | diagnostica ou compacta o disco |

### HDD

| Comando | Finalidade |
|---|---|
| `io_queue`, `io_clear` | lista ou limpa requisições |
| `disk_sched fcfs\|sstf\|scan\|cscan\|all [opções]` | calcula ordem e deslocamento |

Opções: `--head N`, `--dir up|down`, `--tracks 98,183,37`, `--max-track N`.

Exemplo do enunciado:

```text
disk_sched all --head 53 --max-track 199 --tracks 98,183,37,122,14
```

### SSD

| Comando | Finalidade |
|---|---|
| `ssd_write <pagina> <conteúdo>` | grava página lógica |
| `ssd_read <pagina>` | lê página lógica |
| `ssd_trim <pagina>` | invalida página |
| `ssd_status` | mostra páginas, leituras, escritas e GC |
| `ssd_wear` | mostra apagamentos por bloco |

### RAID 5

Os discos são numerados a partir de `1`.

| Comando | Finalidade |
|---|---|
| `raid_write <id> <conteúdo>` | distribui dados e paridade |
| `raid_read <id>` | lê ou reconstrói por XOR |
| `raid_fail <disco>`, `raid_recover <disco>` | falha ou recupera disco |
| `raid_status` | informa o estado do arranjo |

### Identidade, ACL e segurança

| Comando | Finalidade |
|---|---|
| `login --user N [--password S]`, `logout`, `whoami` | sessão e identidade |
| `sudo [--password S] <comando>` | elevação temporária para kernel |
| `users`, `groups`, `passwd`, `shadow`, `audit_log` | administração e auditoria |
| `useradd`, `userdel`, `usermod`, `groupadd`, `groupdel` | administração de contas |
| `chmod 000-777 <caminho>` | altera permissões rwx |
| `chown <usuário>[:grupo] <caminho>` | altera proprietário/grupo |
| `acl <caminho>`, `ls -l [caminho]` | consulta ACL |
| `encrypt_file <caminho> --key K` | criptografa arquivo |
| `decrypt_file <caminho> --key K` | descriptografa arquivo |
| `cat <caminho> [--key K]` | lê texto ou retorna ciphertext |
| `antivirus_scan [caminho]` | verifica integridade |
| `disk_tamper <caminho\|--block N> [--data TEXTO]` | simula adulteração |

### Memória

| Comando | Finalidade |
|---|---|
| `create_process --name N --size N --type critical\|normal` | cria processo |
| `terminate_process --name N` | encerra processo permitido |
| `ps` | lista processos, região e dono |
| `memory_status [--reserved\|--virtual]` | mostra estado da memória |
| `memory_compact --reserved` | compacta área reservada |
| `memory_report` | informa fragmentação externa e interna |
| `memory_policy [lru\|second_chance\|fifo]` | consulta ou troca substituição |
| `translate_address --process N --page K` | consulta tradução sem executar acesso |
| `execute_step --process N --instruction "LOAD_DATA Página 2"` | gera hit ou PAGE FAULT |

## Estados de falha

| Estado | Resultado |
|---|---|
| Caminho inválido, nome duplicado ou operação inválida | `FSError`; operação não é concluída |
| Disco sem espaço suficiente | `DiskError` |
| Alocação contígua sem trecho único | `DiskError` indicando fragmentação externa e compactação |
| SSD sem página livre ou capacidade lógica | `SSDError` |
| RAID com duas falhas simultâneas | dados indisponíveis; com uma falha, leitura pode usar XOR |
| Gravação no RAID com disco falho | operação bloqueada ou integrado com rollback |
| Login ou senha inválida | `AuthError` e evento de auditoria |
| Operação sem privilégio | `PrivilegeError` e evento negativo no log |
| ACL insuficiente | operação negada sem alterações parciais na árvore ou disco |
| Processos críticos sem bloco contíguo | `MemoriaError` por espaço insuficiente ou fragmentação externa |
| Página fora do endereço do processo | violação de segmentação |
| Swap sem slot livre | `MemoriaError` |
| Política ou instrução de memória inválida | `MemoriaError` |
| Comando desconhecido ou argumentos insuficientes | mensagem de ajuda/erro no shell |

## Limitações conhecidas

- todos os dados são simulados em memória e são perdidos ao encerrar o processo;
- o simulador não monta um sistema de arquivos real;
- o sistema não oferece persistência, rede ou concorrência real;
- a criptografia didática não é adequada para produção;
- o antivírus cobre somente o disco lógico e não inspeciona diretamente SSD ou RAID;
- o RAID 5 tolera apenas uma falha simultânea;
- a implementação do SSD é didática e não mede desgaste físico real;
- processos críticos usam alocação contígua;
- processos normais usam paginação e swap em memória virtual;
- o tamanho virtual pode ser configurado por `--swap`, cujo padrão é quatro vezes a região dinâmica;
- a sessão, os usuários e os arquivos não persistem entre execuções.

## Testes

Execute a suíte com o comando solicitado:

### Windows

```powershell
py -m unittest discover -s tests -v
```

### Linux

```bash
python3 -m unittest discover -s tests -v
```

Resultado da execução atual: **106 testes executados, todos aprovados**.

## Estrutura dos arquivos

```text
src/
  main.py          shell e análise da linha de comando
  fs.py            árvore, CRUD e integração de E/S
  disk.py          disco em blocos
  allocation.py    contígua, encadeada e indexada
  io_request.py    representação R/W
  scheduler.py     FCFS, SSTF, SCAN e C-SCAN
  diagnostico.py   mapa e fragmentação
  ssd.py           páginas, TRIM, GC e wear leveling
  raid.py          RAID 5 e paridade XOR
  seguranca.py     identidade, privilégios e auditoria
  acl.py           permissões rwx
  cripto.py        criptografia didática
  antivirus.py     integridade e assinatura
  processo.py      processo em memória
  mem_reservada.py alocação contígua crítica
  mem_virtual.py   paginação, swap e substituição
  memoria.py       gerenciador integrado das duas regiões

tests/             testes unitários e de integração
exemplos/          roteiros demonstrativos
```

## Equipe

- Miguel Monteiro
- Giovanna Costa
