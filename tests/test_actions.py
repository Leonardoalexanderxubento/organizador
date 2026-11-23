"""organizer, history/undo, archiver, interactive e CLI."""

from __future__ import annotations

import shutil
import tarfile
import zipfile
from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from organizador import archiver, organizer
from organizador.archiver import Format, archive_old, plan_archive
from organizador.cli import app
from organizador.config import RegexRule
from organizador.history import History, undo_batch
from organizador.organizer import By, execute_moves, plan_moves
from organizador.scanner import scan

from conftest import make

runner = CliRunner()
OLD = datetime(2021, 6, 1).timestamp()


def run(*args: str, input: str | None = None) -> str:
    result = runner.invoke(app, list(args), input=input)
    assert result.exit_code == 0, result.output
    return result.output


def organize(root: Path, by: By = By.category, **kw: bool) -> int:
    with History() as h:
        return execute_moves(plan_moves(root, scan(root).files, by), root, h, **kw)


# ---------- organizer ----------

def test_dry_run_moves_nothing(root: Path) -> None:
    f = make(root / "x.pdf")
    assert "simulação" in run("organize", str(root)).lower()
    assert f.exists() and not (root / "Documentos").exists()


def test_multiple_name_conflicts(root: Path) -> None:
    for d in "abc":
        make(root / d / "rel.pdf", d.encode())
    make(root / "Documentos" / "rel.pdf", b"0")
    run("organize", str(root), "--execute")
    docs = root / "Documentos"
    assert sorted(p.name for p in docs.iterdir()) == ["rel (1).pdf", "rel (2).pdf", "rel (3).pdf", "rel.pdf"]
    assert (docs / "rel.pdf").read_bytes() == b"0"


def test_strategies_date_ext_regex(root: Path) -> None:
    f = make(root / "nf_123.pdf", mtime=OLD)
    g = make(root / "LEIAME")
    files = scan(root).files
    assert {(m.src, m.dst) for m in plan_moves(root, files, By.date)} == {
        (f, root / "2021" / "06" / f.name), (g, root / f"{datetime.now():%Y}" / f"{datetime.now():%m}" / g.name)}
    assert {m.dst for m in plan_moves(root, files, By.ext)} == {root / "PDF" / f.name, root / "SEM_EXTENSAO" / g.name}
    rules = [RegexRule(pattern=r"^nf_\d+", folder="Financeiro/Notas")]
    assert [(m.src, m.dst) for m in plan_moves(root, files, By.regex, rules)] == [
        (f, root / "Financeiro" / "Notas" / f.name)]


def test_already_organized_and_protected_files_stay(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make(root / "Imagens" / "a.png")
    cfg = make(root / "organizador.toml", b"")
    monkeypatch.setenv("ORGANIZADOR_CONFIG", str(cfg))
    assert plan_moves(root, scan(root).files, By.category) == []


def test_clean_empty_folders(root: Path) -> None:
    make(root / "x" / "y" / "foto.jpg")
    (root / "ja_vazia").mkdir()
    organize(root)
    assert not (root / "x").exists() and (root / "ja_vazia").exists()


def test_keep_empty_folders(root: Path) -> None:
    make(root / "x" / "foto.jpg")
    run("organize", str(root), "--execute", "--keep-empty")
    assert (root / "x").is_dir()


def test_failure_mid_batch_rolls_back(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    files = [make(root / "sub" / f"{n}.txt") for n in "abc"]
    real_move, calls = shutil.move, []

    def flaky(src: str, dst: str) -> object:
        calls.append(src)
        if len(calls) == 2:
            raise OSError("disco cheio")
        return real_move(src, dst)

    monkeypatch.setattr(organizer.shutil, "move", flaky)
    with pytest.raises(OSError):
        organize(root)
    assert all(f.exists() for f in files) and not (root / "Documentos").exists()
    with History() as h:
        assert h.list_batches() == []


# ---------- history / undo ----------

def test_undo_restores_prunes_and_marks_undone(root: Path) -> None:
    originals = [make(root / "x.mp3", b"m"), make(root / "deep" / "y.zip", b"z")]
    organize(root)
    assert not any(p.exists() for p in originals) and not (root / "deep").exists()
    assert "2 arquivos restaurados" in run("undo")
    assert all(p.exists() for p in originals)
    assert not (root / "Áudios").exists() and not (root / "Compactados").exists()
    assert "Nada para desfazer" in run("undo")
    assert "desfeito" in run("history")


def test_undo_specific_batch(root: Path) -> None:
    a = make(root / "a.txt")
    first = organize(root)
    b = make(root / "b.png")
    organize(root)
    run("undo", "--batch-id", str(first))
    assert a.exists() and not b.exists() and (root / "Imagens" / "b.png").exists()


def test_undo_skips_when_original_taken_or_content_changed(root: Path) -> None:
    a = make(root / "a.txt", b"original")
    b = make(root / "b.txt", b"original b")
    organize(root)
    make(a, b"novo no lugar")
    (root / "Documentos" / "b.txt").write_bytes(b"editado")
    with History() as h:
        result = undo_batch(h)
    assert result is not None and not result.restored
    assert sorted(why for _, why in result.skipped) == [
        "conteúdo alterado depois da organização", "já existe um arquivo no caminho original"]
    assert not b.exists()


def test_undo_skips_missing_destination(root: Path) -> None:
    make(root / "a.txt")
    organize(root)
    (root / "Documentos" / "a.txt").unlink()
    assert "não está mais no destino" in run("undo")


def test_history_details_and_missing_batch(root: Path) -> None:
    make(root / "a.txt")
    batch = organize(root)
    assert "a.txt" in run("history", "--batch-id", str(batch))
    assert runner.invoke(app, ["history", "--batch-id", "999"]).exit_code == 1


# ---------- archiver ----------

@pytest.mark.parametrize("fmt", list(Format))
def test_archive_old_files(root: Path, trash: Path, fmt: Format) -> None:
    make(root / "velho1.txt", b"um", mtime=OLD)
    make(root / "sub" / "velho2.txt", b"dois", mtime=OLD)
    novo = make(root / "novo.txt", b"novo")
    files = scan(root, older_than_days=365).files
    [pkg] = archive_old(root, plan_archive(files), fmt)
    assert pkg == root / "_arquivo" / f"2021.{fmt.value}"
    if fmt is Format.zip:
        with zipfile.ZipFile(pkg) as zf:
            names = sorted(zf.namelist())
    else:
        with tarfile.open(pkg) as tf:
            names = sorted(tf.getnames())
    assert names == ["sub/velho2.txt", "velho1.txt"]
    assert novo.exists() and not (root / "sub").exists() and len(list(trash.iterdir())) == 2


def test_archive_integrity_failure_keeps_originals(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = make(root / "velho.txt", b"x", mtime=OLD)
    monkeypatch.setattr(archiver, "_archive_hashes", lambda *a: {})
    with pytest.raises(RuntimeError):
        archive_old(root, plan_archive(scan(root).files), Format.zip)
    assert f.exists() and not (root / "_arquivo" / "2021.zip").exists()


def test_archive_cli(root: Path) -> None:
    make(root / "velho.txt", b"x", mtime=OLD)
    assert "simulação" in run("archive", str(root), "--older-than", "30").lower()
    assert (root / "velho.txt").exists()
    run("archive", str(root), "--older-than", "30", "--format", "tar.gz", "--execute")
    assert (root / "_arquivo" / "2021.tar.gz").exists() and not (root / "velho.txt").exists()
    assert "Nenhum arquivo" in run("archive", str(root), "--older-than", "30")


# ---------- duplicates / interactive ----------

def _dups(root: Path) -> tuple[Path, Path, Path]:
    return (make(root / "a.txt", b"same", mtime=1_000_000), make(root / "b.txt", b"same", mtime=2_000_000),
            make(root / "c.txt", b"same", mtime=3_000_000))


def test_duplicates_dry_run_then_execute(root: Path, trash: Path) -> None:
    a, b, c = _dups(root)
    assert "Simulação" in run("duplicates", str(root), "--delete")
    assert b.exists() and c.exists()
    assert runner.invoke(app, ["duplicates", str(root), "--delete", "--execute"], input="n\n").exit_code != 0
    run("duplicates", str(root), "--delete-duplicates", "--execute", "--yes")
    assert a.exists() and not b.exists() and not c.exists() and len(list(trash.iterdir())) == 2
    assert "Nenhum" in run("duplicates", str(root))


def test_duplicates_keep_newest(root: Path) -> None:
    a, b, c = _dups(root)
    run("duplicates", str(root), "--delete", "--keep-newest", "--execute", "-y")
    assert c.exists() and not a.exists() and not b.exists()


def test_interactive_choose_which_to_keep(root: Path) -> None:
    a, b, c = _dups(root)
    make(root / "x1.bin", b"outro")
    make(root / "x2.bin", b"outro")
    run("interactive", str(root), input="2\ns\n")
    assert b.exists() and not a.exists() and not c.exists()
    assert (root / "x1.bin").exists() and (root / "x2.bin").exists()


def test_interactive_quit_and_flag(root: Path) -> None:
    a, b, c = _dups(root)
    run("duplicates", str(root), "--interactive", input="q\n")
    assert a.exists() and b.exists() and c.exists()
    assert "Nenhum" in run("interactive", str(make(root / "vazia" / "f.txt").parent))


# ---------- scan / config CLI ----------

def test_cli_scan_exports(root: Path, tmp_path: Path) -> None:
    make(root / "a.txt", b"hi")
    make(root / "skip.log", b"hi")
    out_json, out_html = tmp_path / "s.json", tmp_path / "s.html"
    out = run("scan", str(root), "--ignore", "*.log", "--export-json", str(out_json), "--export-html", str(out_html))
    assert "1 arquivos" in out and out_json.exists() and out_html.exists()
    assert runner.invoke(app, ["scan", str(root), "--min-size", "abc"]).exit_code == 1


def test_cli_config_init_show_validate(cfg_file: Path) -> None:
    assert "não existe" in run("config", "validate")
    assert "padrões embutidos" in run("config", "show")
    run("config", "init")
    assert cfg_file.exists() and "já existe" in run("config", "init")
    run("config", "init", "--force")
    assert "válido" in run("config", "validate")
    cfg_file.write_text('[[regex_rules]]\npattern = "("\nfolder = "X"\n', encoding="utf-8")
    result = runner.invoke(app, ["config", "validate"])
    assert result.exit_code == 1 and "regex inválida" in result.output


def test_organize_by_regex_requires_rules(root: Path, cfg_file: Path) -> None:
    make(root / "nf_1.pdf")
    assert runner.invoke(app, ["organize", str(root), "--by", "regex"]).exit_code == 1
    cfg_file.write_text('[[regex_rules]]\npattern = "^nf_"\nfolder = "Notas"\n', encoding="utf-8")
    run("organize", str(root), "--by", "regex", "--execute")
    assert (root / "Notas" / "nf_1.pdf").exists()
    assert "já está organizada" in run("organize", str(root), "--by", "regex")
