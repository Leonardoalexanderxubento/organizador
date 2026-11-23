"""Varredura recursiva de diretórios com filtros e `.organizadorignore`."""

from __future__ import annotations

import os
import re
import stat
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from fnmatch import fnmatch
from pathlib import Path

from .models import FileMetadata, ScanResult

OTHER = "Outros"
IGNORE_FILE = ".organizadorignore"

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


def load_ignore_patterns(root: Path, extra: Iterable[str] = ()) -> list[str]:
    patterns = list(extra)
    ignore_file = root / IGNORE_FILE
    if ignore_file.is_file():
        lines = ignore_file.read_text(encoding="utf-8").splitlines()
        patterns += [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]
    return patterns


def is_ignored(rel: str, name: str, is_dir: bool, patterns: Sequence[str]) -> bool:
    """Padrões estilo .gitignore: `*.log`, `build/` (só pastas), `docs/rascunho.txt`.

    shortcut: sem negação (`!padrao`) nem `**`; adotar `pathspec` se alguém precisar.
    """
    for pat in patterns:
        dir_only = pat.endswith("/")
        pat = pat.rstrip("/").lstrip("/")
        if dir_only and not is_dir:
            continue
        if fnmatch(name, pat) or fnmatch(rel, pat):
            return True
    return False


def scan(
    root: Path,
    *,
    extensions: Iterable[str] | None = None,
    min_size: int = 0,
    max_size: int | None = None,
    older_than_days: float | None = None,
    ignore: Sequence[str] = DEFAULT_IGNORE,
    categories: Mapping[str, Sequence[str]] = DEFAULT_CATEGORIES,
    on_progress: Callable[[int], None] | None = None,
) -> ScanResult:
    """Lista arquivos regulares sob `root`. Erros de permissão são coletados, nunca interrompem."""
    root = Path(root)
    if not root.is_dir():
        raise NotADirectoryError(root)
    patterns = load_ignore_patterns(root, ignore)
    exts = {_norm_ext(e) for e in extensions} if extensions else None
    ext_map = {_norm_ext(e): cat for cat, es in categories.items() for e in es}
    cutoff = time.time() - older_than_days * 86400 if older_than_days is not None else None
    result = ScanResult(files=[])

    def on_error(err: OSError) -> None:
        result.errors.append(f"{err.filename}: {err.strerror}")

    # followlinks=False (padrão): links para pastas não são seguidos, então não há loops
    for dirpath, dirnames, filenames in os.walk(root, onerror=on_error):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        prefix = "" if rel_dir == "." else f"{rel_dir}/"
        dirnames[:] = [d for d in dirnames if not is_ignored(prefix + d, d, True, patterns)]
        for name in filenames:
            if name == IGNORE_FILE or is_ignored(prefix + name, name, False, patterns):
                continue
            path = Path(dirpath) / name
            suffix = path.suffix.lower()
            if exts is not None and suffix not in exts:
                continue
            try:
                st = os.lstat(path)
            except OSError as err:
                on_error(err)
                continue
            if not stat.S_ISREG(st.st_mode):
                continue  # links simbólicos, dispositivos, pipes
            if st.st_size < min_size or (max_size is not None and st.st_size > max_size):
                continue
            if cutoff is not None and st.st_mtime >= cutoff:
                continue
            result.files.append(FileMetadata(path, st.st_size, st.st_mtime, ext_map.get(suffix, OTHER)))
            if on_progress and len(result.files) % 250 == 0:
                on_progress(len(result.files))
    return result
