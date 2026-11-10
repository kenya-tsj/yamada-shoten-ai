#!/usr/bin/env python3
"""やまだ商店（架空）のダッシュボード：reports/dashboard_data.json と reports/dashboard.html を作る。

    python3 tools/dashboard.py            作る
    python3 tools/dashboard.py --open     作ってブラウザで開く

- dashboard_data.json：画面の数字と「その数字がどこから来たか」（ファイル・サービス）。数字は q.py と同じ計算。
- dashboard.html：tools/dashboard_template.html があれば、その中の <!--DASH_DATA--> を
  <script>window.DASH = {…};</script> に置きかえて作る。なければ、ここで作る簡単な版（外の読み込みなし・1920×1080 向け）。
data/ と sim/state.json を読むだけ。書くのは reports/ の2つだけ。サービスとのつながりは全部シミュレーション（架空）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import approvals  # noqa: E402
import sim  # noqa: E402
from common import WD, Paths, d, fmt, is_open, jp, load_state, read_csv, ym  # noqa: E402
from sim_model import DAILY_FRESH, ITEM, MANUAL_SUPPLIERS, qty_s, reorder_point, unit  # noqa: E402
from sources import AGENTS, SOURCES  # noqa: E402

MARKER = "<!--DASH_DATA-->"
BIZ_SRC = {"店舗": ["smaregi"], "配達": ["delivery_sheet"], "EC": ["shopify", "rakuten", "amazon", "ga4"],
           "法人": ["freee_invoice"], "ギフト": ["gift_sheet", "shopify", "rakuten", "amazon"]}
SALES_FILES = ["data/accounting/日計表.csv", "data/store/POS_日別.csv", "data/delivery/配達_日別.csv", "data/ec/チャネル別_日別.csv",
               "data/gift/ギフト受注_日別.csv", "data/b2b/納品_日別.csv"]
SALES_SRC = ["smaregi", "delivery_sheet", "shopify", "rakuten", "amazon", "gift_sheet", "freee_invoice", "freee_accounting"]


def _pct(a, b):
    return round((a / b - 1) * 100, 1) if b else None


def build_data(paths: Paths) -> dict:
    """画面の数字と、その出どころ（q.py と同じ計算）。"""
    import q as qmod
    S = load_state(paths)
    D = paths.data
    today = d(S["今日"])
    j = read_csv(D / "accounting/日計表.csv")
    pos = read_csv(D / "store/POS_日別.csv")
    bykey = {r["日付"]: r for r in j}
    y = j[-1]
    w1 = [(today - dt.timedelta(days=i)).isoformat() for i in range(7, 0, -1)]
    w0 = [(today - dt.timedelta(days=i)).isoformat() for i in range(14, 7, -1)]

    def sumj(col, dates):
        return sum(int(bykey[x][col]) for x in dates if x in bykey)
    mk = ym(today)
    mt = [r["日付"] for r in j if r["日付"].startswith(mk)]
    bt = sim.budget_to_date(paths, today) or {}
    mtd = sumj("売上合計", mt)
    prev_y = bykey.get((d(y["日付"]) - dt.timedelta(days=7)).isoformat())
    lo = next(r for r in reversed(pos) if not r["備考"])
    lo_prev = next((r for r in pos if r["日付"] == (d(lo["日付"]) - dt.timedelta(days=7)).isoformat()), None)
    gp1, s1 = sumj("粗利", w1), sumj("売上合計", w1)
    gp0, s0 = sumj("粗利", w0), sumj("売上合計", w0)
    cash7 = bykey.get((today - dt.timedelta(days=8)).isoformat())
    stocked = [i for i in ITEM if ITEM[i][8] != "店内調理" and i not in DAILY_FRESH]
    outs = [i for i in stocked if S["在庫"].get(i, 0) <= 0]
    pend = sorted(approvals.load_all(paths.pending), key=approvals.sort_key)
    kpis = [
        {"id": "sales_yesterday", "label": "昨日の売上", "value": int(y["売上合計"]), "unit": "円", "date": y["日付"],
         "delta": {"vs": "前週同曜日", "pct": _pct(int(y["売上合計"]), int(prev_y["売上合計"])) if prev_y else None},
         "how": "店・配達・ネット3店・ギフト・法人の合計（日計表の売上合計）", "files": SALES_FILES, "sources": SALES_SRC},
        {"id": "sales_mtd", "label": "今月の売上", "value": mtd, "unit": "円", "budget": round(bt.get("合計", 0)),
         "budget_pct": round(mtd / bt["合計"] * 100, 1) if bt.get("合計") else None,
         "delta": {"vs": "予算（今日までの分）", "pct": _pct(mtd, bt.get("合計", 0))},
         "how": f"{today.month}/1〜昨日の売上合計。予算の今日までの分は、月の予算を去年の同じ日の売れ方で割り振ったもの",
         "files": ["data/accounting/日計表.csv", "data/accounting/予算.csv"], "sources": ["freee_accounting", "budget_excel", "kessansho_pdf"]},
        {"id": "gross_margin", "label": "粗利率（直近7日）", "value": round(gp1 / s1 * 100, 1) if s1 else None, "unit": "%",
         "delta": {"vs": "前の7日", "pt": round(gp1 / s1 * 100 - gp0 / s0 * 100, 1) if (s1 and s0) else None},
         "how": "粗利 ÷ 売上（直近7日）。粗利＝売上－仕入れの原価", "files": ["data/accounting/日計表.csv"],
         "sources": ["freee_accounting", "smaregi"]},
        {"id": "customers", "label": "客数（店）", "value": int(lo["客数"]), "unit": "人", "date": lo["日付"],
         "delta": {"vs": "前週同曜日", "pct": _pct(int(lo["客数"]), int(lo_prev["客数"])) if lo_prev else None},
         "how": "直近の営業日にレジで買ったお客様の数", "files": ["data/store/POS_日別.csv"], "sources": ["smaregi"]},
        {"id": "atv", "label": "客単価（店）", "value": int(lo["客単価"]), "unit": "円", "date": lo["日付"],
         "delta": {"vs": "前週同曜日", "pct": _pct(int(lo["客単価"]), int(lo_prev["客単価"])) if lo_prev else None},
         "how": "店の売上 ÷ 客数（直近の営業日）", "files": ["data/store/POS_日別.csv"], "sources": ["smaregi"]},
        {"id": "cash", "label": "現金", "value": int(S["現金"]), "unit": "円",
         "delta": {"vs": "7日前", "pct": _pct(int(S["現金"]), int(cash7["現金残高"])) if cash7 else None},
         "how": "銀行の普通預金の今朝の残高（日計表の現金残高）", "files": ["data/accounting/日計表.csv", "data/accounting/資金繰り.csv"],
         "sources": ["netbank", "freee_accounting"]},
        {"id": "stockouts", "label": "欠品の数", "value": len(outs), "unit": "品目", "delta": None,
         "how": "今朝の在庫が0の品目の数（毎日の生ものと店内調理は除く）", "files": ["data/purchasing/在庫.csv", "data/store/POS_商品別_直近14日.csv"],
         "sources": ["smaregi"]},
        {"id": "approvals", "label": "承認待ちの数", "value": len(pend), "unit": "件", "delta": None,
         "how": "AI が書いて、まだ人が決めていない提案（approvals/pending/）", "files": ["approvals/pending/"], "sources": []},
    ]
    q = qmod.Q(paths)
    by_business = []
    pr = qmod.prior_sum(q, w1)
    for name, col in qmod.BIZ:
        a1, a0, m = sumj(col, w1), sumj(col, w0), sumj(col, mt)
        by_business.append({"name": name, "value": m, "period": "今月", "last7": a1, "wow_pct": _pct(a1, a0),
                            "yoy_pct": _pct(a1, pr[name]) if name in pr else None,
                            "budget": round(bt.get(name, 0)), "budget_pct": round(m / bt[name] * 100, 1) if bt.get(name) else None,
                            "sources": BIZ_SRC[name]})
    ch = qmod.channel_month(q)
    tot = sum(c["value"] for c in ch) or 1
    by_channel = [{"name": c["name"], "value": c["value"], "orders": c["orders"], "fee": c["fee"], "source": c["source"],
                   "share_pct": round(c["value"] / tot * 100, 1), "通常": c["通常"], "ギフト": c["ギフト"], "period": "今月"} for c in ch]
    start = (today - dt.timedelta(days=56)).isoformat()
    series = {
        "酒類_日別": [{"d": r["日付"], "v": int(r["酒類"])} for r in pos if r["日付"] >= start and not r["備考"]],
        "売上_日別": [{"d": r["日付"], "v": int(r["売上合計"])} for r in j if r["日付"] >= start],
        "予算_日別": [{"d": r["日付"], "v": round(sim.daily_budget(paths, d(r["日付"])) or 0)} for r in j if r["日付"] >= start],
    }
    stockouts = []
    for iid in outs:
        rec = S.get("欠品記録", {}).get(iid, {})
        stockouts.append({"商品": ITEM[iid][1], "商品ID": iid, "単位": unit(iid), "since": rec.get("since"), "lost": rec.get("lost", 0),
                          "承認がいる": ITEM[iid][8] in MANUAL_SUPPLIERS})
    overdue = [{"相手": r["取引先"], "請求の月": r["請求の月"], "金額": int(r["請求額"]), "日数": int(r["期日から何日過ぎたか"])}
               for r in read_csv(D / "accounting/売掛金.csv") if r["期日から何日過ぎたか"]]
    appr = [{"id": fm.get("id", ""), "何を": fm.get("件名", ""), "金額": int(fm.get("金額") or 0), "期限": str(fm.get("期限", "")),
             "部": approvals.DEPT.get(str(fm.get("担当AI", "")), fm.get("担当AI", ""))} for _, fm, _ in pend]
    return {"company": "株式会社やまだ商店（架空）", "today": today.isoformat(), "as_of": "昨日まで",
            "note": "架空のサンプル企業。サービスとのつながりは全部シミュレーション（実際にはつないでいない）",
            "kpis": kpis, "by_business": by_business, "by_channel": by_channel, "series": series,
            "alerts": {"stockouts": stockouts, "overdue": overdue, "approvals": appr},
            "sources": SOURCES, "agents": [{"id": i, "name": n, "dept": dp} for i, n, dp in AGENTS]}

ACCENT = "#E3A21A"
E = html.escape


def nice(mx, n=4):
    """きりのいい目盛り（1・2・2.5・5 の倍数）"""
    raw = mx / n
    mag = 10 ** (len(str(int(raw))) - 1)
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    top = step * -(-mx // step)
    return top, step


def tile(label, value, sub=""):
    return f'<div class="tile"><div class="tl">{E(label)}</div><div class="tv">{value}</div><div class="ts">{sub}</div></div>'


def biz_bars(rows):
    """事業別：今月の実績（棒）と予算の今日までの分（縦の線）。"""
    W, rowh, left, right = 760, 58, 90, 240
    mx, step = nice(max(max(a, b) for _, a, b in rows) or 1)
    plot = W - left - right
    h = rowh * len(rows) + 30
    out = [f'<svg viewBox="0 0 {W} {h}" width="100%" role="img" aria-label="事業別の今月の売上と予算">']
    v = 0
    while v <= mx:
        x = left + plot * v / mx
        out.append(f'<line x1="{x:.1f}" y1="8" x2="{x:.1f}" y2="{h - 22}" class="grid"/>')
        out.append(f'<text x="{x:.1f}" y="{h - 6}" class="ax" text-anchor="middle">{v / 10000:,.0f}万</text>')
        v += step
    for i, (name, actual, budget) in enumerate(rows):
        y = 14 + i * rowh
        bw = max(2, plot * actual / mx)
        r = min(4, bw / 2)
        x0 = left
        path = (f"M{x0},{y} H{x0 + bw - r} Q{x0 + bw},{y} {x0 + bw},{y + r} V{y + 24 - r} "
                f"Q{x0 + bw},{y + 24} {x0 + bw - r},{y + 24} H{x0} Z")
        ratio = actual / budget * 100 if budget else 0
        tip = f"{name}：実績 {fmt(actual)}円・予算（今日まで）{fmt(budget)}円・予算比 {ratio:.0f}%"
        out.append(f'<g class="hit"><title>{E(tip)}</title><rect x="0" y="{y - 8}" width="{W}" height="{rowh - 6}" fill="transparent"/>')
        out.append(f'<text x="{left - 12}" y="{y + 17}" class="lab" text-anchor="end">{E(name)}</text>')
        out.append(f'<path d="{path}" fill="{ACCENT}"/>')
        bx = left + plot * budget / mx
        out.append(f'<line x1="{bx:.1f}" y1="{y - 5}" x2="{bx:.1f}" y2="{y + 29}" class="bud"/>')
        out.append(f'<text x="{max(x0 + bw, bx) + 10:.1f}" y="{y + 17}" class="val">{actual / 10000:,.1f}万円'
                   f'<tspan class="muted">（予算比 {ratio:.0f}%）</tspan></text></g>')
    out.append("</svg>")
    return "".join(out)


def alc_line(pos, out_days):
    """酒類の8週間（営業日）の線。欠品の日は金色のうすい帯。"""
    pts = [(r["日付"], int(r["酒類"])) for r in pos if not r["備考"]][-48:]
    W, H, l, r_, t, b = 1040, 330, 60, 120, 20, 40
    mx, tick = nice(max(v for _, v in pts) * 1.1)
    step = (W - l - r_) / max(1, len(pts) - 1)

    def X(i):
        return l + i * step

    def Y(v):
        return t + (H - t - b) * (1 - v / mx)
    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="酒類の売上の動き（8週間・営業日）">']
    v = 0
    while v <= mx:
        out.append(f'<line x1="{l}" y1="{Y(v):.1f}" x2="{W - r_}" y2="{Y(v):.1f}" class="grid"/>')
        out.append(f'<text x="{l - 8}" y="{Y(v) + 4:.1f}" class="ax" text-anchor="end">{v / 10000:,.0f}万</text>')
        v += tick
    idx = [i for i, (x, _) in enumerate(pts) if x in out_days]
    if idx:
        a, z = min(idx), max(idx)
        out.append(f'<rect x="{X(a) - step / 2:.1f}" y="{t}" width="{(z - a + 1) * step:.1f}" height="{H - t - b}" fill="{ACCENT}" opacity="0.14"/>')
        out.append(f'<text x="{X(a) - step / 2 - 8:.1f}" y="{t + 16}" class="note" text-anchor="end">播磨ゴールド 在庫0 →</text>')
    line = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, (_, v) in enumerate(pts))
    out.append(f'<polyline points="{line}" class="ln"/>')
    for i, (x, v) in enumerate(pts):
        dd = d(x)
        out.append(f'<g class="hit"><title>{jp(dd)} 酒類 {fmt(v)}円</title><rect x="{X(i) - step / 2:.1f}" y="{t}" width="{step:.1f}" '
                   f'height="{H - t - b}" fill="transparent"/><circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="4" class="dot"/></g>')
        if dd.weekday() == 0 or i == 0:
            out.append(f'<text x="{X(i):.1f}" y="{H - 14}" class="ax" text-anchor="middle">{dd.month}/{dd.day}</text>')
    lx, lv = len(pts) - 1, pts[-1][1]
    out.append(f'<circle cx="{X(lx):.1f}" cy="{Y(lv):.1f}" r="5" class="end"/>')
    out.append(f'<text x="{X(lx) + 12:.1f}" y="{Y(lv) + 5:.1f}" class="val">{lv / 10000:,.1f}万円</text>')
    out.append("</svg>")
    return "".join(out)


def build(paths: Paths) -> str:
    S = load_state(paths)
    D = paths.data
    today = d(S["今日"])
    j = read_csv(D / "accounting/日計表.csv")
    pos = read_csv(D / "store/POS_日別.csv")
    y = j[-1]
    last_open = next(r for r in reversed(pos) if not r["備考"])
    mk = ym(today)
    mt = [r for r in j if r["日付"].startswith(mk)]
    bt = sim.budget_to_date(paths, today) or {}
    act = {k: sum(int(r["売上_" + k]) for r in mt) for k in ("店舗", "配達", "EC", "法人", "ギフト")}
    tot = sum(act.values())
    ratio = tot / bt["合計"] * 100 if bt.get("合計") else 0
    pr = float(last_open["前年同曜日の合計"] or 0)
    tiles = [
        tile("昨日の売上（全事業）", f"{int(y['売上合計']) / 10000:,.1f}<small>万円</small>",
             f"{jp(d(y['日付']))}" + ("・店は定休日" if not is_open(d(y["日付"])) else f"・うち店 {int(y['売上_店舗']) / 10000:,.1f}万円")),
        tile("客数（店・直近の営業日）", f"{int(last_open['客数'])}<small>人</small>", f"{jp(d(last_open['日付']))}・目標 105人以上"),
        tile("客単価（店）", f"{int(last_open['客単価']):,}<small>円</small>",
             f"店の売上 {int(last_open['合計']) / 10000:,.1f}万円（前年同曜日比 {(int(last_open['合計']) / pr - 1) * 100:+.0f}%）" if pr else ""),
        tile("今月の予算比", f"{ratio:.1f}<small>%</small>", f"{today.month}/1〜昨日 {tot / 10000:,.1f}万円／予算 {bt.get('合計', 0) / 10000:,.1f}万円"),
        tile("現金", f"{S['現金'] / 10000:,.0f}<small>万円</small>", "今朝の残高"),
    ]
    rows = [(k, act[k], bt.get(k, 0)) for k in ("店舗", "配達", "法人", "EC", "ギフト")]
    it = read_csv(D / "store/POS_商品別_直近14日.csv")
    out_days = {r["日付"] for r in it if r["商品ID"] == "S01" and int(r["数量"] or 0) == 0}
    # 欠品と入荷待ち
    stock_rows = []
    for iid, q in S["在庫"].items():
        if iid in ITEM and iid not in DAILY_FRESH and (q <= 0 or q < reorder_point(iid)):
            pend = [o for o in S["発注"] if o["商品ID"] == iid and o["状態"] == "未入荷"]
            how = "承認がいる" if ITEM[iid][8] in MANUAL_SUPPLIERS else "自動"
            if how == "自動" and pend and q > 0:
                continue                                   # 定期の自動発注で入荷を待っているだけ
            ps = "・".join(f"{jp(d(o['入荷予定日']))} {qty_s(iid, o['数量'])}" for o in pend) or "<b>手配なし</b>"
            stock_rows.append(f"<tr><td>{E(ITEM[iid][1])}</td><td class='n'>{qty_s(iid, q)}</td><td class='n'>{qty_s(iid, reorder_point(iid))}</td>"
                              f"<td>{ps}</td><td>{how}</td></tr>")
    arrivals = [o for o in S["発注"] if o["状態"] == "未入荷" and o["発注者"] != "定期（自動）"]
    for o in arrivals:
        if not any(E(o["商品"]) in r for r in stock_rows):
            stock_rows.append(f"<tr><td>{E(o['商品'])}</td><td class='n'>{qty_s(o['商品ID'], S['在庫'].get(o['商品ID'], 0))}</td>"
                              f"<td class='n'>{qty_s(o['商品ID'], reorder_point(o['商品ID']))}</td>"
                              f"<td>{jp(d(o['入荷予定日']))} {qty_s(o['商品ID'], o['数量'])}</td><td>承認ずみ</td></tr>")
    over = [r for r in read_csv(D / "accounting/売掛金.csv") if r["期日から何日過ぎたか"]]
    over_rows = "".join(f"<tr><td>{E(r['取引先'])}</td><td>{r['請求の月']}</td><td class='n'>{fmt(r['請求額'])}</td>"
                        f"<td class='n'><b>{r['期日から何日過ぎたか']}日</b></td></tr>" for r in over)
    pend = sorted(approvals.load_all(paths.pending), key=approvals.sort_key)
    pend_rows = "".join(f"<tr><td>{E(str(fm.get('期限', ''))[5:16])}</td><td>{E(fm.get('件名', ''))}</td><td class='n'>{fmt(fm.get('金額', 0))}</td>"
                        f"<td>{E(fm.get('担当AI', ''))}</td></tr>" for _, fm, _ in pend[:6])
    ev = next((e for e in S["行事"] if d(e["日付"]) >= today), None)
    ev_s = f"次の行事：{jp(d(ev['日付']))} {E(ev['名前'])}" if ev else ""
    css = f"""
:root{{--ink:#141414;--ink2:#4a4a4a;--muted:#8a8a8a;--line:#e8e8e6;--surface:#ffffff;--accent:{ACCENT}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--surface);color:var(--ink);font-family:"Noto Sans JP","Hiragino Sans","Hiragino Kaku Gothic ProN","Yu Gothic",system-ui,sans-serif}}
.wrap{{max-width:1920px;margin:0 auto;padding:36px 48px;display:grid;gap:22px}}
header{{display:flex;align-items:baseline;justify-content:space-between;border-bottom:2px solid var(--ink);padding-bottom:12px}}
h1{{font-size:34px;margin:0;font-weight:800;letter-spacing:.02em}} h1 span{{color:var(--muted);font-weight:500;font-size:20px;margin-left:12px}}
.meta{{color:var(--ink2);font-size:18px}} .meta b{{color:var(--ink)}}
.tiles{{display:grid;grid-template-columns:repeat(5,1fr);gap:18px}}
.tile{{border:1px solid var(--line);border-radius:14px;padding:18px 22px}}
.tile:first-child{{border-top:4px solid var(--accent)}}
.tl{{font-size:17px;color:var(--ink2)}} .tv{{font-size:52px;font-weight:800;line-height:1.15;margin-top:4px}} .tv small{{font-size:20px;font-weight:600;margin-left:4px}}
.ts{{font-size:15px;color:var(--muted);margin-top:4px}}
.row{{display:grid;grid-template-columns:780px 1fr;gap:22px}}
.row3{{display:grid;grid-template-columns:1fr 1fr 1.2fr;gap:22px}}
.card{{border:1px solid var(--line);border-radius:14px;padding:16px 22px}}
h2{{font-size:20px;margin:0 0 8px;font-weight:700}} h2 small{{font-weight:400;color:var(--muted);font-size:15px;margin-left:8px}}
.legend{{font-size:14px;color:var(--ink2);display:flex;gap:18px;margin-bottom:4px}}
.sw{{display:inline-block;width:14px;height:14px;border-radius:3px;background:var(--accent);vertical-align:-2px;margin-right:6px}}
.tick{{display:inline-block;width:2px;height:16px;background:var(--ink);vertical-align:-3px;margin-right:6px}}
table{{width:100%;border-collapse:collapse;font-size:16px}} th{{text-align:left;color:var(--muted);font-weight:500;border-bottom:1px solid var(--line);padding:6px 4px}}
td{{padding:7px 4px;border-bottom:1px solid var(--line)}} th,td{{white-space:nowrap}} td:first-child{{white-space:normal}} td.n,th.n{{text-align:right;font-variant-numeric:tabular-nums}}
.empty{{color:var(--muted);font-size:16px;padding:8px 0}}
svg text{{font-family:inherit}} .grid{{stroke:var(--line);stroke-width:1}} .ax{{fill:var(--muted);font-size:13px}}
.lab{{fill:var(--ink);font-size:17px;font-weight:600}} .val{{fill:var(--ink);font-size:16px;font-weight:700}} .muted{{fill:var(--muted);font-weight:400}}
.bud{{stroke:var(--ink);stroke-width:2}} .ln{{fill:none;stroke:var(--ink);stroke-width:2;stroke-linejoin:round;stroke-linecap:round}}
.dot{{fill:var(--ink);stroke:var(--surface);stroke-width:2;opacity:0}} .hit:hover .dot{{opacity:1}} .hit:hover rect{{fill:rgba(0,0,0,.03)}}
.end{{fill:var(--accent);stroke:var(--surface);stroke-width:2}} .note{{fill:var(--ink2);font-size:14px;font-weight:600}}
footer{{color:var(--muted);font-size:13px}}
@media (max-width:1200px){{.tiles{{grid-template-columns:repeat(2,1fr)}}.row,.row3{{grid-template-columns:1fr}}.wrap{{padding:16px}}}}
"""
    body = f"""<div class="wrap">
<header><h1>やまだ商店 経営ダッシュボード<span>架空のサンプル企業</span></h1>
<div class="meta"><b>{jp(today)}の朝</b>（データは昨日まで）　{ev_s}</div></header>
<section class="tiles">{''.join(tiles)}</section>
<section class="row">
 <div class="card"><h2>事業別の今月の売上<small>{today.month}/1〜昨日</small></h2>
  <div class="legend"><span><i class="sw"></i>実績</span><span><i class="tick"></i>予算（今日までの分）</span></div>{biz_bars(rows)}</div>
 <div class="card"><h2>酒類の売上（8週間・営業日）<small>点にさわると日ごとの数字</small></h2>{alc_line(pos, out_days)}</div>
</section>
<section class="row3">
 <div class="card"><h2>欠品・発注点割れと入荷待ち</h2>
  {('<table><tr><th>商品</th><th class="n">在庫</th><th class="n">発注点</th><th>入荷待ち</th><th>発注</th></tr>' + ''.join(stock_rows[:6]) + '</table>') if stock_rows else '<div class="empty">なし</div>'}</div>
 <div class="card"><h2>期日を過ぎた売掛金</h2>
  {('<table><tr><th>取引先</th><th>請求の月</th><th class="n">金額</th><th class="n">過ぎた日数</th></tr>' + over_rows + '</table>') if over_rows else '<div class="empty">なし</div>'}</div>
 <div class="card"><h2>承認待ち<small>{len(pend)}件・期限が近い順</small></h2>
  {('<table><tr><th>期限</th><th>件名</th><th class="n">金額</th><th>担当</th></tr>' + pend_rows + '</table>') if pend_rows else '<div class="empty">承認待ちはありません</div>'}</div>
</section>
<footer>株式会社やまだ商店はサンプル企業で実在しません。数字は tools/sim.py が作った架空のデータ（円・税抜）。作成 {dt.datetime.now():%Y-%m-%d %H:%M}</footer>
</div>"""
    return (f'<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>やまだ商店 ダッシュボード</title><style>{css}</style></head><body>{body}</body></html>")


def main(argv=None):
    ap = argparse.ArgumentParser(description="ダッシュボードを作る（reports/dashboard.html）")
    ap.add_argument("--root")
    ap.add_argument("--open", action="store_true")
    a = ap.parse_args(argv)
    paths = Paths(a.root)
    paths.reports.mkdir(parents=True, exist_ok=True)
    data = build_data(paths)
    js = paths.reports / "dashboard_data.json"
    js.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    out = paths.reports / "dashboard.html"
    tpl = paths.root / "tools/dashboard_template.html"
    if tpl.exists() and MARKER in tpl.read_text(encoding="utf-8"):
        inline = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
        out.write_text(tpl.read_text(encoding="utf-8").replace(MARKER, f"<script>window.DASH = {inline};</script>"), encoding="utf-8")
        kind = "テンプレートから"
    else:
        out.write_text(build(paths), encoding="utf-8")
        kind = "簡単な版"
    print(f"作りました：{js}（{js.stat().st_size:,} バイト）")
    print(f"作りました：{out}（{out.stat().st_size:,} バイト・{kind}）")
    if a.open:
        subprocess.run(["open", str(out)], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
