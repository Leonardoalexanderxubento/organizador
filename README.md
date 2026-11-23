# organizador

CLI em Python para **analisar, limpar e organizar** arquivos: resumo por categoria, detecção de duplicados
via SHA-256, organização por categoria ou data com simulação por padrão, desfazer, e relatórios JSON/HTML.

## Instalação

Requer Python 3.11+.

```bash
git clone https://github.com/Leonardoalexanderxubento/organizador
cd organizador
python -m venv .venv
# Windows: .venv\Scripts\activate   |   Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
organizador --help
```

## Comandos

### `organizador scan <caminho>`
Mostra total de arquivos, espaço por categoria, maiores arquivos e arquivos antigos/vazios.

```bash
organizador scan ~/Downloads
organizador scan ~/Downloads --ext pdf --ext docx --min-size 1MB
organizador scan ~/Downloads --export-html relatorio.html --export-json relatorio.json
```

| Flag | Descrição |
|------|-----------|
| `--ext`, `-e` | Só considera estas extensões (repita a flag para várias). |
| `--min-size` / `--max-size` | Limites de tamanho: `500KB`, `10MB`, `1.5GB`. |
| `--old-days` | Idade em dias para um arquivo contar como antigo (padrão 365). |
| `--export-json` | Salva relatório completo em JSON (inclui duplicados). |
| `--export-html` | Salva relatório visual em HTML: gráfico SVG por categoria, top 20 maiores, duplicados e vazios. |

### `organizador duplicates <caminho>`
Agrupa por tamanho e depois compara o SHA-256 (lido em blocos de 1 MB, sem estourar a memória).
Arquivos vazios são ignorados (não liberam espaço).

```bash
organizador duplicates ~/Fotos
organizador duplicates ~/Fotos --delete-duplicates        # pede confirmação
organizador duplicates ~/Fotos --delete-duplicates --yes  # sem confirmação
```

| Flag | Descrição |
|------|-----------|
| `--delete-duplicates` | Apaga as cópias, **mantendo sempre a mais antiga** de cada grupo. |
| `--yes`, `-y` | Não pede confirmação. |
| `--ext`, `--min-size`, `--max-size` | Mesmos filtros do `scan`. |

### `organizador organize <caminho>`
Move os arquivos para subpastas de `<caminho>`. **Por padrão só simula** e mostra a tabela do que seria movido.

```bash
organizador organize ~/Downloads                         # simulação (--dry-run)
organizador organize ~/Downloads --execute               # por categoria
organizador organize ~/Downloads --by date --execute     # em Ano/Mês (data de modificação)
```

| Flag | Descrição |
|------|-----------|
| `--by category` | Imagens, Documentos, Vídeos, Áudios, Compactados, Código, Outros (padrão). |
| `--by date` | Pastas `AAAA/MM`. |
| `--dry-run` / `--execute` | Simula (padrão) ou move de fato. |
| `--ext`, `--min-size`, `--max-size` | Organiza só os arquivos filtrados. |

Conflitos de nome viram `arquivo (1).pdf`, `arquivo (2).pdf`… Nenhum arquivo é sobrescrito.
Cada movimento é gravado no histórico SQLite (`~/.organizador_history.sqlite`).

### `organizador undo`
Devolve todos os arquivos da última execução de `organize --execute` aos caminhos originais e remove as
pastas que ficarem vazias. Se o caminho original já estiver ocupado, o arquivo é mantido onde está e listado.

### `organizador config`
Cria (se não existir) e exibe `~/.organizador.toml`. Use `--reset` para recriar com os padrões.

```toml
ignore = [".git", "node_modules", "__pycache__", ".venv"]

[categories]
"Imagens" = [".jpg", ".png"]
"Planilhas" = [".xlsx", ".csv"]
```

As categorias do arquivo **substituem** as padrão; extensões não listadas vão para `Outros`.

Variáveis de ambiente `ORGANIZADOR_CONFIG` e `ORGANIZADOR_HISTORY` trocam o caminho desses arquivos.

## Testar na prática

```bash
python scripts/gerar_massa_teste.py massa_teste
organizador scan massa_teste --export-html relatorio.html
organizador duplicates massa_teste
organizador organize massa_teste
organizador organize massa_teste --execute
organizador undo
```

## Testes

```bash
pytest
```

## Estrutura

```
src/organizador/
  cli.py           comandos Typer + saída Rich
  scanner.py       varredura recursiva com filtros
  deduplicator.py  tamanho -> SHA-256 em blocos
  organizer.py     plano de movimentação e execução segura
  history.py       histórico SQLite e undo
  reporter.py      relatórios JSON e HTML (SVG puro)
  config.py        ~/.organizador.toml
```
