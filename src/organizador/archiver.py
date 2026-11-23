"""Compacta arquivos antigos por ano, verificando a integridade antes de descartar os originais."""

from __future__ import annotations

import tarfile
import zipfile
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from .deduplicator import file_hash, move_to_trash, stream_hash
from .history import prune_empty
from .models import FileMetadata
from .organizer import free_name

ARCHIVE_DIR = "_arquivo"


class Format(StrEnum):
    zip = "zip"
    tar = "tar.gz"


def plan_archive(files: Iterable[FileMetadata]) -> dict[int, list[FileMetadata]]:
    by_year: dict[int, list[FileMetadata]] = defaultdict(list)
    for f in files:
        by_year[datetime.fromtimestamp(f.mtime).year].append(f)
    return dict(sorted(by_year.items()))


def _archive_hashes(archive: Path, fmt: Format) -> dict[str, str]:
    found: dict[str, str] = {}
    if fmt is Format.zip:
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                with zf.open(info) as fh:
                    found[info.filename] = stream_hash(fh)
    else:
        with tarfile.open(archive, "r:gz") as tf:
            for member in tf.getmembers():
                if (member_fh := tf.extractfile(member)) is not None:
                    found[member.name] = stream_hash(member_fh)
    return found


def archive_old(root: Path, by_year: dict[int, list[FileMetadata]], fmt: Format) -> list[Path]:
    """Cria `_arquivo/AAAA.zip|tar.gz`; originais só vão para a lixeira se o pacote conferir."""
    dest_dir = root / ARCHIVE_DIR
    dest_dir.mkdir(exist_ok=True)
    created: list[Path] = []
    for year, files in by_year.items():
        target = free_name(dest_dir / f"{year}.{fmt.value}", set())
        expected = {f.path.relative_to(root).as_posix(): file_hash(f.path) for f in files}
        if fmt is Format.zip:
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, strict_timestamps=False) as zf:
                for f in files:
                    zf.write(f.path, f.path.relative_to(root).as_posix())
        else:
            with tarfile.open(target, "w:gz") as tf:
                for f in files:
                    tf.add(f.path, arcname=f.path.relative_to(root).as_posix())
        if _archive_hashes(target, fmt) != expected:
            target.unlink()
            raise RuntimeError(f"Falha de integridade em {target.name}; originais mantidos.")
        for f in files:
            move_to_trash(f.path)
            prune_empty(f.path.parent, root)
        created.append(target)
    return created
