from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Nunca tocar no histórico/config reais do usuário."""
    monkeypatch.setenv("ORGANIZADOR_HISTORY", str(tmp_path / "history.sqlite"))
    monkeypatch.setenv("ORGANIZADOR_CONFIG", str(tmp_path / "organizador.toml"))


def make(path: Path, content: bytes = b"x", mtime: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path
