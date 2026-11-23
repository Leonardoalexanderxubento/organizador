"""Leitura e criação de ~/.organizador.toml."""

from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path

from .scanner import DEFAULT_CATEGORIES, DEFAULT_IGNORE


def config_path() -> Path:
    return Path(os.environ.get("ORGANIZADOR_CONFIG", Path.home() / ".organizador.toml"))


def default_toml() -> str:
    lines = [
        "# Configuração do organizador",
        "# Pastas/arquivos ignorados na varredura",
        f"ignore = {json.dumps(DEFAULT_IGNORE, ensure_ascii=False)}",
        "",
        "# Categoria = lista de extensões. Extensões fora daqui vão para 'Outros'.",
        "[categories]",
    ]
    lines += [f"{json.dumps(cat, ensure_ascii=False)} = {json.dumps(exts)}" for cat, exts in DEFAULT_CATEGORIES.items()]
    return "\n".join(lines) + "\n"


def write_default(path: Path | None = None) -> Path:
    path = path or config_path()
    path.write_text(default_toml(), encoding="utf-8")
    return path


def load_config(path: Path | None = None) -> tuple[dict[str, list[str]], list[str]]:
    """Retorna (categorias, ignorados). Sem arquivo, usa os padrões."""
    path = path or config_path()
    if not path.exists():
        return dict(DEFAULT_CATEGORIES), list(DEFAULT_IGNORE)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"{path}: TOML inválido ({e})") from e
    categories = data.get("categories", DEFAULT_CATEGORIES)
    ignore = data.get("ignore", DEFAULT_IGNORE)
    if not isinstance(categories, dict) or not all(
        isinstance(v, list) and all(isinstance(e, str) for e in v) for v in categories.values()
    ):
        raise ValueError(f"{path}: [categories] deve mapear nome -> lista de extensões")
    if not isinstance(ignore, list) or not all(isinstance(i, str) for i in ignore):
        raise ValueError(f"{path}: 'ignore' deve ser uma lista de nomes")
    return categories, ignore
