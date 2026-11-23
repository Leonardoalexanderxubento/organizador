"""Revisão interativa de duplicados, grupo a grupo."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from .deduplicator import trash_copies
from .models import DuplicateGroup
from .scanner import human_size


def review_duplicates(groups: list[DuplicateGroup], console: Console) -> list[Path]:
    """Para cada grupo o usuário escolhe qual manter; os demais vão para a lixeira."""
    console.print(Panel(
        "Digite o [bold]número do arquivo a manter[/] (os outros vão para a lixeira), "
        "[bold]s[/] para pular o grupo ou [bold]q[/] para sair.", title="Revisão de duplicados"))
    trashed: list[Path] = []
    for i, group in enumerate(groups, 1):
        t = Table(title=f"Grupo {i}/{len(groups)} · {human_size(group.size)} cada · "
                        f"{human_size(group.wasted)} recuperáveis")
        t.add_column("#", justify="right")
        t.add_column("Arquivo")
        t.add_column("Modificado")
        for n, f in enumerate(group.files, 1):
            t.add_row(str(n), str(f.path), f"{datetime.fromtimestamp(f.mtime):%Y-%m-%d %H:%M}",
                      style="green" if n == 1 else None)
        console.print(t)
        choices = [str(n) for n in range(1, len(group.files) + 1)] + ["s", "q"]
        choice = Prompt.ask("Manter qual?", choices=choices, default="1", console=console)
        if choice == "q":
            break
        if choice == "s":
            continue
        moved = trash_copies(group, group.files[int(choice) - 1])
        trashed += moved
        console.print(f"[green]{len(moved)} cópias enviadas para a lixeira.[/]")
    console.print(f"Total: [bold]{len(trashed)}[/] arquivos enviados para a lixeira.")
    return trashed
