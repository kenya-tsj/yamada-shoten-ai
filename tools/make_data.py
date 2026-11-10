#!/usr/bin/env python3
"""（前の版の入口）データを作り直す。いまは tools/sim.py init と同じ。

    python3 tools/make_data.py                    はじめの状態（2026-11-10）に戻す
    python3 tools/make_data.py --date 2026-11-12  「今日」を指定して作り直す

新しく使うときは python3 tools/sim.py init を使ってください。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sim  # noqa: E402

if __name__ == "__main__":
    args = sys.argv[1:]
    root = []
    if args and not args[0].startswith("--"):
        root = ["--root", args.pop(0)]
    sys.exit(sim.main(root + ["init"] + args))
