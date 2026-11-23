# Arquitetura

```
src/organizador/
  cli.py           comandos Typer, saída Rich (sem lógica de negócio)
  config.py        Settings (Pydantic) <- ~/.organizador.toml, com padrões embutidos
  models.py        FileMetadata, ScanResult, DuplicateGroup, MoveOperation, ExecutionBatch, ScanReport
  scanner.py       os.walk sem seguir links, .organizadorignore, filtros; erros coletados
  deduplicator.py  3 estágios + lixeira (send2trash)
  organizer.py     plano de movimentos + execução transacional
  archiver.py      pacotes zip/tar.gz por ano com verificação de integridade
  history.py       SQLite (lotes, movimentos, hash) + undo verificado
  reporter.py      ScanReport -> JSON / HTML com SVG
  interactive.py   revisão de duplicados com prompts Rich
```

## Fluxo de dados

```mermaid
flowchart LR
    CFG[~/.organizador.toml] -->|Settings| CLI
    IGN[.organizadorignore] --> SC
    CLI --> SC[scanner.scan]
    SC -->|ScanResult: files + errors| D[deduplicator]
    SC --> O[organizer.plan_moves]
    SC --> A[archiver.plan_archive]
    SC --> R[reporter.build_report]
    D -->|DuplicateGroup| R
    D -->|DuplicateGroup| I[interactive]
    I -->|send2trash| LX[(Lixeira)]
    D -->|send2trash| LX
    O -->|MoveOperation| X[organizer.execute_moves]
    X -->|lote + sha256| H[(history.db)]
    H --> U[history.undo_batch]
    A -->|zip/tar.gz verificado| LX
    R --> J[relatorio.json]
    R --> HT[relatorio.html]
```

## Algoritmo de deduplicação

```mermaid
flowchart TD
    F[Arquivos varridos] --> S1{Estágio 1<br/>agrupar por tamanho}
    S1 -->|tamanho único ou 0 bytes| X1[descartado]
    S1 -->|mesmo tamanho| B{> 64 KB?}
    B -->|não| S3
    B -->|sim| S2{Estágio 2<br/>SHA-256 dos primeiros<br/>e últimos 8 KB}
    S2 -->|parcial único| X2[descartado]
    S2 -->|parcial igual| S3{Estágio 3<br/>SHA-256 completo<br/>em blocos de 64 KB}
    S3 -->|hash único| X3[descartado]
    S3 -->|hash igual| G[DuplicateGroup<br/>ordenado por mtime]
```

Os estágios 2 e 3 rodam num `ThreadPoolExecutor`, porque o tempo vai em leitura de disco. Um arquivo ilegível
(sem permissão, removido durante a varredura) é descartado do grupo sem interromper o resto.
Arquivos vazios não entram, porque são todos "iguais" e apagá-los não libera espaço.

## Organização transacional e rollback

```mermaid
sequenceDiagram
    participant CLI
    participant Org as organizer
    participant H as history.db
    CLI->>Org: execute_moves(plano)
    Org->>H: start_batch
    loop cada arquivo
        Org->>Org: sha256(origem)
        Org->>Org: shutil.move (nunca sobrescreve)
        Org->>H: record(origem, destino, hash) + commit
    end
    alt falha no meio
        Org->>Org: devolve os já movidos
        Org->>H: delete_batch
    else sucesso
        Org->>Org: remove pastas que ficaram vazias
    end
    CLI->>H: undo_batch
    H-->>CLI: movimentos do lote
    Note over CLI,H: só devolve se o hash do destino conferir<br/>e o caminho original estiver livre
```

## Decisões

**Segurança**
- **Nada é apagado de vez.** Duplicados e originais compactados vão para a lixeira (`send2trash`).
- **Links simbólicos não são seguidos**: arquivos-link são ignorados e `os.walk(followlinks=False)` evita loops.
- **Junções do Windows não são detectadas no Python 3.11.** Uma junção circular pode ser percorrida.
- **Histórico e config nunca são movidos**, mesmo ao organizar a pasta pessoal.
- **Caminhos `folder` das regras regex são validados** (relativos, sem `..`) para nada sair da pasta alvo.

**Escopo**
- **`.organizadorignore` é um subconjunto do `.gitignore`**, sem negação `!` e sem `**`.
