"""Histórico SQLite dos lotes de movimentação e rollback verificado por SHA-256."""

from __future__ import annotations

import os
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import TracebackType

from .deduplicator import file_hash
from .models import ExecutionBatch, MoveOperation

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    root TEXT NOT NULL,
    kind TEXT NOT NULL,
    undone_at TEXT
);
CREATE TABLE IF NOT EXISTS moves (
    id INTEGER PRIMARY KEY,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    src TEXT NOT NULL,
    dst TEXT NOT NULL,
    sha256 TEXT NOT NULL
);
"""


def db_path() -> Path:
    default = Path.home() / ".local" / "share" / "organizador" / "history.db"
    return Path(os.environ.get("ORGANIZADOR_HISTORY", default))


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class History:
    def __init__(self, path: Path | None = None) -> None:
        path = path or db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(path)
        self.con.execute("PRAGMA foreign_keys = ON")
        # WAL + NORMAL: commit por movimento continua seguro contra queda do processo, sem fsync a cada um
        self.con.execute("PRAGMA journal_mode = WAL")
        self.con.execute("PRAGMA synchronous = NORMAL")
        self.con.executescript(SCHEMA)

    def __enter__(self) -> History:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None:
        self.con.close()

    def start_batch(self, root: Path, kind: str) -> int:
        cur = self.con.execute("INSERT INTO batches (created_at, root, kind) VALUES (?, ?, ?)",
                               (_now(), str(root), kind))
        self.con.commit()
        assert cur.lastrowid is not None
        return cur.lastrowid

    def record(self, batch_id: int, op: MoveOperation) -> None:
        # commit a cada movimento: se o processo cair, o log continua fiel ao disco
        self.con.execute("INSERT INTO moves (batch_id, src, dst, sha256) VALUES (?, ?, ?, ?)",
                         (batch_id, str(op.src), str(op.dst), op.sha256))
        self.con.commit()

    def get_batch(self, batch_id: int | None = None) -> ExecutionBatch | None:
        """Sem id: o último lote ainda não desfeito."""
        sql = "SELECT id, created_at, root, kind, undone_at FROM batches "
        row = (self.con.execute(sql + "WHERE id = ?", (batch_id,)) if batch_id is not None
               else self.con.execute(sql + "WHERE undone_at IS NULL ORDER BY id DESC LIMIT 1")).fetchone()
        if row is None:
            return None
        moves = self.con.execute("SELECT src, dst, sha256 FROM moves WHERE batch_id = ? ORDER BY id", (row[0],))
        return ExecutionBatch(row[0], row[1], Path(row[2]), row[3], row[4],
                              [MoveOperation(Path(s), Path(d), h) for s, d, h in moves])

    def list_batches(self) -> list[tuple[ExecutionBatch, int]]:
        rows = self.con.execute(
            "SELECT b.id, b.created_at, b.root, b.kind, b.undone_at, COUNT(m.id) FROM batches b "
            "LEFT JOIN moves m ON m.batch_id = b.id GROUP BY b.id ORDER BY b.id DESC"
        ).fetchall()
        return [(ExecutionBatch(r[0], r[1], Path(r[2]), r[3], r[4]), r[5]) for r in rows]

    def mark_undone(self, batch_id: int) -> None:
        self.con.execute("UPDATE batches SET undone_at = ? WHERE id = ?", (_now(), batch_id))
        self.con.commit()

    def delete_batch(self, batch_id: int) -> None:
        self.con.execute("DELETE FROM batches WHERE id = ?", (batch_id,))
        self.con.commit()


def prune_empty(directory: Path, root: Path) -> None:
    """Remove `directory` e pais vazios, sem nunca subir acima de `root`."""
    while directory != root and root in directory.parents:
        try:
            directory.rmdir()
        except OSError:
            return  # não vazia (ou sem permissão)
        directory = directory.parent


@dataclass
class UndoResult:
    batch_id: int
    restored: list[MoveOperation] = field(default_factory=list)
    skipped: list[tuple[MoveOperation, str]] = field(default_factory=list)


def undo_batch(history: History, batch_id: int | None = None) -> UndoResult | None:
    """Devolve os arquivos do lote aos caminhos originais, conferindo o hash de cada um."""
    batch = history.get_batch(batch_id)
    if batch is None or batch.undone_at:
        return None
    result = UndoResult(batch.id)
    for op in reversed(batch.moves):
        if not op.dst.exists():
            result.skipped.append((op, "arquivo não está mais no destino"))
        elif op.src.exists():
            result.skipped.append((op, "já existe um arquivo no caminho original"))
        elif op.sha256 and file_hash(op.dst) != op.sha256:
            result.skipped.append((op, "conteúdo alterado depois da organização"))
        else:
            op.src.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(op.dst, op.src)
            result.restored.append(op)
            prune_empty(op.dst.parent, batch.root)
    history.mark_undone(batch.id)
    return result
