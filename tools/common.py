"""やまだ商店（架空）の道具で共通に使うもの：場所・日付・CSV の読み書き・data の鍵・承認ファイルの読み方。"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import re
import stat
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WD = "月火水木金土日"
NOTE = "架空のデータです（株式会社やまだ商店はサンプル企業で実在しません）。金額は円・税抜"


# ── 場所 ──────────────────────────────────────────────────
class Paths:
    def __init__(self, root=None):
        self.root = Path(root).expanduser().resolve() if root else REPO
        self.data = self.root / "data"
        self.sim = self.root / "sim"
        self.state = self.sim / "state.json"
        self.prior = self.sim / "前年_日別.csv"
        self.approvals = self.root / "approvals"
        self.pending = self.approvals / "pending"
        self.approved = self.approvals / "approved"
        self.rejected = self.approvals / "rejected"
        self.logs = self.root / "logs"
        self.reports = self.root / "reports"


# ── 日付 ──────────────────────────────────────────────────
def d(s) -> dt.date:
    return s if isinstance(s, dt.date) else dt.date.fromisoformat(str(s)[:10])


def is_open(day: dt.date) -> bool:
    return day.weekday() != 6 and not (day.month == 1 and day.day <= 3)


def add_months(first: dt.date, n: int) -> dt.date:
    y, m = divmod(first.month - 1 + n, 12)
    return dt.date(first.year + y, m + 1, 1)


def month_last(day: dt.date) -> dt.date:
    return add_months(day.replace(day=1), 1) - dt.timedelta(days=1)


def ym(day: dt.date) -> str:
    return f"{day.year}-{day.month:02d}"


def add_business_days(day: dt.date, n: int) -> dt.date:
    while n > 0:
        day += dt.timedelta(days=1)
        if day.weekday() < 5:
            n -= 1
    return day


def weekday_back(day: dt.date) -> dt.date:
    while day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    return day


def jp(day: dt.date) -> str:
    return f"{day.month}/{day.day}（{WD[day.weekday()]}）"


def yen(x) -> int:
    return int(round(x, -1))


def fmt(n) -> str:
    try:
        return f"{int(round(float(n))):,}"
    except (TypeError, ValueError):
        return str(n)


# ── CSV ──────────────────────────────────────────────────
def read_csv(path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        first = f.readline()
        if not first.startswith("#"):
            f.seek(0)
        return list(csv.DictReader(f))


def write_csv(path, header, rows, note_extra="", today=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write(f"# {NOTE}。{note_extra}\n" if note_extra else f"# {NOTE}\n")
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def append_csv(path, rows):
    if not rows:
        return
    with open(path, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)


def header_of(path) -> list[str]:
    with open(path, encoding="utf-8") as f:
        first = f.readline()
        if first.startswith("#"):
            first = f.readline()
    return next(csv.reader([first]))


# ── data の鍵（sim.py だけが書く） ─────────────────────────────
def _walk(top: Path):
    if not top.exists():
        return
    yield top
    for p in sorted(top.rglob("*")):
        yield p


def unlock(paths: Paths):
    """sim.py が書く前に、data/ と sim/ の状態ファイルに書き込みの許可を戻す。"""
    for p in list(_walk(paths.data)) + [x for x in (paths.state, paths.prior) if x.exists()]:
        try:
            os.chmod(p, os.stat(p).st_mode | stat.S_IWUSR)
        except FileNotFoundError:
            pass


def lock(paths: Paths):
    """書き終わったら、data/（フォルダもファイルも）と sim/ の状態ファイルを読むだけにする。"""
    items = list(_walk(paths.data)) + [x for x in (paths.state, paths.prior) if x.exists()]
    for p in sorted(items, key=lambda x: -len(x.parts)):     # 中から順に
        mode = os.stat(p).st_mode
        os.chmod(p, mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


# ── 状態 ─────────────────────────────────────────────────
def load_state(paths: Paths) -> dict:
    with open(paths.state, encoding="utf-8") as f:
        return json.load(f)


def save_state(paths: Paths, state: dict):
    paths.sim.mkdir(parents=True, exist_ok=True)
    with open(paths.state, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, sort_keys=False)
        f.write("\n")


# ── 承認ファイル（approvals/*/YYYYMMDD-NNN_件名.md） ──────────────────
REQUIRED = ["id", "件名", "種類", "担当AI", "金額", "期限", "効果の見込み", "根拠", "リスク"]


def parse_proposal(path) -> tuple[dict, str]:
    """先頭の --- と --- の間を読む。key: 値／key: のあとに「  - 項目」の並び／実行: {JSON} の3つだけ。"""
    text = Path(path).read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if not m:
        raise ValueError(f"{Path(path).name}：先頭の --- で囲んだ欄がありません")
    fm, body = {}, m.group(2)
    key = None
    for line in m.group(1).splitlines():
        if not line.strip():
            continue
        item = re.match(r"^\s+-\s*(.*)$", line)
        if item and key:
            if not isinstance(fm.get(key), list):
                fm[key] = []
            fm[key].append(item.group(1).strip().strip('"'))
            continue
        kv = re.match(r"^([^\s:][^:]*):\s*(.*)$", line)
        if not kv:
            continue
        key, val = kv.group(1).strip(), kv.group(2).strip()
        if key == "実行" and val:
            try:
                fm[key] = json.loads(val)
            except json.JSONDecodeError as e:
                raise ValueError(f"{Path(path).name}：実行 の JSON が読めません（{e}）")
        elif val == "":
            fm[key] = ""
        else:
            fm[key] = val.strip('"').strip("'")
    if "金額" in fm:
        num = re.sub(r"[^\d\-]", "", str(fm["金額"]))
        fm["金額"] = int(num) if num not in ("", "-") else 0
    return fm, body


def check_proposal(fm: dict) -> list[str]:
    errs = [f"「{k}」がない" for k in REQUIRED if k not in fm or fm[k] in ("", None, [])]
    if fm.get("id") and not re.fullmatch(r"\d{8}-\d{3}", str(fm["id"])):
        errs.append("id は YYYYMMDD-NNN の形")
    if fm.get("期限"):
        try:
            d(str(fm["期限"])[:10])
        except ValueError:
            errs.append("期限 は YYYY-MM-DD（時刻をつけるなら YYYY-MM-DD HH:MM）")
    return errs


def find_proposal(folder: Path, pid: str):
    hits = sorted(folder.glob(f"{pid}_*.md")) + sorted(folder.glob(f"{pid}.md"))
    return hits[0] if hits else None
