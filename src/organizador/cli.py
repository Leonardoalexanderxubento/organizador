"""Comandos da CLI `organizador`."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import track
from rich.syntax import Syntax
from rich.table import Table

from . import config as cfg
from .deduplicator import delete_duplicates, find_duplicates, reclaimable
from .history import History, undo_last
from .organizer import By, execute_moves, plan_moves
from .reporter import build_report, summarize, write_html, write_json
from .scanner import FileInfo, human_size, parse_size, scan

app = typer.Typer(help="Análise, limpeza e organização inteligente de arquivos.", no_args_is_help=True)
console = Console()

PathArg = Annotated[Path, typer.Argument(exists=True, file_okay=False, resolve_path=True, help="Pasta alvo.")]
ExtOpt = Annotated[Optional[list[str]], typer.Option("--ext", "-e", help="Só estas extensões (repetível).")]
MinOpt = Annotated[str, typer.Option("--min-size", help="Tamanho mínimo, ex.: 10KB, 5MB.")]
MaxOpt = Annotated[Optional[str], typer.Option("--max-size", help="Tamanho máximo, ex.: 1GB.")]
MAX_ROWS = 200


def _scan(path: Path, ext: list[str] | None, min_size: str, max_size: str | None) -> list[FileInfo]:
    try:
        categories, ignore = cfg.load_config()
        low, high = parse_size(min_size), parse_size(max_size) if max_size else None
    except ValueError as e:
        console.print(f"[red]Erro:[/] {e}")
        raise typer.Exit(1) from e
    with console.status("Varrendo arquivos..."):
        return scan(path, extensions=ext, min_size=low, max_size=high, ignore=ignore, categories=categories)


def _rel(p: Path | str, root: Path) -> str:
    try:
        return str(Path(p).relative_to(root))
    except ValueError:
        return str(p)


@app.command("scan")
def scan_cmd(
    path: PathArg,
    ext: ExtOpt = None,
    min_size: MinOpt = "0",
    max_size: MaxOpt = None,
    old_days: Annotated[int, typer.Option(help="Idade (dias) para considerar arquivo antigo.")] = 365,
    export_json: Annotated[Optional[Path], typer.Option("--export-json", help="Salva relatório JSON.")] = None,
    export_html: Annotated[Optional[Path], typer.Option("--export-html", help="Salva relatório HTML.")] = None,
) -> None:
    """Analisa a pasta e mostra um resumo."""
    files = _scan(path, ext, min_size, max_size)
    s = summarize(files, old_days, top=10)
    console.print(Panel(f"[bold]{s['total_files']}[/] arquivos · [bold]{human_size(s['total_size'])}[/]",
                        title=str(path), expand=False))

    t = Table(title="Espaço por categoria")
    for col in ("Categoria", "Arquivos", "Tamanho"):
        t.add_column(col, justify="left" if col == "Categoria" else "right")
    for cat, c in s["by_category"].items():
        t.add_row(cat, str(c["count"]), human_size(c["size"]))
    console.print(t)

    t = Table(title="Maiores arquivos")
    t.add_column("Arquivo")
    t.add_column("Tamanho", justify="right")
    for f in s["largest"]:
        t.add_row(_rel(f["path"], path), human_size(f["size"]))
    console.print(t)

    console.print(f"[yellow]Antigos (> {old_days} dias):[/] {len(s['old'])}   [yellow]Vazios:[/] {len(s['empty'])}")
    for f in (s["old"] + s["empty"])[:10]:
        console.print(f"  · {_rel(f['path'], path)}  [dim]{f['modified']}[/]")

    if export_json or export_html:
        with console.status("Procurando duplicados para o relatório..."):
            report = build_report(path, files, find_duplicates(files), old_days)
        if export_json:
            console.print(f"[green]JSON salvo em[/] {write_json(report, export_json)}")
        if export_html:
            console.print(f"[green]HTML salvo em[/] {write_html(report, export_html)}")


@app.command("duplicates")
def duplicates_cmd(
    path: PathArg,
    ext: ExtOpt = None,
    min_size: MinOpt = "0",
    max_size: MaxOpt = None,
    delete: Annotated[bool, typer.Option("--delete-duplicates", help="Apaga cópias, mantendo a mais antiga.")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Não pede confirmação.")] = False,
) -> None:
    """Encontra arquivos idênticos (SHA-256)."""
    files = _scan(path, ext, min_size, max_size)
    with console.status(f"Comparando {len(files)} arquivos..."):
        groups = find_duplicates(files)
    if not groups:
        console.print("[green]Nenhum arquivo duplicado encontrado.[/]")
        return

    t = Table(title=f"{len(groups)} grupos de duplicados")
    t.add_column("#", justify="right")
    t.add_column("Arquivo")
    t.add_column("Tamanho", justify="right")
    t.add_column("Ação")
    for i, g in enumerate(groups[:MAX_ROWS], 1):
        for j, f in enumerate(g):
            t.add_row(str(i) if j == 0 else "", _rel(f.path, path), human_size(f.size),
                      "[green]manter[/]" if j == 0 else "[red]apagar[/]", end_section=j == len(g) - 1)
    console.print(t)
    total = sum(len(g) - 1 for g in groups)
    console.print(f"Espaço recuperável: [bold]{human_size(reclaimable(groups))}[/] em {total} cópias.")

    if delete:
        if not yes and not typer.confirm(f"Apagar {total} cópias permanentemente?"):
            raise typer.Abort()
        removed = delete_duplicates(groups)
        console.print(f"[green]{len(removed)} arquivos apagados.[/]")


@app.command("organize")
def organize_cmd(
    path: PathArg,
    by: Annotated[By, typer.Option("--by", help="Organizar por categoria ou por data (Ano/Mês).")] = By.category,
    execute: Annotated[bool, typer.Option("--execute/--dry-run", help="Simula (padrão) ou move de fato.")] = False,
    ext: ExtOpt = None,
    min_size: MinOpt = "0",
    max_size: MaxOpt = None,
) -> None:
    """Organiza arquivos em subpastas. Simula por padrão."""
    moves = plan_moves(path, _scan(path, ext, min_size, max_size), by)
    if not moves:
        console.print("[green]Nada a mover: a pasta já está organizada.[/]")
        return

    t = Table(title=f"{len(moves)} arquivos {'serão movidos' if execute else 'seriam movidos (simulação)'}")
    t.add_column("Origem")
    t.add_column("Destino", style="cyan")
    for src, dst in moves[:MAX_ROWS]:
        t.add_row(_rel(src, path), _rel(dst, path))
    console.print(t)
    if len(moves) > MAX_ROWS:
        console.print(f"[dim]... e mais {len(moves) - MAX_ROWS}[/]")

    if not execute:
        console.print("[yellow]Modo simulação.[/] Rode com [bold]--execute[/] para mover de fato.")
        return
    with History() as h:
        execute_moves(moves, path, h, wrap=lambda it: track(it, description="Movendo...", total=len(moves)))
    console.print(f"[green]{len(moves)} arquivos movidos.[/] Use [bold]organizador undo[/] para desfazer.")


@app.command("undo")
def undo_cmd() -> None:
    """Desfaz a última organização executada."""
    with History() as h:
        result = undo_last(h)
    if result is None:
        console.print("[yellow]Nenhuma organização no histórico.[/]")
        return
    console.print(f"[green]{len(result.restored)} arquivos restaurados.[/]")
    for (src, dst), why in result.skipped:
        console.print(f"[red]Ignorado[/] {dst} -> {src}: {why}")


@app.command("config")
def config_cmd(
    reset: Annotated[bool, typer.Option("--reset", help="Recria o arquivo com os padrões.")] = False,
) -> None:
    """Cria (se não existir) e exibe ~/.organizador.toml."""
    p = cfg.config_path()
    if reset or not p.exists():
        cfg.write_default(p)
        console.print(f"[green]Arquivo criado em[/] {p}")
    console.print(Panel(Syntax(p.read_text(encoding="utf-8"), "toml"), title=str(p)))
