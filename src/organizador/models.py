"""Modelos de dados compartilhados entre os módulos."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FileMetadata:
    path: Path
    size: int
    mtime: float
    category: str


@dataclass
class ScanResult:
    files: list[FileMetadata]
    errors: list[str] = field(default_factory=list)


@dataclass
class DuplicateGroup:
    files: list[FileMetadata]  # files[0] é o que fica por padrão

    @property
    def keep(self) -> FileMetadata:
        return self.files[0]

    @property
    def copies(self) -> list[FileMetadata]:
        return self.files[1:]

    @property
    def size(self) -> int:
        return self.files[0].size

    @property
    def wasted(self) -> int:
        return self.size * (len(self.files) - 1)


@dataclass(frozen=True)
class MoveOperation:
    src: Path
    dst: Path
    sha256: str = ""


@dataclass
class ExecutionBatch:
    id: int
    created_at: str
    root: Path
    kind: str
    undone_at: str | None = None
    moves: list[MoveOperation] = field(default_factory=list)


@dataclass
class ScanReport:
    root: str
    generated_at: str
    total_files: int
    total_size: int
    by_category: dict[str, dict[str, int]]
    largest: list[dict[str, Any]]
    empty: list[dict[str, Any]]
    old: list[dict[str, Any]]
    old_days: int
    timeline: dict[str, int]  # "AAAA-MM" -> quantidade (data de modificação)
    errors: list[str]
    duplicates: list[dict[str, Any]] = field(default_factory=list)
    reclaimable: int = 0
