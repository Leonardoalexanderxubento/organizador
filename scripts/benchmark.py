"""Benchmark: gera 2.000+ arquivos, mede scan/duplicates e valida organize + undo.

Uso: python scripts/benchmark.py [--arquivos 2500]
Roda numa pasta temporária, com histórico próprio e sem tocar na lixeira. Sai com código 1 se algo divergir.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

from gerar_massa_teste import gerar


def snapshot(root: Path) -> dict[str, str]:
    from organizador.deduplicator import file_hash

    return {p.relative_to(root).as_posix(): file_hash(p) for p in root.rglob("*") if p.is_file()}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arquivos", type=int, default=2500)
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["ORGANIZADOR_HISTORY"] = str(Path(tmp) / "history.db")
        from organizador.deduplicator import find_duplicates, reclaimable
        from organizador.history import History, undo_batch
        from organizador.organizer import By, execute_moves, plan_moves
        from organizador.scanner import human_size, scan

        root = Path(tmp) / "massa"
        criados, dups = gerar(root, args.arquivos, seed=7)
        before = snapshot(root)
        timings: dict[str, float] = {}

        t = time.perf_counter()
        result = scan(root)
        timings["scan"] = time.perf_counter() - t

        t = time.perf_counter()
        groups = find_duplicates(result.files)
        timings["duplicates"] = time.perf_counter() - t

        with History() as h:
            moves = plan_moves(root, result.files, By.category)
            t = time.perf_counter()
            execute_moves(moves, root, h)
            timings["organize"] = time.perf_counter() - t
            t = time.perf_counter()
            undo = undo_batch(h)
            timings["undo"] = time.perf_counter() - t

        after = snapshot(root)
        ok = before == after and undo is not None and not undo.skipped

        print(f"Massa: {criados} arquivos + {dups} duplicados ({len(result.files)} varridos, "
              f"{human_size(sum(f.size for f in result.files))})")
        for name, secs in timings.items():
            print(f"  {name:<11} {secs * 1000:8.0f} ms")
        print(f"  duplicados  {len(groups)} grupos, {human_size(reclaimable(groups))} recuperáveis")
        print(f"  movidos     {len(moves)} arquivos e restaurados pelo undo")
        print("Integridade após organize + undo:", "OK" if ok else "FALHOU")
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
