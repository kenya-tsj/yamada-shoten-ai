#!/usr/bin/env python3
"""pytest が無くても動くテストの入口：python3 tests/run_tests.py（pytest があれば python3 -m pytest tests でもよい）。"""
import importlib
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import helpers  # noqa: E402


def main():
    t0 = time.time()
    ok = ng = 0
    for f in sorted(HERE.glob("test_*.py")):
        mod = importlib.import_module(f.stem)
        for name in sorted(n for n in dir(mod) if n.startswith("test_")):
            t = time.time()
            try:
                getattr(mod, name)()
                ok += 1
                print(f"OK  {f.stem}.{name}（{time.time() - t:.2f}秒）")
            except Exception:
                ng += 1
                print(f"NG  {f.stem}.{name}")
                traceback.print_exc()
            finally:
                helpers.cleanup()
    print(f"\n{ok}件 OK・{ng}件 NG（{time.time() - t0:.1f}秒）")
    return 1 if ng else 0


if __name__ == "__main__":
    sys.exit(main())
