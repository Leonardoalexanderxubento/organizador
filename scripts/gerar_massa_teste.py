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
SIZES = [0, 120, 4_000, 40_000, 200_000, 1_500_000]
WEIGHTS = [3, 25, 35, 25, 10, 2]
SUBDIRS = [".", "Downloads", "Downloads/antigos", "Desktop", "Desktop/coisas/mais coisas", "fotos viagem",
           "projeto/src"]


def gerar(root: Path, arquivos: int = 150, seed: int = 42) -> tuple[int, int]:
    """Cria a massa em `root` e devolve (arquivos, duplicados)."""
    rng = random.Random(seed)
    if root.exists() and any(root.iterdir()):
        raise SystemExit(f"{root} já existe e não está vazia; escolha outro destino.")
    now = time.time()

    created: list[Path] = []
    for i in range(arquivos):
        path = root / rng.choice(SUBDIRS) / f"{rng.choice(NAMES)}_{i}{rng.choice(EXTS)}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(rng.randbytes(rng.choices(SIZES, WEIGHTS)[0]))
        mtime = now - rng.randint(0, 4 * 365) * 86400
        os.utime(path, (mtime, mtime))
        created.append(path)

    # duplicados: mesmo conteúdo, às vezes com o mesmo nome em outra pasta (gera conflito ao organizar)
    dups = 0
    for src in rng.sample([p for p in created if p.stat().st_size > 0], k=max(20, arquivos // 8)):
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
    return len(created), dups


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("destino", nargs="?", default="massa_teste", type=Path)
    ap.add_argument("--arquivos", type=int, default=150)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    n, dups = gerar(args.destino, args.arquivos, args.seed)
    print(f"Criados {n} arquivos e {dups} duplicados em {args.destino.resolve()}")


if __name__ == "__main__":
    main()
