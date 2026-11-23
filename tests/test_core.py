"""scanner, deduplicator, config e reporter."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from organizador import deduplicator
from organizador.config import Settings, load_settings, write_default
from organizador.deduplicator import (
    file_hash,
    find_duplicates,
    partial_hash,
    reclaimable,
    trash_duplicates,
)
from organizador.reporter import build_report, write_html, write_json
from organizador.scanner import parse_size, scan

from conftest import make, try_symlink

DAY = 86400.0
BIG = 100 * 1024  # acima do limite do hash parcial


# ---------- scanner ----------

def test_scan_categorizes_and_ignores_defaults(root: Path) -> None:
    make(root / "foto.JPG")
    make(root / "doc.pdf")
    make(root / "sem_ext")
    make(root / ".git" / "config")
    make(root / "a" / "node_modules" / "x.js")
    make(root / "a" / "__pycache__" / "m.pyc")
    cats = {f.path.name: f.category for f in scan(root).files}
    assert cats == {"foto.JPG": "Imagens", "doc.pdf": "Documentos", "sem_ext": "Outros"}


def test_scan_filters_extension_size_and_age(root: Path) -> None:
    import time
    make(root / "small.txt", b"a")
    make(root / "mid.txt", b"a" * 2000, mtime=time.time() - 400 * DAY)
    make(root / "mid_new.txt", b"a" * 2000)
    make(root / "big.txt", b"a" * 5000)
    make(root / "mid.png", b"a" * 2000)
    res = scan(root, extensions=["TXT"], min_size=1000, max_size=3000, older_than_days=365)
    assert [f.path.name for f in res.files] == ["mid.txt"]


def test_organizadorignore_and_extra_patterns(root: Path) -> None:
    (root / ".organizadorignore").write_text("# comentário\n*.log\nbuild/\ndocs/rascunho.txt\n", encoding="utf-8")
    make(root / "app.log")
    make(root / "build" / "out.bin")
    make(root / "build.txt")  # `build/` só casa com pastas
    make(root / "docs" / "rascunho.txt")
    make(root / "docs" / "final.txt")
    make(root / "tmp" / "x.tmp")
    names = sorted(f.path.name for f in scan(root, ignore=["*.tmp"]).files)
    assert names == ["build.txt", "final.txt"]


def test_parse_size() -> None:
    assert parse_size("2048") == 2048
    assert parse_size("1.5kb") == 1536
    assert parse_size("10 MB") == 10 * 1024**2
    with pytest.raises(ValueError):
        parse_size("dez megas")


def test_scan_survives_permission_denied_file(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make(root / "ok.txt")
    secret = make(root / "secreto.txt")
    real_lstat = os.lstat

    def fake_lstat(p: object, *a: object, **k: object) -> os.stat_result:
        if Path(str(p)) == secret:
            raise PermissionError(13, "Permission denied", str(p))
        return real_lstat(p, *a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "lstat", fake_lstat)
    res = scan(root)
    assert [f.path.name for f in res.files] == ["ok.txt"]
    assert len(res.errors) == 1 and "secreto.txt" in res.errors[0]


def test_scan_survives_permission_denied_dir(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make(root / "ok.txt")
    make(root / "trancada" / "x.txt")
    real_scandir = os.scandir

    def fake_scandir(p: object = ".") -> object:
        if Path(str(p)).name == "trancada":
            raise PermissionError(13, "Permission denied", str(p))
        return real_scandir(p)  # type: ignore[call-overload]

    monkeypatch.setattr(os, "scandir", fake_scandir)
    res = scan(root)
    assert [f.path.name for f in res.files] == ["ok.txt"]
    assert "trancada" in res.errors[0]


def test_scan_skips_file_symlinks(root: Path, tmp_path: Path) -> None:
    target = make(tmp_path / "fora.txt", b"fora")
    make(root / "real.txt")
    try_symlink(root / "link.txt", target)
    assert [f.path.name for f in scan(root).files] == ["real.txt"]


def test_scan_does_not_loop_on_circular_dir_symlink(root: Path) -> None:
    make(root / "a" / "f.txt")
    try_symlink(root / "a" / "loop", root, is_dir=True)
    assert [f.path.name for f in scan(root).files] == ["f.txt"]


def test_scan_rejects_file_root(root: Path) -> None:
    with pytest.raises(NotADirectoryError):
        scan(make(root / "f.txt"))


# ---------- deduplicator ----------

def test_duplicates_keep_oldest_or_newest(root: Path) -> None:
    data = os.urandom(BIG)
    old = make(root / "old.bin", data, mtime=1_000_000)
    new = make(root / "sub" / "new.bin", data, mtime=2_000_000)
    make(root / "same_size_diff.bin", os.urandom(BIG))
    groups = find_duplicates(scan(root).files)
    assert [[f.path for f in g.files] for g in groups] == [[old, new]]
    assert reclaimable(groups) == BIG
    assert find_duplicates(scan(root).files, keep_newest=True)[0].keep.path == new


def test_partial_hash_skips_full_hash_for_different_heads(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make(root / "a.bin", b"A" + b"\0" * (BIG - 1))
    make(root / "b.bin", b"B" + b"\0" * (BIG - 1))
    calls: list[Path] = []
    real = deduplicator.file_hash
    monkeypatch.setattr(deduplicator, "file_hash", lambda p, *a: calls.append(p) or real(p, *a))
    assert find_duplicates(scan(root).files) == []
    assert calls == []  # descartados no estágio 2


def test_full_hash_catches_middle_difference(root: Path) -> None:
    body = bytearray(b"\0" * BIG)
    make(root / "a.bin", bytes(body))
    body[BIG // 2] = 1
    make(root / "b.bin", bytes(body))
    assert partial_hash(root / "a.bin") == partial_hash(root / "b.bin")
    assert find_duplicates(scan(root).files) == []


def test_empty_files_are_not_duplicates(root: Path) -> None:
    make(root / "a.txt", b"")
    make(root / "b.txt", b"")
    assert find_duplicates(scan(root).files) == []


def test_chunked_hash_matches_whole(root: Path) -> None:
    p = make(root / "f", b"abc" * 1000)
    assert file_hash(p, chunk_size=7) == hashlib.sha256(b"abc" * 1000).hexdigest()


def test_unreadable_file_is_left_out_of_groups(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for n in "abc":
        make(root / f"{n}.txt", b"same")
    real = deduplicator.file_hash

    def fake(p: Path, *a: int) -> str:
        if p.name == "c.txt":
            raise PermissionError(13, "Permission denied", str(p))
        return real(p, *a)

    monkeypatch.setattr(deduplicator, "file_hash", fake)
    [group] = find_duplicates(scan(root).files)
    assert sorted(f.path.name for f in group.files) == ["a.txt", "b.txt"]


def test_trash_keeps_original_and_skips_when_original_gone(root: Path, trash: Path) -> None:
    make(root / "a.txt", b"same", mtime=1_000_000)
    copy = make(root / "b.txt", b"same", mtime=2_000_000)
    groups = find_duplicates(scan(root).files)
    assert trash_duplicates(groups) == [copy]
    assert (root / "a.txt").exists() and len(list(trash.iterdir())) == 1

    make(copy, b"same")
    groups = find_duplicates(scan(root).files)
    (root / "a.txt").unlink()  # original sumiu depois da varredura
    assert trash_duplicates(groups) == [] and copy.exists()


# ---------- config ----------

def test_settings_defaults_and_custom_file(cfg_file: Path) -> None:
    assert "Imagens" in load_settings().categories
    write_default()
    assert load_settings() == Settings()
    cfg_file.write_text(
        'ignore = ["lixo"]\nmin_size = "1KB"\n[categories]\nPlanilhas = [".xlsx"]\n'
        '[[regex_rules]]\npattern = "^nf_"\nfolder = "Financeiro/Notas"\n', encoding="utf-8")
    s = load_settings()
    assert s.ignore == ["lixo"] and s.min_size == 1024 and s.regex_rules[0].folder == "Financeiro/Notas"


@pytest.mark.parametrize("body", [
    "ignore = 3\n",
    "isto não é toml = \n",
    '[[regex_rules]]\npattern = "(sem fechar"\nfolder = "X"\n',
    '[[regex_rules]]\npattern = "x"\nfolder = "../fora"\n',
    '[[regex_rules]]\npattern = "x"\nfolder = "C:/Windows"\n',
    '[categories]\n"a/b" = [".x"]\n',
    'chave_desconhecida = 1\n',
    'max_size = "muito"\n',
])
def test_invalid_config_raises(cfg_file: Path, body: str) -> None:
    cfg_file.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError):
        load_settings()


# ---------- reporter ----------

def test_reports_json_and_html(root: Path, tmp_path: Path) -> None:
    make(root / "a.png", b"dup!")
    make(root / "b.png", b"dup!")
    make(root / "vazio.txt", b"")
    make(root / "velho.pdf", b"old", mtime=1_000_000)
    result = scan(root)
    report = build_report(root, result, find_duplicates(result.files))
    data = json.loads(write_json(report, tmp_path / "r.json").read_text(encoding="utf-8"))
    assert data["total_files"] == 4
    assert data["by_category"]["Imagens"] == {"count": 2, "size": 8}
    assert data["reclaimable"] == 4 and len(data["duplicates"]) == 1
    assert len(data["empty"]) == 1 and data["old"][0]["path"].endswith("velho.pdf")
    assert "1970-01" in data["timeline"]
    html = write_html(report, tmp_path / "r.html").read_text(encoding="utf-8")
    assert html.count("<svg") == 2 and "prefers-color-scheme:dark" in html and "http" not in html


def test_html_escapes_file_names(root: Path, tmp_path: Path) -> None:
    make(root / "<script>.txt", b"x") if os.name != "nt" else make(root / "a&b.txt", b"x")
    html = write_html(build_report(root, scan(root)), tmp_path / "r.html").read_text(encoding="utf-8")
    assert "<script>.txt" not in html and ("&lt;script&gt;" in html or "a&amp;b.txt" in html)
