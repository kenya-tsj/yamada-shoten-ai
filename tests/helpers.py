"""テストの共通：一時フォルダに会社を作る（リポの data/ には触らない）。"""
from __future__ import annotations

import csv
import hashlib
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import sim  # noqa: E402
from common import Paths  # noqa: E402
from sim_model import DEFAULT_START  # noqa: E402

_made = []


def fresh() -> Paths:
    """はじめの日（2026-11-10）の会社を一時フォルダに作る。"""
    tmp = Path(tempfile.mkdtemp(prefix="yamada_test_"))
    _made.append(tmp)
    paths = Paths(tmp)
    sim.cmd_init(paths, DEFAULT_START, quiet=True)
    for sub in ("pending", "approved", "rejected"):
        (tmp / "approvals" / sub).mkdir(parents=True, exist_ok=True)
    return paths


def rows(paths: Paths, rel: str) -> list[dict]:
    with open(paths.data / rel, encoding="utf-8") as f:
        next(f)
        return list(csv.DictReader(f))


def digest(paths: Paths) -> str:
    h = hashlib.sha256()
    for p in sorted(paths.data.rglob("*")) + [paths.state]:
        if p.is_file():
            h.update(p.name.encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def write_proposal(paths: Paths, pid: str, body_extra: str = "", execute: str | None = None, folder="pending"):
    ex = execute if execute is not None else '{"発注": [{"商品ID": "S01", "数量": 80}, {"商品ID": "S12", "数量": 6}]}'
    text = f"""---
id: {pid}
件名: 播磨ゴールドと地ビールセットの発注
種類: 発注
担当AI: ai-shiire
金額: 107000
期限: 2026-11-10 15:00
効果の見込み: 11/13（金）に入荷
根拠:
  - data/purchasing/在庫.csv S01 在庫0
リスク: 売れ残り
実行: {ex}
---
テスト用の提案。
{body_extra}"""
    p = getattr(paths, folder) / f"{pid}_播磨ゴールドの発注.md"
    p.write_text(text, encoding="utf-8")
    return p


def cleanup():
    for tmp in _made:
        for p in [tmp] + list(tmp.rglob("*")):
            try:
                os.chmod(p, os.stat(p).st_mode | stat.S_IWUSR)
            except FileNotFoundError:
                pass
        shutil.rmtree(tmp, ignore_errors=True)
    _made.clear()
