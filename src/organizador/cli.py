"""Comandos da CLI `organizador`."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.progress import track
from rich.syntax import Syntax
from rich.table import Table

from .archiver import ARCHIVE_DIR, Format, archive_old, plan_archive
from .config import Settings, config_path, dump_toml, load_settings, write_default
from .deduplicator import find_duplicates, reclaimable, trash_duplicates
from .history import History, undo_batch
from .interactive import review_duplicates
from .models import DuplicateGroup, ScanResult
from .organizer import By, execute_moves, plan_moves
from .reporter import build_report, write_html, write_json
from .scanner import human_size, parse_size, scan

app = typer.Typer(help="Análise, limpeza e organização inteligente de arquivos.", no_args_is_help=True)
config_app = typer.Typer(help="Gerencia o arquivo ~/.organizador.toml.", no_args_is_help=True)
app.add_typer(config_app, name="config")
console = Console()

PathArg = Annotated[Path, typer.Argument(exists=True, file_okay=False, resolve_path=True, help="Pasta alvo.")]
ExtOpt = Annotated[list[str] | None, typer.Option("--ext", "-e", help="Só estas extensões (repetível).")]
MinOpt = Annotated[str | None, typer.Option("--min-size", help="Tamanho mínimo, ex.: 10KB, 5MB.")]
MaxOpt = Annotated[str | None, typer.Option("--max-size", help="Tamanho máximo, ex.: 1GB.")]
IgnoreOpt = Annotated[list[str] | None, typer.Option("--ignore", help="Padrão extra a ignorar (repetível).")]
ExecOpt = Annotated[bool, typer.Option("--execute/--dry-run", help="Simula (padrão) ou aplica de fato.")]
KeepNewestOpt = Annotated[bool, typer.Option("--keep-newest", help="Mantém o mais novo em vez do mais antigo.")]
MAX_ROWS = 200


def _fail(msg: str) -> typer.Exit:
    console.print(f"[red]Erro:[/] {escape(msg)}")  # mensagens do pydantic têm [colchetes]
    return typer.Exit(1)


def _settings() -> Settings:
    try:
        return load_settings()
    except ValueError as e:
        raise _fail(str(e)) from e


def _scan(s: Settings, path: Path, ext: list[str] | None, min_size: str | None, max_size: str | None,
          ignore: list[str] | None = None, older_than: float | None = None) -> ScanResult:
    try:
        low = parse_size(min_size) if min_size else s.min_size
        high = parse_size(max_size) if max_size else s.max_size
    except ValueError as e:
        raise _fail(str(e)) from e
    with console.status("Varrendo arquivos...") as status:
        result = scan(path, extensions=ext, min_size=low, max_size=high, older_than_days=older_than,
                      ignore=[*s.ignore, *(ignore or [])], categories=s.categories,
                      on_progress=lambda n: status.update(f"Varrendo arquivos... {n} encontrados"))
    if result.errors:
        console.print(f"[yellow]{len(result.errors)} itens inacessíveis ignorados[/] (ex.: {result.errors[0]})")
    return result


def _find(path: Path, ext: list[str] | None, min_size: str | None, max_size: str | None,
          keep_newest: bool) -> list[DuplicateGroup]:
    files = _scan(_settings(), path, ext, min_size, max_size).files
    with console.status(f"Comparando {len(files)} arquivos (tamanho → hash parcial → SHA-256)..."):
        return find_duplicates(files, keep_newest=keep_newest)


def _rel(p: Path | str, root: Path) -> str:
    try:
        return str(Path(p).relative_to(root))
    except ValueError:
        return str(p)


@app.command("scan")
def scan_cmd(
    path: PathArg,
    ext: ExtOpt = None,
    min_size: MinOpt = None,
    max_size: MaxOpt = None,
    ignore: IgnoreOpt = None,
    old_days: Annotated[int, typer.Option(help="Idade (dias) para considerar arquivo antigo.")] = 365,
    export_json: Annotated[Path | None, typer.Option("--export-json", help="Salva relatório JSON.")] = None,
    export_html: Annotated[Path | None, typer.Option("--export-html", help="Salva relatório HTML.")] = None,
) -> None:
    """Analisa a pasta e mostra um painel com o resumo."""
    result = _scan(_settings(), path, ext, min_size, max_size, ignore)
    r = build_report(path, result, old_days=old_days, top=10)
    console.print(Panel(f"[bold]{r.total_files}[/] arquivos · [bold]{human_size(r.total_size)}[/]",
                        title=str(path), expand=False))

    t = Table(title="Espaço por categoria")
    for col in ("Categoria", "Arquivos", "Tamanho"):
        t.add_column(col, justify="left" if col == "Categoria" else "right")
    for cat, c in r.by_category.items():
        t.add_row(cat, str(c["count"]), human_size(c["size"]))
    console.print(t)

    t = Table(title="Maiores arquivos")
    t.add_column("Arquivo")
    t.add_column("Tamanho", justify="right")
    for f in r.largest:
        t.add_row(_rel(f["path"], path), human_size(f["size"]))
    console.print(t)

    console.print(f"[yellow]Antigos (> {old_days} dias):[/] {len(r.old)}   [yellow]Vazios:[/] {len(r.empty)}")
    for f in (r.old[:5] + r.empty[:5]):
        console.print(f"  · {_rel(f['path'], path)}  [dim]{f['modified']}[/]")

    if export_json or export_html:
        with console.status("Procurando duplicados para o relatório..."):
            report = build_report(path, result, find_duplicates(result.files), old_days)
        if export_json:
            console.print(f"[green]JSON salvo em[/] {write_json(report, export_json)}")
        if export_html:
            console.print(f"[green]HTML salvo em[/] {write_html(report, export_html)}")


@app.command("duplicates")
def duplicates_cmd(
    path: PathArg,
    ext: ExtOpt = None,
    min_size: MinOpt = None,
    max_size: MaxOpt = None,
    delete: Annotated[bool, typer.Option("--delete", "--delete-duplicates",
                                         help="Envia as cópias para a lixeira.")] = False,
    keep_newest: KeepNewestOpt = False,
    execute: ExecOpt = False,
    interactive: Annotated[bool, typer.Option("--interactive", "-i", help="Revisa grupo a grupo.")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Não pede confirmação.")] = False,
) -> None:
    """Encontra arquivos idênticos e, opcionalmente, manda as cópias para a lixeira."""
    groups = _find(path, ext, min_size, max_size, keep_newest)
    if not groups:
        console.print("[green]Nenhum arquivo duplicado encontrado.[/]")
        return
    if interactive:
        review_duplicates(groups, console)
        return

    t = Table(title=f"{len(groups)} grupos de duplicados")
    for col in ("#", "Arquivo", "Tamanho", "Ação"):
        t.add_column(col, justify="right" if col in ("#", "Tamanho") else "left")
    for i, g in enumerate(groups[:MAX_ROWS], 1):
        for j, f in enumerate(g.files):
            t.add_row(str(i) if j == 0 else "", _rel(f.path, path), human_size(f.size),
                      "[green]manter[/]" if j == 0 else "[red]lixeira[/]", end_section=j == len(g.files) - 1)
    console.print(t)
    total = sum(len(g.copies) for g in groups)
    console.print(f"Espaço recuperável: [bold]{human_size(reclaimable(groups))}[/] em {total} cópias.")

    if not delete:
        return
    if not execute:
        console.print("[yellow]Simulação:[/] nada foi alterado. Use [bold]--delete --execute[/] para aplicar.")
        return
    if not yes and not typer.confirm(f"Enviar {total} cópias para a lixeira?"):
        raise typer.Abort()
    console.print(f"[green]{len(trash_duplicates(groups))} arquivos enviados para a lixeira.[/]")


@app.command("interactive")
def interactive_cmd(
    path: PathArg,
    ext: ExtOpt = None,
    min_size: MinOpt = None,
    max_size: MaxOpt = None,
    keep_newest: KeepNewestOpt = False,
) -> None:
    """Revisa duplicados um a um, escolhendo qual manter (o resto vai para a lixeira)."""
    groups = _find(path, ext, min_size, max_size, keep_newest)
    if not groups:
        console.print("[green]Nenhum arquivo duplicado encontrado.[/]")
        return
    review_duplicates(groups, console)


@app.command("organize")
def organize_cmd(
    path: PathArg,
    by: Annotated[By, typer.Option("--by", help="Estratégia: category, date (AAAA/MM), ext ou regex.")] = By.category,
    execute: ExecOpt = False,
    clean_empty: Annotated[bool, typer.Option("--clean-empty/--keep-empty",
                                              help="Remove pastas que ficarem vazias (padrão).")] = True,
    ext: ExtOpt = None,
    min_size: MinOpt = None,
    max_size: MaxOpt = None,
) -> None:
    """Organiza arquivos em subpastas. Simula por padrão."""
    s = _settings()
    if by is By.regex and not s.regex_rules:
        raise _fail(f"nenhuma [[regex_rules]] definida em {config_path()}")
    moves = plan_moves(path, _scan(s, path, ext, min_size, max_size).files, by, s.regex_rules)
    if not moves:
        console.print("[green]Nada a mover: a pasta já está organizada.[/]")
        return

    t = Table(title=f"{len(moves)} arquivos {'serão movidos' if execute else 'seriam movidos (simulação)'}")
    t.add_column("Origem")
    t.add_column("Destino", style="cyan")
    for op in moves[:MAX_ROWS]:
        t.add_row(_rel(op.src, path), _rel(op.dst, path))
    console.print(t)
    if len(moves) > MAX_ROWS:
        console.print(f"[dim]... e mais {len(moves) - MAX_ROWS}[/]")

    if not execute:
        console.print("[yellow]Modo simulação.[/] Rode com [bold]--execute[/] para mover de fato.")
        return
    with History() as h:
        batch = execute_moves(moves, path, h, clean_empty=clean_empty,
                              wrap=lambda it: track(it, description="Movendo...", total=len(moves)))
    console.print(f"[green]{len(moves)} arquivos movidos (lote {batch}).[/] "
                  "Use [bold]organizador undo[/] para desfazer.")


@app.command("archive")
def archive_cmd(
    path: PathArg,
    older_than: Annotated[int, typer.Option("--older-than", min=1, help="Compacta o que não muda há N dias.")],
    fmt: Annotated[Format, typer.Option("--format", help="Formato do pacote.")] = Format.zip,
    execute: ExecOpt = False,
) -> None:
    """Compacta arquivos antigos em _arquivo/AAAA.zip (ou .tar.gz). Simula por padrão."""
    files = _scan(_settings(), path, None, None, None, ignore=[ARCHIVE_DIR], older_than=older_than).files
    plan = plan_archive(files)
    if not plan:
        console.print(f"[green]Nenhum arquivo sem modificação há mais de {older_than} dias.[/]")
        return
    t = Table(title="Pacotes" + ("" if execute else " (simulação)"))
    for col in ("Pacote", "Arquivos", "Tamanho"):
        t.add_column(col, justify="left" if col == "Pacote" else "right")
    for year, fs in plan.items():
        t.add_row(f"{ARCHIVE_DIR}/{year}.{fmt.value}", str(len(fs)), human_size(sum(f.size for f in fs)))
    console.print(t)
    if not execute:
        console.print("[yellow]Modo simulação.[/] Rode com [bold]--execute[/] para compactar.")
        return
    try:
        with console.status("Compactando e verificando integridade..."):
            created = archive_old(path, plan, fmt)
    except (RuntimeError, OSError) as e:
        raise _fail(str(e)) from e
    console.print(f"[green]{len(created)} pacotes criados;[/] originais enviados para a lixeira.")


@app.command("undo")
def undo_cmd(batch_id: Annotated[int | None, typer.Option("--batch-id", help="Lote específico.")] = None) -> None:
    """Desfaz a última organização (ou um lote), conferindo o SHA-256 de cada arquivo."""
    with History() as h:
        result = undo_batch(h, batch_id)
    if result is None:
        console.print("[yellow]Nada para desfazer.[/]")
        return
    console.print(f"[green]Lote {result.batch_id}: {len(result.restored)} arquivos restaurados.[/]")
    for op, why in result.skipped:
        console.print(f"[red]Ignorado[/] {op.dst} -> {op.src}: {why}")


@app.command("history")
def history_cmd(batch_id: Annotated[int | None, typer.Option("--batch-id", help="Detalha um lote.")] = None) -> None:
    """Lista as execuções registradas ou detalha um lote."""
    with History() as h:
        if batch_id is None:
            t = Table(title="Histórico")
            for col in ("Lote", "Data", "Tipo", "Pasta", "Movimentos", "Status"):
                t.add_column(col)
            for b, count in h.list_batches():
                t.add_row(str(b.id), b.created_at, b.kind, str(b.root), str(count),
                          f"desfeito {b.undone_at}" if b.undone_at else "[green]ativo[/]")
            console.print(t)
            return
        batch = h.get_batch(batch_id)
    if batch is None:
        raise _fail(f"lote {batch_id} não existe")
    t = Table(title=f"Lote {batch.id} · {batch.created_at} · {batch.root}")
    t.add_column("Origem")
    t.add_column("Destino", style="cyan")
    t.add_column("SHA-256", style="dim")
    for op in batch.moves:
        t.add_row(_rel(op.src, batch.root), _rel(op.dst, batch.root), op.sha256[:12])
    console.print(t)


@config_app.command("init")
def config_init(force: Annotated[bool, typer.Option("--force", help="Sobrescreve o existente.")] = False) -> None:
    """Cria o arquivo de configuração com os padrões."""
    p = config_path()
    if p.exists() and not force:
        console.print(f"[yellow]{p} já existe.[/] Use --force para recriar.")
        return
    console.print(f"[green]Configuração criada em[/] {write_default(p)}")


@config_app.command("show")
def config_show() -> None:
    """Exibe as regras ativas."""
    p = config_path()
    source = str(p) if p.exists() else "padrões embutidos (sem arquivo)"
    console.print(Panel(Syntax(dump_toml(_settings()), "toml"), title=source))


@config_app.command("validate")
def config_validate() -> None:
    """Valida a sintaxe e as regras do TOML."""
    p = config_path()
    if not p.exists():
        console.print(f"[yellow]{p} não existe;[/] os padrões embutidos estão em uso.")
        return
    _settings()
    console.print(f"[green]{p} é válido.[/]")
