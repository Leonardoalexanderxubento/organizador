"""Relatórios em JSON e HTML (gráfico em SVG puro, sem dependências)."""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from .deduplicator import reclaimable
from .scanner import FileInfo, human_size

Report = dict[str, Any]


def _entry(f: FileInfo) -> dict[str, Any]:
    return {"path": str(f.path), "size": f.size, "category": f.category,
            "modified": datetime.fromtimestamp(f.mtime).isoformat(timespec="seconds")}


def summarize(files: Sequence[FileInfo], old_days: int = 365, top: int = 20) -> Report:
    by_cat: dict[str, dict[str, int]] = {}
    for f in files:
        c = by_cat.setdefault(f.category, {"count": 0, "size": 0})
        c["count"] += 1
        c["size"] += f.size
    cutoff = time.time() - old_days * 86400
    return {
        "total_files": len(files),
        "total_size": sum(f.size for f in files),
        "by_category": dict(sorted(by_cat.items(), key=lambda kv: -kv[1]["size"])),
        "largest": [_entry(f) for f in sorted(files, key=lambda f: -f.size)[:top]],
        "empty": [_entry(f) for f in files if f.size == 0],
        "old": [_entry(f) for f in sorted(files, key=lambda f: f.mtime) if f.mtime < cutoff],
        "old_days": old_days,
    }


def build_report(root: Path, files: Sequence[FileInfo], groups: list[list[FileInfo]], old_days: int = 365) -> Report:
    return {
        "root": str(root),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        **summarize(files, old_days),
        "duplicates": [{"size": g[0].size, "keep": str(g[0].path), "copies": [str(f.path) for f in g[1:]]}
                       for g in groups],
        "reclaimable": reclaimable(groups),
    }


def write_json(report: Report, path: Path) -> Path:
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _bar_chart(by_cat: dict[str, dict[str, int]]) -> str:
    peak = max((c["size"] for c in by_cat.values()), default=0) or 1
    rows = []
    for i, (name, c) in enumerate(by_cat.items()):
        w, y = 480 * c["size"] / peak, i * 34
        rows.append(
            f'<text x="0" y="{y + 21}">{escape(name)}</text>'
            f'<rect x="130" y="{y + 6}" width="{w:.1f}" height="22" rx="4" fill="#4f7cff"/>'
            f'<text x="{138 + w:.1f}" y="{y + 21}">{human_size(c["size"])} · {c["count"]} arq.</text>'
        )
    return (f'<svg viewBox="0 0 800 {len(by_cat) * 34 + 8}" width="100%" role="img" '
            f'aria-label="Espaço ocupado por categoria">{"".join(rows)}</svg>')


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "<p class='muted'>Nenhum.</p>"
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{escape(c)}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def write_html(report: Report, path: Path) -> Path:
    largest = [[f["path"], human_size(f["size"]), f["category"]] for f in report["largest"]]
    dups = [[d["keep"], "\n".join(d["copies"]), human_size(d["size"] * len(d["copies"]))] for d in report["duplicates"]]
    html = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Relatório organizador – {escape(report['root'])}</title>
<style>
body{{font-family:system-ui,sans-serif;margin:2rem auto;max-width:1000px;padding:0 1rem;color:#1d2330}}
h1{{font-size:1.5rem}} .muted{{color:#667}} svg text{{font-size:13px;fill:#1d2330}}
.cards{{display:flex;gap:1rem;flex-wrap:wrap}} .card{{background:#f2f5fb;border-radius:8px;padding:1rem 1.25rem}}
.card b{{display:block;font-size:1.4rem}} table{{border-collapse:collapse;width:100%;font-size:.9rem}}
th,td{{text-align:left;padding:.4rem;border-bottom:1px solid #e3e6ee;vertical-align:top;white-space:pre-line;word-break:break-all}}
</style></head><body>
<h1>Relatório de {escape(report['root'])}</h1>
<p class="muted">Gerado em {escape(report['generated_at'])}</p>
<div class="cards">
<div class="card"><b>{report['total_files']}</b>arquivos</div>
<div class="card"><b>{human_size(report['total_size'])}</b>espaço total</div>
<div class="card"><b>{len(report['duplicates'])}</b>grupos de duplicados</div>
<div class="card"><b>{human_size(report['reclaimable'])}</b>recuperáveis</div>
</div>
<h2>Espaço por categoria</h2>{_bar_chart(report['by_category'])}
<h2>Top {len(largest)} maiores arquivos</h2>{_table(['Arquivo', 'Tamanho', 'Categoria'], largest)}
<h2>Duplicados</h2>{_table(['Mantido (mais antigo)', 'Cópias', 'Recuperável'], dups)}
<h2>Arquivos vazios ({len(report['empty'])})</h2>{_table(['Arquivo'], [[f['path']] for f in report['empty']])}
</body></html>
"""
    path.write_text(html, encoding="utf-8")
    return path
