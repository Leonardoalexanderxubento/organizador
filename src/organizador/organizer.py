"""Planejamento e execução transacional das movimentações."""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from .config import RegexRule, config_path
from .deduplicator import file_hash
from .history import History, db_path, prune_empty
from .models import FileMetadata, MoveOperation

NO_EXT = "SEM_EXTENSAO"
CompiledRules = Sequence[tuple[re.Pattern[str], str]]


class By(StrEnum):
    category = "category"
    date = "date"
    ext = "ext"
    regex = "regex"


def target_dir(root: Path, f: FileMetadata, by: By, rules: CompiledRules = ()) -> Path | None:
    """Pasta de destino, ou None quando o arquivo não deve ser movido."""
    if by is By.category:
        return root / f.category
    if by is By.date:
        d = datetime.fromtimestamp(f.mtime)
        return root / f"{d:%Y}" / f"{d:%m}"
    if by is By.ext:
        return root / (f.path.suffix.lstrip(".").upper() or NO_EXT)
    for pattern, folder in rules:
        if pattern.search(f.path.name):
            return root / folder
    return None


def free_name(dest: Path, taken: set[str]) -> Path:
    """`arquivo.pdf` -> `arquivo (1).pdf` se já existir no disco ou no plano."""
    candidate, n = dest, 1
    while os.path.normcase(candidate) in taken or candidate.exists():
        candidate = dest.with_name(f"{dest.stem} ({n}){dest.suffix}")
        n += 1
    return candidate


def plan_moves(root: Path, files: Iterable[FileMetadata], by: By,
               rules: Sequence[RegexRule] = ()) -> list[MoveOperation]:
    compiled = [(re.compile(r.pattern), r.folder) for r in rules]
    # organizar a home não pode mover o próprio histórico/config
    protected = {os.path.normcase(p.resolve()) for p in (db_path(), config_path())}
    taken: set[str] = set()
    moves: list[MoveOperation] = []
    for f in sorted(files, key=lambda f: str(f.path)):
        folder = target_dir(root, f, by, compiled)
        if folder is None or f.path.parent == folder or os.path.normcase(f.path.resolve()) in protected:
            continue
        dest = free_name(folder / f.path.name, taken)
        taken.add(os.path.normcase(dest))
        moves.append(MoveOperation(f.path, dest))
    return moves


def execute_moves(
    moves: list[MoveOperation],
    root: Path,
    history: History,
    *,
    clean_empty: bool = True,
    wrap: Callable[[Iterable[MoveOperation]], Iterable[MoveOperation]] = lambda it: it,
) -> int:
    """Move tudo ou nada: se algo falhar, os já movidos voltam e o lote é descartado."""
    batch_id = history.start_batch(root, "organize")
    done: list[MoveOperation] = []
    try:
        for op in wrap(moves):
            digest = file_hash(op.src)
            op.dst.parent.mkdir(parents=True, exist_ok=True)
            if op.dst.exists():  # surgiu depois do plano: nunca sobrescrever
                raise FileExistsError(op.dst)
            shutil.move(op.src, op.dst)  # rename, ou copy2 (copystat) entre discos: preserva datas
            done.append(MoveOperation(op.src, op.dst, digest))
            history.record(batch_id, done[-1])
    except BaseException:
        for op in reversed(done):
            shutil.move(op.dst, op.src)
            prune_empty(op.dst.parent, root)
        history.delete_batch(batch_id)
        raise
    if clean_empty:
        for op in done:
            prune_empty(op.src.parent, root)
    return batch_id
