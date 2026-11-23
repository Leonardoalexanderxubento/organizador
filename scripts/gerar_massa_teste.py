"""Cria uma pasta bagunçada para testar o organizador na prática.

Uso: python scripts/gerar_massa_teste.py [destino] [--arquivos 150] [--seed 42]
"""

from __future__ import annotations

import argparse
import os
import random
import shutil
import time
from pathlib import Path

EXTS = [".jpg", ".png", ".gif", ".pdf", ".docx", ".txt", ".xlsx", ".mp4", ".mov", ".mp3", ".wav",
        ".zip", ".7z", ".py", ".js", ".json", ".xyz", ""]
NAMES = ["foto", "relatorio", "nota_fiscal", "musica", "video_ferias", "backup", "script", "IMG", "contrato",
         "planilha", "Documento sem título", "download", "cópia"]
SIZES = [0, 120, 4_000, 60_000, 400_000, 3_000_000]
WEIGHTS = [2, 20, 30, 25, 15, 3]
SUBDIRS = [".", "Downloads", "Downloads/antigos", "Desktop", "Desktop/coisas/mais coisas", "fotos viagem",
           "projeto/src"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("destino", nargs="?", default="massa_teste", type=Path)
    ap.add_argument("--arquivos", type=int, default=150)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    root: Path = args.destino
    if root.exists() and any(root.iterdir()):
        raise SystemExit(f"{root} já existe e não está vazia; escolha outro destino.")
    now = time.time()

    created: list[Path] = []
    for i in range(args.arquivos):
        path = root / rng.choice(SUBDIRS) / f"{rng.choice(NAMES)}_{i}{rng.choice(EXTS)}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(rng.randbytes(rng.choices(SIZES, WEIGHTS)[0]))
        mtime = now - rng.randint(0, 4 * 365) * 86400
        os.utime(path, (mtime, mtime))
        created.append(path)

    # duplicados: mesmo conteúdo, às vezes com o mesmo nome em outra pasta (gera conflito ao organizar)
    dups = 0
    for src in rng.sample([p for p in created if p.stat().st_size > 0], k=min(20, len(created) // 5)):
        dest_dir = root / rng.choice(SUBDIRS)
        dest = dest_dir / (src.name if dest_dir != src.parent else f"cópia de {src.name}")
        if dest.exists():
            continue
        shutil.copy2(src, dest)
        dups += 1

    # pastas que devem ser ignoradas
    for ignored in ("projeto/node_modules/lib/index.js", "projeto/.git/HEAD", "projeto/src/__pycache__/m.pyc"):
        p = root / ignored
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("ignorar", encoding="utf-8")

    print(f"Criados {len(created)} arquivos e {dups} duplicados em {root.resolve()}")


if __name__ == "__main__":
    main()
