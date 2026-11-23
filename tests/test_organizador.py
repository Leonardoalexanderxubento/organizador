from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from conftest import make
from organizador.cli import app
from organizador.config import load_config, write_default
from organizador.deduplicator import delete_duplicates, file_hash, find_duplicates, reclaimable
from organizador.history import History, undo_last
from organizador.organizer import By, execute_moves, plan_moves
from organizador.reporter import build_report, write_html, write_json
from organizador.scanner import parse_size, scan

runner = CliRunner()
DAY = 86400.0


# ---------- scanner ----------

def test_scan_categorizes_and_ignores(tmp_path: Path) -> None:
    root = tmp_path / "r"
    make(root / "foto.JPG")
    make(root / "doc.pdf")
    make(root / "sem_ext")
    make(root / ".git" / "config")
    make(root / "a" / "node_modules" / "x.js")
    make(root / "a" / "__pycache__" / "m.pyc")
    cats = {f.path.name: f.category for f in scan(root)}
    assert cats == {"foto.JPG": "Imagens", "doc.pdf": "Documentos", "sem_ext": "Outros"}


def test_scan_filters_by_extension_and_size(tmp_path: Path) -> None:
    make(tmp_path / "small.txt", b"a")
    make(tmp_path / "mid.txt", b"a" * 2000)
    make(tmp_path / "big.txt", b"a" * 5000)
    make(tmp_path / "mid.png", b"a" * 2000)
    names = {f.path.name for f in scan(tmp_path, extensions=["txt"], min_size=1000, max_size=3000)}
    assert names == {"mid.txt"}


def test_parse_size() -> None:
    assert parse_size("2048") == 2048
    assert parse_size("1.5kb") == 1536
    assert parse_size("10 MB") == 10 * 1024**2
    with pytest.raises(ValueError):
        parse_size("dez megas")


# ---------- deduplicator ----------

def test_duplicates_large_files_keep_oldest(tmp_path: Path) -> None:
    big = b"\x01" * (3 * 1024 * 1024 + 7)  # maior que o bloco de hash
    old = make(tmp_path / "old.bin", big, mtime=1_000_000)
    new = make(tmp_path / "sub" / "new.bin", big, mtime=2_000_000)
    make(tmp_path / "same_size_diff.bin", b"\x02" * len(big))
    groups = find_duplicates(scan(tmp_path))
    assert [[f.path for f in g] for g in groups] == [[old, new]]
    assert reclaimable(groups) == len(big)
    assert delete_duplicates(groups) == [new]
    assert old.exists() and not new.exists()


def test_empty_files_are_not_duplicates(tmp_path: Path) -> None:
    make(tmp_path / "a.txt", b"")
    make(tmp_path / "b.txt", b"")
    assert find_duplicates(scan(tmp_path)) == []


def test_chunked_hash_matches_whole(tmp_path: Path) -> None:
    import hashlib
    p = make(tmp_path / "f", b"abc" * 1000)
    assert file_hash(p, chunk_size=7) == hashlib.sha256(b"abc" * 1000).hexdigest()


# ---------- organizer + history ----------

def test_dry_run_moves_nothing(tmp_path: Path) -> None:
    f = make(tmp_path / "x.pdf")
    result = runner.invoke(app, ["organize", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "simulação" in result.output.lower()
    assert f.exists() and not (tmp_path / "Documentos").exists()


def test_execute_moves_with_name_conflicts(tmp_path: Path) -> None:
    make(tmp_path / "a" / "rel.pdf", b"1")
    make(tmp_path / "b" / "rel.pdf", b"2")
    make(tmp_path / "Documentos" / "rel.pdf", b"0")  # já existe no destino
    result = runner.invoke(app, ["organize", str(tmp_path), "--execute"])
    assert result.exit_code == 0, result.output
    docs = tmp_path / "Documentos"
    assert sorted(p.name for p in docs.iterdir()) == ["rel (1).pdf", "rel (2).pdf", "rel.pdf"]
    assert (docs / "rel.pdf").read_bytes() == b"0"  # nada foi sobrescrito


def test_organize_by_date(tmp_path: Path) -> None:
    ts = datetime(2023, 4, 15).timestamp()
    make(tmp_path / "foto.jpg", mtime=ts)
    moves = plan_moves(tmp_path, scan(tmp_path), By.date)
    assert moves == [(tmp_path / "foto.jpg", tmp_path / "2023" / "04" / "foto.jpg")]


def test_already_organized_is_noop(tmp_path: Path) -> None:
    make(tmp_path / "Imagens" / "a.png")
    assert plan_moves(tmp_path, scan(tmp_path), By.category) == []


def test_undo_restores_and_prunes(tmp_path: Path) -> None:
    root = tmp_path / "r"
    originals = [make(root / "x.mp3", b"m"), make(root / "deep" / "y.zip", b"z")]
    with History() as h:
        execute_moves(plan_moves(root, scan(root), By.category), root, h)
    assert not any(p.exists() for p in originals)
    result = runner.invoke(app, ["undo"])
    assert result.exit_code == 0, result.output
    assert all(p.exists() for p in originals)
    assert not (root / "Áudios").exists() and not (root / "Compactados").exists()
    with History() as h:
        assert undo_last(h) is None  # histórico consumido


def test_undo_skips_when_original_taken(tmp_path: Path) -> None:
    src = make(tmp_path / "a.txt", b"original")
    with History() as h:
        execute_moves(plan_moves(tmp_path, scan(tmp_path), By.category), tmp_path, h)
        make(src, b"novo")
        result = undo_last(h)
    assert result is not None and len(result.skipped) == 1
    assert src.read_bytes() == b"novo"
    assert (tmp_path / "Documentos" / "a.txt").read_bytes() == b"original"


# ---------- reporter ----------

def test_reports_json_and_html(tmp_path: Path) -> None:
    root = tmp_path / "r"
    make(root / "a.png", b"dup!")
    make(root / "b.png", b"dup!")
    make(root / "vazio.txt", b"")
    make(root / "velho.pdf", b"old", mtime=1_000_000)
    files = scan(root)
    report = build_report(root, files, find_duplicates(files))
    data = json.loads(write_json(report, tmp_path / "r.json").read_text(encoding="utf-8"))
    assert data["total_files"] == 4
    assert data["by_category"]["Imagens"] == {"count": 2, "size": 8}
    assert data["reclaimable"] == 4 and len(data["duplicates"]) == 1
    assert len(data["empty"]) == 1 and data["old"][0]["path"].endswith("velho.pdf")
    html = write_html(report, tmp_path / "r.html").read_text(encoding="utf-8")
    assert "<svg" in html and "Imagens" in html and "Duplicados" in html


def test_cli_scan_exports(tmp_path: Path) -> None:
    root = tmp_path / "r"
    make(root / "a.txt", b"hi")
    out_json, out_html = tmp_path / "s.json", tmp_path / "s.html"
    result = runner.invoke(app, ["scan", str(root), "--export-json", str(out_json), "--export-html", str(out_html)])
    assert result.exit_code == 0, result.output
    assert out_json.exists() and out_html.exists()


def test_cli_duplicates_delete_requires_confirmation(tmp_path: Path) -> None:
    make(tmp_path / "a.txt", b"same", mtime=1_000_000)
    copy = make(tmp_path / "b.txt", b"same", mtime=2_000_000)
    result = runner.invoke(app, ["duplicates", str(tmp_path), "--delete-duplicates"], input="n\n")
    assert result.exit_code != 0 and copy.exists()
    result = runner.invoke(app, ["duplicates", str(tmp_path), "--delete-duplicates", "--yes"])
    assert result.exit_code == 0 and not copy.exists()


# ---------- config ----------

def test_config_roundtrip_and_custom_rules(tmp_path: Path) -> None:
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0 and (tmp_path / "organizador.toml").exists()
    cats, ignore = load_config()
    assert "Imagens" in cats and ".git" in ignore

    cfg = tmp_path / "organizador.toml"
    cfg.write_text('ignore = ["lixo"]\n[categories]\nPlanilhas = [".xlsx"]\n', encoding="utf-8")
    root = tmp_path / "r"
    make(root / "p.xlsx")
    make(root / "lixo" / "q.xlsx")
    assert [(f.path.name, f.category) for f in scan(root, ignore=load_config()[1], categories=load_config()[0])] \
        == [("p.xlsx", "Planilhas")]


def test_invalid_config_is_reported(tmp_path: Path) -> None:
    (tmp_path / "organizador.toml").write_text("ignore = 3\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config()
    write_default()
    assert load_config()[1]
