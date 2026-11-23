"""Planejamento e execução segura das movimentações."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Iterable
from datetime import datetime
from enum import Enum
from pathlib import Path

from .config import config_path
from .history import History, Move, db_path
from .scanner import FileInfo


class By(str, Enum):
    category = "category"
    date = "date"


def target_dir(root: Path, f: FileInfo, by: By) -> Path:
    if by is By.category:
        return root / f.category
    d = datetime.fromtimestamp(f.mtime)
    return root / f"{d:%Y}" / f"{d:%m}"


def _free_name(dest: Path, taken: set[str]) -> Path:
    """`arquivo.pdf` -> `arquivo (1).pdf` se já existir no disco ou no plano."""
    candidate, n = dest, 1
    while os.path.normcase(candidate) in taken or candidate.exists():
        candidate = dest.with_name(f"{dest.stem} ({n}){dest.suffix}")
        n += 1
    return candidate


def plan_moves(root: Path, files: Iterable[FileInfo], by: By) -> list[Move]:
    taken: set[str] = set()
    moves: list[Move] = []
    # organizar a home não pode mover o próprio histórico/config
    protected = {os.path.normcase(p.resolve()) for p in (db_path(), config_path())}
    for f in sorted(files, key=lambda f: str(f.path)):
        folder = target_dir(root, f, by)
        if f.path.parent == folder or os.path.normcase(f.path.resolve()) in protected:
            continue  # já organizado ou protegido
        dest = _free_name(folder / f.path.name, taken)
        taken.add(os.path.normcase(dest))
        moves.append((f.path, dest))
    return moves


def execute_moves(
    moves: list[Move],
    root: Path,
    history: History,
    wrap: Callable[[Iterable[Move]], Iterable[Move]] = lambda it: it,
) -> int:
    run_id = history.start_run(root)
    for src, dst in wrap(moves):
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():  # surgiu depois do plano: nunca sobrescrever
            raise FileExistsError(dst)
        shutil.move(src, dst)
        history.record(run_id, src, dst)
    return run_id
