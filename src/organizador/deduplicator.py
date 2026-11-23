"""Detecção de duplicados: agrupa por tamanho, depois por SHA-256 em blocos."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

from .scanner import FileInfo

CHUNK_SIZE = 1024 * 1024


def file_hash(path: Path, chunk_size: int = CHUNK_SIZE) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk_size):
            h.update(block)
    return h.hexdigest()


def find_duplicates(files: Iterable[FileInfo]) -> list[list[FileInfo]]:
    """Grupos de arquivos idênticos; em cada grupo o mais antigo vem primeiro."""
    by_size: dict[int, list[FileInfo]] = defaultdict(list)
    for f in files:
        if f.size > 0:  # vazios são "iguais" mas não liberam espaço
            by_size[f.size].append(f)

    groups: list[list[FileInfo]] = []
    for same_size in by_size.values():
        if len(same_size) < 2:
            continue
        by_hash: dict[str, list[FileInfo]] = defaultdict(list)
        for f in same_size:
            try:
                by_hash[file_hash(f.path)].append(f)
            except OSError:
                continue
        groups += [sorted(g, key=lambda f: (f.mtime, str(f.path))) for g in by_hash.values() if len(g) > 1]
    return sorted(groups, key=lambda g: g[0].size * (len(g) - 1), reverse=True)


def reclaimable(groups: Iterable[list[FileInfo]]) -> int:
    return sum(g[0].size * (len(g) - 1) for g in groups)


def delete_duplicates(groups: Iterable[list[FileInfo]]) -> list[Path]:
    """Apaga todas as cópias exceto a mais antiga de cada grupo."""
    removed: list[Path] = []
    for group in groups:
        if not group[0].path.exists():
            continue  # sem o original, apagar as cópias perderia o conteúdo
        for f in group[1:]:
            f.path.unlink(missing_ok=True)
            removed.append(f.path)
    return removed
