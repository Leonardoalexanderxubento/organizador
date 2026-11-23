# organizador

CLI em Python para **analisar, limpar e organizar** arquivos:
- painel por categoria;
- duplicados em 3 estágios (tamanho → hash parcial → SHA-256);
- organização por categoria, data, extensão ou regex;
- compactação de arquivos antigos;
- histórico com rollback verificado por hash;
- relatórios JSON/HTML.

Nada é apagado de vez: duplicados e originais compactados vão para a **lixeira do sistema**.

## Guia rápido

Requer Python 3.11+.

```bash
git clone https://github.com/Leonardoalexanderxubento/organizador
cd organizador
python -m venv .venv
# Windows: .venv\Scripts\activate   |   Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"

organizador scan ~/Downloads
organizador organize ~/Downloads            # só mostra o que faria
organizador organize ~/Downloads --execute  # aplica
organizador undo                            # volta tudo
```

Todo comando que altera o disco **simula por padrão** (`--dry-run`) e só aplica com `--execute`.

## Comandos

### `scan <caminho>`
Painel com total de arquivos, tamanho, distribuição por categoria, maiores, mais antigos e vazios.

```bash
organizador scan ~/Downloads --ext pdf --ext docx --min-size 1MB --ignore "*.tmp"
organizador scan ~/Downloads --export-html relatorio.html --export-json relatorio.json
```

| Flag | Descrição |
|------|-----------|
| `--ext`, `-e` | Só estas extensões (repetível). |
| `--min-size` / `--max-size` | Limites: `500KB`, `10MB`, `1.5GB`. Sem a flag, vale o limite do config. |
| `--ignore` | Padrão extra a ignorar, estilo `.gitignore` (repetível). |
| `--old-days` | Idade em dias para "antigo" (padrão 365). |
| `--export-json` | Relatório completo em JSON. |
| `--export-html` | HTML autossuficiente (sem internet), tema claro/escuro. Inclui gráfico SVG por categoria, linha do tempo, top 20 maiores, duplicados e espaço recuperável. |

### `duplicates <caminho>`

```bash
organizador duplicates ~/Fotos                                   # lista grupos e espaço desperdiçado
organizador duplicates ~/Fotos --delete                          # simula
organizador duplicates ~/Fotos --delete --execute                # cópias -> lixeira (pede confirmação)
organizador duplicates ~/Fotos --delete --execute --keep-newest -y
organizador duplicates ~/Fotos --interactive                     # revisa grupo a grupo
```

| Flag | Descrição |
|------|-----------|
| `--delete` (`--delete-duplicates`) | Envia as cópias para a lixeira, mantendo a mais antiga. |
| `--keep-newest` | Mantém a mais nova. |
| `--dry-run` / `--execute` | Simula (padrão) ou aplica. |
| `--yes`, `-y` | Não pede confirmação. |
| `--interactive`, `-i` | Mesmo que o comando `interactive`. |

### `interactive <caminho>`
Mostra cada grupo de duplicados numa tabela. Para cada um, você digita:
- o **número do arquivo a manter** (os outros vão para a lixeira);
- `s` para pular o grupo;
- `q` para sair.

### `organize <caminho>`

```bash
organizador organize ~/Downloads --by category --execute   # Imagens/, Documentos/, Vídeos/...
organizador organize ~/Downloads --by date --execute       # 2024/05/
organizador organize ~/Downloads --by ext --execute        # PDF/, JPG/, SEM_EXTENSAO/
organizador organize ~/Downloads --by regex --execute      # regras do config
```

| Flag | Descrição |
|------|-----------|
| `--by` | `category` (padrão), `date` (AAAA/MM), `ext` ou `regex`. |
| `--dry-run` / `--execute` | Simula (padrão) ou move. |
| `--clean-empty` / `--keep-empty` | Remove as pastas que ficarem vazias (padrão) ou as mantém. Pastas que já estavam vazias não são tocadas. |
| `--ext`, `--min-size`, `--max-size` | Organiza só os arquivos filtrados. |

Comportamentos de segurança:
- Conflitos de nome viram `arquivo (1).pdf`, `arquivo (2).pdf`… Nenhum arquivo é sobrescrito.
- A execução é transacional: se algo falhar no meio, os arquivos já movidos voltam.
- O SHA-256 de cada arquivo é gravado no histórico.

### `archive <caminho> --older-than <dias>`
Compacta o que não é modificado há N dias em `_arquivo/AAAA.zip` (ou `--format tar.gz`), um pacote por ano.
O pacote é relido e cada arquivo conferido por SHA-256. Os originais só vão para a lixeira depois disso.

```bash
organizador archive ~/Documentos --older-than 730
organizador archive ~/Documentos --older-than 730 --format tar.gz --execute
```

### `undo [--batch-id ID]`
Desfaz a última organização (ou um lote específico) e remove as pastas que ficarem vazias.
Um arquivo **não** é devolvido, e aparece na lista de ignorados, nestes casos:
- foi alterado depois da organização (o hash não confere);
- o caminho original já está ocupado;
- o arquivo sumiu do destino.

### `history [--batch-id ID]`
Lista todos os lotes (data, pasta, quantidade, se foi desfeito) ou detalha um lote com origem, destino e hash.

### `config init | show | validate`

```bash
organizador config init      # cria ~/.organizador.toml (use --force para recriar)
organizador config show      # regras ativas (arquivo ou padrões embutidos)
organizador config validate  # aponta erros de sintaxe ou regras inválidas
```

```toml
ignore = [".git", "node_modules", "*.tmp", "build/"]
min_size = "1KB"        # opcional
max_size = "5GB"        # opcional

[categories]
Imagens = [".jpg", ".png"]
Planilhas = [".xlsx", ".csv"]

[[regex_rules]]
pattern = "(?i)^nota[_ ]?fiscal"
folder = "Financeiro/Notas"

[[regex_rules]]
pattern = "^IMG_\\d{8}"
folder = "Fotos/Celular"
```

Como as regras funcionam:
- As categorias do arquivo **substituem** as padrão. Extensões não listadas vão para `Outros`.
- As `regex_rules` são aplicadas por `organize --by regex`, na ordem, sobre o nome do arquivo. A primeira que casar vence. Arquivos sem regra ficam onde estão.
- `folder` precisa ser um caminho relativo, sem `..`.

### `.organizadorignore`
Arquivo opcional na raiz da pasta analisada. Uma regra por linha, estilo `.gitignore`: `*.log`, `build/`
(só pastas), `docs/rascunho.txt`. Linhas com `#` são comentários.

### Arquivos do programa

| O quê | Onde | Variável para trocar |
|-------|------|----------------------|
| Configuração | `~/.organizador.toml` | `ORGANIZADOR_CONFIG` |
| Histórico | `~/.local/share/organizador/history.db` | `ORGANIZADOR_HISTORY` |

## Testar na prática

```bash
python scripts/gerar_massa_teste.py massa_teste
organizador scan massa_teste --export-html relatorio.html
organizador interactive massa_teste
organizador organize massa_teste --execute
organizador history
organizador undo

python scripts/benchmark.py --arquivos 2500   # mede scan/duplicates e valida organize + undo
```

## Desenvolvimento

```bash
ruff check .
mypy src
pytest --cov=organizador --cov-report=term-missing
```

Veja [ARCHITECTURE.md](ARCHITECTURE.md) para o fluxo de dados e o algoritmo de deduplicação.
