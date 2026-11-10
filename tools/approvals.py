#!/usr/bin/env python3
"""承認の道具（やまだ商店・架空）。お金と約束は人（山田太郎）が決める。

    python3 tools/approvals.py list [--top 5]        承認待ちを「期限が近い順 → 金額が大きい順」に並べる
    python3 tools/approvals.py check                 承認待ちのファイルの書き方を確かめる
    python3 tools/approvals.py approve <ID> [--by 山田太郎]   承認：approved/ へ移す → 意思決定ログ → sim.py apply
    python3 tools/approvals.py reject <ID> <理由>     却下：rejected/ へ移す → 意思決定ログ

approve と reject は人が /承認・/却下 で動かすもの。AI が自分で動かさない。
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Paths, check_proposal, d, find_proposal, fmt, load_state, parse_proposal  # noqa: E402

LOG_HEAD = "# 意思決定ログ（やまだ商店・架空）\n\n承認と却下の記録。書くのは tools/approvals.py だけ（/承認・/却下）。\n\n| 日時 | 会社の日付 | ID | 件名 | 種類 | 金額 | 決定 | 決めた人 | 理由・メモ |\n|---|---|---|---|---|---|---|---|---|\n"


def load_all(folder: Path):
    out = []
    for f in sorted(folder.glob("*.md")):
        try:
            fm, body = parse_proposal(f)
            out.append((f, fm, check_proposal(fm)))
        except ValueError as e:
            out.append((f, {"id": f.stem.split("_")[0], "件名": f.stem}, [str(e)]))
    return out


def sort_key(item):
    fm = item[1]
    due = str(fm.get("期限", "9999-12-31"))
    return (due, -int(fm.get("金額") or 0))


def company_today(paths: Paths):
    try:
        return d(load_state(paths)["今日"])
    except Exception:
        return dt.date.today()


DEPT = {"ai-shacho": "社長", "ai-tencho": "店長", "ai-sekkyaku": "接客", "ai-uketsuke": "受付", "ai-shiire": "仕入れ",
        "ai-butsuryu": "物流", "ai-eigyo": "営業", "ai-ec": "EC販売", "ai-koukoku": "広告", "ai-kouhou": "広報",
        "ai-keiri": "経理", "ai-houmu": "法務"}


def cmd_list(paths: Paths, top=None):
    """承認待ちを、期限が近い順 → 金額が大きい順の表で全部出す（top を指定したときだけ上から N 件）。"""
    items = sorted(load_all(paths.pending), key=sort_key)
    today = company_today(paths)
    if not items:
        print("承認待ちはありません（0件）。")
        return
    shown = items[:top] if top else items
    head = f"承認待ち {len(items)}件（期限が近い順 → 金額が大きい順）"
    if top and len(items) > top:
        head += f"。上から{len(shown)}件"
    print(head)
    print("| 順 | ID | 何を | 金額 | 期限 | 部 |")
    print("|---|---|---|---|---|---|")
    for i, (f, fm, errs) in enumerate(shown, 1):
        due = str(fm.get("期限", ""))
        mark = "（期限切れ）" if due and d(due[:10]) < today else ("（今日まで）" if due and d(due[:10]) == today else "")
        bad = "（書き方に不足あり）" if errs else ""
        dept = DEPT.get(str(fm.get("担当AI", "")), fm.get("担当AI", ""))
        print(f"| {i} | {fm.get('id', '')} | {fm.get('件名', '')}{bad} | {fmt(fm.get('金額', 0))}円 | {due}{mark} | {dept} |")
    if top and len(items) > top:
        print(f"ほか {len(items) - top}件は /承認待ち で見られます。")
    print("承認は /承認 <ID>、見送りは /却下 <ID> <理由>。中身は approvals/pending/<ID>_….md")


def cmd_check(paths: Paths):
    items = load_all(paths.pending)
    bad = 0
    for f, fm, errs in items:
        if errs:
            bad += 1
            print(f"NG {f.name}：{'・'.join(errs)}")
        else:
            print(f"OK {f.name}")
    print(f"{len(items)}件中 {bad}件に直すところがあります。" if bad else f"{len(items)}件とも書き方は大丈夫です。")
    return 1 if bad else 0


def log(paths: Paths, fm, decision, who, memo):
    paths.logs.mkdir(parents=True, exist_ok=True)
    p = paths.logs / "意思決定ログ.md"
    if not p.exists():
        p.write_text(LOG_HEAD, encoding="utf-8")
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    memo = str(memo).replace("|", "／").replace("\n", " ")
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"| {now} | {company_today(paths)} | {fm.get('id', '')} | {fm.get('件名', '')} | {fm.get('種類', '')} | "
                f"{fmt(fm.get('金額', 0))}円 | {decision} | {who} | {memo} |\n")


def move(src: Path, folder: Path, stamp: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    dst = folder / src.name
    text = src.read_text(encoding="utf-8").rstrip() + "\n\n## 決定\n" + stamp + "\n"
    dst.write_text(text, encoding="utf-8")
    src.unlink()
    return dst


def cmd_approve(paths: Paths, pid: str, who: str):
    src = find_proposal(paths.pending, pid)
    if not src:
        done = find_proposal(paths.approved, pid) or find_proposal(paths.rejected, pid)
        print(f"{pid} は承認待ちにありません" + ("（もう決まっています）" if done else "") + "。/承認待ち で ID を確かめてください。")
        return 1
    fm, _ = parse_proposal(src)
    errs = check_proposal(fm)
    if errs:
        print(f"{pid} は書き方に足りない所があるので承認できません：{'・'.join(errs)}")
        return 1
    today = company_today(paths)
    move(src, paths.approved, f"- 承認（{who}・会社の日付 {today}・{dt.datetime.now():%Y-%m-%d %H:%M}）")
    log(paths, fm, "承認", who, fm.get("効果の見込み", ""))
    print(f"承認しました：{pid}「{fm.get('件名', '')}」{fmt(fm.get('金額', 0))}円")
    import sim                                       # 承認したら、すぐ会社に入れる
    try:
        sim.cmd_apply(paths, pid)
    except sim.ApplyError as e:
        print(f"会社に入れられませんでした：{e}")
        return 2
    return 0


def cmd_reject(paths: Paths, pid: str, reason: str, who: str):
    src = find_proposal(paths.pending, pid)
    if not src:
        print(f"{pid} は承認待ちにありません。/承認待ち で ID を確かめてください。")
        return 1
    fm, _ = parse_proposal(src)
    move(src, paths.rejected, f"- 却下（{who}・会社の日付 {company_today(paths)}）\n- 理由：{reason}")
    log(paths, fm, "却下", who, reason)
    print(f"却下しました：{pid}「{fm.get('件名', '')}」 理由：{reason}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="承認の道具（やまだ商店・架空）")
    ap.add_argument("--root")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list")
    p.add_argument("--top", type=int)
    sub.add_parser("check")
    p = sub.add_parser("approve")
    p.add_argument("id")
    p.add_argument("--by", default="山田太郎")
    p = sub.add_parser("reject")
    p.add_argument("id")
    p.add_argument("reason", nargs="+")
    p.add_argument("--by", default="山田太郎")
    a = ap.parse_args(argv)
    paths = Paths(a.root)
    if a.cmd == "list":
        cmd_list(paths, a.top)
        return 0
    if a.cmd == "check":
        return cmd_check(paths)
    if a.cmd == "approve":
        return cmd_approve(paths, a.id, a.by)
    return cmd_reject(paths, a.id, " ".join(a.reason), a.by)


if __name__ == "__main__":
    sys.exit(main())
