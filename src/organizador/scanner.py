"""Varredura recursiva de diretórios com filtros."""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

OTHER = "Outros"

DEFAULT_CATEGORIES: dict[str, list[str]] = {
    "Imagens": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".heic", ".tiff", ".ico"],
    "Documentos": [".pdf", ".doc", ".docx", ".txt", ".odt", ".xls", ".xlsx", ".ppt", ".pptx", ".csv", ".md", ".rtf"],
    "Vídeos": [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".flv"],
    "Áudios": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"],
    "Compactados": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"],
    "Código": [".py", ".js", ".ts", ".html", ".css", ".java", ".c", ".cpp", ".h", ".go", ".rs", ".rb",
               ".php", ".sh", ".json", ".xml", ".yml", ".yaml", ".toml", ".sql"],
}

DEFAULT_IGNORE: list[str] = [".git", "node_modules", "__pycache__", ".venv"]

_UNITS = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}


@dataclass(frozen=True)
class FileInfo:
    path: Path
    size: int
    mtime: float
    category: str


def parse_size(text: str) -> int:
    """Converte '10MB', '1.5 GB' ou '2048' em bytes."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([KMGT]?B)?\s*", text.upper())
    if not m:
        raise ValueError(f"Tamanho inválido: {text!r} (use ex.: 500KB, 10MB, 1GB)")
    return int(float(m.group(1)) * _UNITS[m.group(2) or "B"])


def human_size(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _norm_ext(ext: str) -> str:
    ext = ext.lower().strip()
    return ext if ext.startswith(".") else f".{ext}"


def scan(
    root: Path,
    *,
    extensions: Iterable[str] | None = None,
    min_size: int = 0,
    max_size: int | None = None,
    ignore: Sequence[str] = DEFAULT_IGNORE,
    categories: Mapping[str, Sequence[str]] = DEFAULT_CATEGORIES,
) -> list[FileInfo]:
    """Lista arquivos regulares sob `root`, sem seguir links simbólicos."""
    root = Path(root)
    if not root.is_dir():
        raise NotADirectoryError(root)
    ignored = set(ignore)
    exts = {_norm_ext(e) for e in extensions} if extensions else None
    ext_map = {_norm_ext(e): cat for cat, es in categories.items() for e in es}

    found: list[FileInfo] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ignored]
        for name in filenames:
            if name in ignored:
                continue
            path = Path(dirpath) / name
            suffix = path.suffix.lower()
            if exts is not None and suffix not in exts:
                continue
            try:
                st = os.lstat(path)
            except OSError:
                continue  # sem permissão ou removido durante a varredura
            if not stat.S_ISREG(st.st_mode):
                continue
            if st.st_size < min_size or (max_size is not None and st.st_size > max_size):
                continue
            found.append(FileInfo(path, st.st_size, st.st_mtime, ext_map.get(suffix, OTHER)))
    return found
