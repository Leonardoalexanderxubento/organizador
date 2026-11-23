"""Detecção de duplicados em 3 estágios: tamanho -> hash parcial -> SHA-256 completo."""

from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import IO

import send2trash

from .models import DuplicateGroup, FileMetadata

CHUNK_SIZE = 64 * 1024
PARTIAL_SIZE = 8 * 1024
PARTIAL_MIN = 64 * 1024
WORKERS = 8


def stream_hash(fh: IO[bytes], chunk_size: int = CHUNK_SIZE) -> str:
    h = hashlib.sha256()
    while block := fh.read(chunk_size):
        h.update(block)
    return h.hexdigest()


def file_hash(path: Path, chunk_size: int = CHUNK_SIZE) -> str:
    with path.open("rb") as fh:
        return stream_hash(fh, chunk_size)


def partial_hash(path: Path) -> str:
    """SHA-256 dos primeiros e últimos 8 KB."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        h.update(fh.read(PARTIAL_SIZE))
        fh.seek(-PARTIAL_SIZE, os.SEEK_END)
        h.update(fh.read(PARTIAL_SIZE))
    return h.hexdigest()


def _refine(files: list[FileMetadata], key: Callable[[Path], str]) -> list[list[FileMetadata]]:
    """Reagrupa por (tamanho, key) em paralelo; ilegíveis são descartados."""

    def safe(f: FileMetadata) -> str | None:
        try:
            return key(f.path)
        except OSError:
            return None

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        keys = list(ex.map(safe, files))
    buckets: dict[tuple[int, str], list[FileMetadata]] = defaultdict(list)
    for f, k in zip(files, keys, strict=True):
        if k is not None:
            buckets[(f.size, k)].append(f)
    return [g for g in buckets.values() if len(g) > 1]


def find_duplicates(files: Iterable[FileMetadata], keep_newest: bool = False) -> list[DuplicateGroup]:
    by_size: dict[int, list[FileMetadata]] = defaultdict(list)
    for f in files:
        if f.size > 0:  # vazios são "iguais" mas não liberam espaço
            by_size[f.size].append(f)
    stage1 = [f for g in by_size.values() if len(g) > 1 for f in g]
    small = [f for f in stage1 if f.size <= PARTIAL_MIN]
    big = [f for g in _refine([f for f in stage1 if f.size > PARTIAL_MIN], partial_hash) for f in g]
    groups = _refine(small + big, file_hash)
    result = [DuplicateGroup(sorted(g, key=lambda f: (f.mtime, str(f.path)), reverse=keep_newest)) for g in groups]
    return sorted(result, key=lambda g: g.wasted, reverse=True)


def reclaimable(groups: Iterable[DuplicateGroup]) -> int:
    return sum(g.wasted for g in groups)


def move_to_trash(path: Path) -> None:
    send2trash.send2trash(str(path))


def trash_copies(group: DuplicateGroup, keep: FileMetadata | None = None) -> list[Path]:
    """Envia para a lixeira todos do grupo exceto `keep` (padrão: o mais antigo)."""
    keep = keep or group.keep
    if not keep.path.exists():
        return []  # sem o original, descartar as cópias perderia o conteúdo
    trashed: list[Path] = []
    for f in group.files:
        if f is not keep and f.path.exists():
            move_to_trash(f.path)
            trashed.append(f.path)
    return trashed


def trash_duplicates(groups: Iterable[DuplicateGroup]) -> list[Path]:
    return [p for g in groups for p in trash_copies(g)]
