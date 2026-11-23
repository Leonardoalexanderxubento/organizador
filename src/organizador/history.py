"""Histórico SQLite das movimentações, para permitir desfazer."""

from __future__ import annotations

import os
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import TracebackType

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, root TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS moves (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    src TEXT NOT NULL,
    dst TEXT NOT NULL
);
"""

Move = tuple[Path, Path]


def db_path() -> Path:
    return Path(os.environ.get("ORGANIZADOR_HISTORY", Path.home() / ".organizador_history.sqlite"))


class History:
    def __init__(self, path: Path | None = None) -> None:
        self.con = sqlite3.connect(path or db_path())
        self.con.execute("PRAGMA foreign_keys = ON")
        self.con.executescript(SCHEMA)

    def __enter__(self) -> History:
        return self

    def __exit__(self, *_: type[BaseException] | BaseException | TracebackType | None) -> None:
        self.con.close()

    def start_run(self, root: Path) -> int:
        cur = self.con.execute("INSERT INTO runs (created_at, root) VALUES (?, ?)",
                               (datetime.now().isoformat(timespec="seconds"), str(root)))
        self.con.commit()
        assert cur.lastrowid is not None
        return cur.lastrowid

    def record(self, run_id: int, src: Path, dst: Path) -> None:
        # commit a cada movimento: se o processo cair, o log continua fiel ao disco
        self.con.execute("INSERT INTO moves (run_id, src, dst) VALUES (?, ?, ?)", (run_id, str(src), str(dst)))
        self.con.commit()

    def last_run(self) -> tuple[int, Path, list[Move]] | None:
        row = self.con.execute("SELECT id, root FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            return None
        moves = self.con.execute("SELECT src, dst FROM moves WHERE run_id = ? ORDER BY id", (row[0],)).fetchall()
        return row[0], Path(row[1]), [(Path(s), Path(d)) for s, d in moves]

    def delete_run(self, run_id: int) -> None:
        self.con.execute("DELETE FROM runs WHERE id = ?", (run_id,))
        self.con.commit()


@dataclass
class UndoResult:
    restored: list[Move] = field(default_factory=list)
    skipped: list[tuple[Move, str]] = field(default_factory=list)


def _prune_empty(directory: Path, root: Path) -> None:
    while directory != root and root in directory.parents:
        try:
            directory.rmdir()
        except OSError:
            return  # não vazia
        directory = directory.parent


def undo_last(history: History) -> UndoResult | None:
    """Devolve os arquivos da última organização aos caminhos originais."""
    run = history.last_run()
    if run is None:
        return None
    run_id, root, moves = run
    result = UndoResult()
    for src, dst in reversed(moves):
        if not dst.exists():
            result.skipped.append(((src, dst), "arquivo não está mais no destino"))
            continue
        if src.exists():
            result.skipped.append(((src, dst), "já existe um arquivo no caminho original"))
            continue
        src.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(dst, src)
        result.restored.append((src, dst))
        _prune_empty(dst.parent, root)
    history.delete_run(run_id)
    return result
