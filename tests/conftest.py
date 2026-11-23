from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
import send2trash


@pytest.fixture(autouse=True)
def trash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isola histórico/config e troca a lixeira real por uma pasta temporária."""
    state = tmp_path / "state"
    bin_dir = state / "lixeira"
    bin_dir.mkdir(parents=True)
    monkeypatch.setenv("ORGANIZADOR_HISTORY", str(state / "history.db"))
    monkeypatch.setenv("ORGANIZADOR_CONFIG", str(state / "organizador.toml"))

    def fake_trash(path: str) -> None:
        src = Path(path)
        shutil.move(src, bin_dir / f"{len(list(bin_dir.iterdir()))}_{src.name}")

    monkeypatch.setattr(send2trash, "send2trash", fake_trash)
    return bin_dir


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = tmp_path / "r"
    r.mkdir()
    return r


@pytest.fixture
def cfg_file(tmp_path: Path) -> Path:
    return tmp_path / "state" / "organizador.toml"


def make(path: Path, content: bytes = b"x", mtime: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def try_symlink(link: Path, target: Path, is_dir: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=is_dir)
    except (OSError, NotImplementedError):
        pytest.skip("sem permissão para criar links simbólicos neste sistema")
