"""Configuração validada (Pydantic) lida de ~/.organizador.toml, com padrões embutidos."""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any

import tomli_w
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .scanner import DEFAULT_CATEGORIES, DEFAULT_IGNORE, parse_size

_BAD_NAME = re.compile(r'[/\\:*?"<>|]')


class RegexRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pattern: str
    folder: str

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, v: str) -> str:
        try:
            re.compile(v)
        except re.error as e:
            raise ValueError(f"regex inválida: {e}") from e
        return v

    @field_validator("folder")
    @classmethod
    def _inside_root(cls, v: str) -> str:
        # a pasta vem do usuário: nunca deixar mover arquivos para fora da raiz
        p = PurePosixPath(v.replace("\\", "/"))
        if not v.strip() or p.is_absolute() or ".." in p.parts or ":" in v:
            raise ValueError("folder deve ser um caminho relativo, sem '..'")
        return v


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ignore: list[str] = Field(default_factory=lambda: list(DEFAULT_IGNORE))
    categories: dict[str, list[str]] = Field(
        default_factory=lambda: {k: list(v) for k, v in DEFAULT_CATEGORIES.items()})
    regex_rules: list[RegexRule] = Field(default_factory=list)
    min_size: int = 0
    max_size: int | None = None

    @field_validator("min_size", "max_size", mode="before")
    @classmethod
    def _size(cls, v: Any) -> Any:
        return parse_size(v) if isinstance(v, str) else v

    @field_validator("categories")
    @classmethod
    def _folder_names(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        for name in v:
            if not name.strip() or name in {".", ".."} or _BAD_NAME.search(name):
                raise ValueError(f"nome de categoria inválido para pasta: {name!r}")
        return v


def config_path() -> Path:
    return Path(os.environ.get("ORGANIZADOR_CONFIG", Path.home() / ".organizador.toml"))


def dump_toml(settings: Settings) -> str:
    return tomli_w.dumps(settings.model_dump(exclude_none=True))


def default_toml() -> str:
    header = (
        "# Configuração do organizador\n"
        "# ignore: nomes ou padrões estilo .gitignore (ex.: \"*.tmp\", \"build/\")\n"
        "# min_size / max_size: limites padrão de tamanho (ex.: \"1KB\", \"2GB\")\n"
        "# regex_rules: usadas por `organize --by regex`. Exemplo:\n"
        "#   [[regex_rules]]\n"
        "#   pattern = \"(?i)^nota[_ ]?fiscal\"\n"
        "#   folder = \"Financeiro/Notas\"\n\n"
    )
    return header + dump_toml(Settings())


def write_default(path: Path | None = None) -> Path:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(default_toml(), encoding="utf-8")
    return path


def load_settings(path: Path | None = None) -> Settings:
    """Sem arquivo, usa os padrões. Arquivo inválido gera ValueError legível."""
    path = path or config_path()
    if not path.exists():
        return Settings()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"{path}: TOML inválido ({e})") from e
    try:
        return Settings.model_validate(data)
    except ValidationError as e:
        raise ValueError(f"{path}: {e}") from e
