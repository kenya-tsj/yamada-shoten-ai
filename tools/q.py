#!/usr/bin/env python3
"""やまだ商店（架空）の数字を早く見るための道具。読むだけ（何も書かない）。

    python3 tools/q.py 一覧          使える名前の一覧
    python3 tools/q.py 全体          全体の数字（昨日・直近7日・今月の予算比・先月・12か月）
    python3 tools/q.py 店舗          部門別・客数・落ちた商品・欠品（AI店長）
    python3 tools/q.py 仕入れ        在庫0・発注点割れ・入荷待ち・発注の抜け・行事に間に合う締め（AI仕入れ）
    python3 tools/q.py 経理          先月の損益と予算比・事業別・売掛金・資金繰り（AI経理）
    …ほか：期日超過・EC・配達・受付・法人・広告・口コミ・広報・法務・KPI・承認待ち・表

各部の AI は、まず自分の名前を1回だけ呼ぶ。足りないときだけ data/ を読む。
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import WD, Paths, add_business_days, add_months, d, fmt, is_open, jp, load_state, month_last, read_csv, ym  # noqa: E402
from sim_model import CUST, CUSTOMERS, DAILY_FRESH, ITEM, ITEMS, MANUAL_SUPPLIERS, STAFF_HOURS, qty_s, unit  # noqa: E402

TARGET = {"粗利率": 30.0, "客数": 105, "客単価": 1050, "欠品率": 1.0, "在庫日数": 10.0, "廃棄率": 6.0, "EC購入率": 2.0,
          "ROAS": 3.3, "回収日数": 45, "人時売上": 3700, "配達1件の原価": 700}


class Q:
    def __init__(self, paths: Paths):
        self.p = paths
        self.D = paths.data
        self.S = load_state(paths)
        self.today = d(self.S["今日"])
        self.yday = self.today - dt.timedelta(days=1)
        self._c = {}

    def t(self, rel):
        if rel not in self._c:
            self._c[rel] = read_csv(self.D / rel)
        return self._c[rel]

    def days(self, n, end=None):
        end = end or self.yday
        return [(end - dt.timedelta(days=i)).isoformat() for i in range(n - 1, -1, -1)]

    def sumcol(self, rel, col, dates, cond=None):
        ds = set(dates)
        return sum(float(r[col] or 0) for r in self.t(rel) if r["日付"] in ds and (cond is None or cond(r)))

    def prior(self):
        if "prior" not in self._c:
            self._c["prior"] = {r["日付"]: r for r in read_csv(self.p.prior)}
        return self._c["prior"]


def pct(a, b):
    return f"{(a / b - 1) * 100:+.1f}%" if b else "―"


def ratio(a, b):
    return f"{a / b * 100:.1f}%" if b else "―"


BIZ = [("店舗", "売上_店舗"), ("配達", "売上_配達"), ("EC", "売上_EC"), ("ギフト", "売上_ギフト"), ("法人", "売上_法人")]


def prior_sum(q, dates):
    pr = q.prior()
    out = {"店舗": 0, "配達": 0, "EC": 0, "ギフト": 0}
    for x in dates:
        r = pr.get(x)
        if r:
            out["店舗"] += int(r["店の合計"])
            out["配達"] += int(r["配達の売上"])
            out["EC"] += int(r["ECの売上"])
            out["ギフト"] += sum(int(r[f"ギフト_{c}_売上"]) for c in ("店頭", "電話", "ネット", "法人"))
    return out


# ── 全体 ─────────────────────────────────────────────────
def q_zentai(q: Q):
    import sim
    J = "accounting/日計表.csv"
    y = q.t(J)[-1]
    print(f"■ 全体（今日＝{jp(q.today)}・データは昨日まで）")
    note = "（定休日）" if not is_open(q.yday) else ""
    print(f"昨日 {jp(q.yday)}{note}：合計 {fmt(y['売上合計'])}円｜" + "・".join(f"{k} {fmt(y[c])}" for k, c in BIZ))
    if not is_open(q.yday):
        last_open = next(r for r in reversed(q.t(J)) if is_open(d(r["日付"])))
        print(f"  直近の営業日 {jp(d(last_open['日付']))}：合計 {fmt(last_open['売上合計'])}円｜" + "・".join(f"{k} {fmt(last_open[c])}" for k, c in BIZ))
    w1, w0 = q.days(7), q.days(7, q.yday - dt.timedelta(days=7))
    pr = prior_sum(q, w1)
    print("\n直近7日（前の7日・前年の同じ7日と比べる）")
    print("| 事業 | 直近7日 | 前週比 | 前年比 |")
    print("|---|---|---|---|")
    tot1 = tot0 = totp = 0
    for k, c in BIZ:
        a, b = q.sumcol(J, c, w1), q.sumcol(J, c, w0)
        p = pr.get(k)
        tot1 += a
        tot0 += b
        totp += (p or 0) + (a if p is None else 0)
        print(f"| {k} | {fmt(a)} | {pct(a, b)} | {pct(a, p) if p is not None else '（前年データなし）'} |")
    print(f"| 合計 | {fmt(tot1)} | {pct(tot1, tot0)} | {pct(tot1, totp)}（法人は前年なしのため同じ額で計算） |")
    if pr.get("ギフト") is not None and pr["ギフト"] and q.sumcol(J, "売上_ギフト", w1) > pr["ギフト"] * 3:
        print("※ギフトの前年比が大きいのは、去年の店頭・電話のお歳暮の受付が11/20からだったため（今年は10/20から）")
    gp = q.sumcol(J, "粗利", w1)
    lost = q.sumcol(J, "欠品で逃した売上", w1)
    print(f"粗利 {fmt(gp)}円（粗利率 {ratio(gp, tot1)}）・欠品で逃した売上 {fmt(lost)}円")
    mk = ym(q.today)
    mt = [r["日付"] for r in q.t(J) if r["日付"].startswith(mk)]
    bt = sim.budget_to_date(q.p, q.today)
    if mt and bt:
        print(f"\n今月（{q.today.month}/1〜昨日）：予算は去年の同じ日の動きで割り振った「今日までの分」")
        print("| 事業 | 実績 | 予算（今日まで） | 予算比 |")
        print("|---|---|---|---|")
        tot = 0
        for k, c in BIZ:
            a = q.sumcol(J, c, mt)
            tot += a
            print(f"| {k} | {fmt(a)} | {fmt(bt[k])} | {ratio(a, bt[k])} |")
        print(f"| 合計 | {fmt(tot)} | {fmt(bt['合計'])} | {ratio(tot, bt['合計'])} |")
    pl = q.t("accounting/月次PL.csv")
    bud = {r["月"]: r for r in q.t("accounting/予算.csv")}
    if pl:
        r = pl[-1]
        b = bud.get(r["月"])
        print(f"\n先月（{r['月']}）：売上 {fmt(r['売上合計'])}円（予算比 {ratio(float(r['売上合計']), float(b['売上合計'])) if b else '―'}・"
              f"前年比 {pct(float(r['売上合計']), float(r['前年同月の売上合計'] or 0))}）・粗利率 {r['粗利率(%)']}%・営業利益 {fmt(r['営業利益'])}円"
              + (f"（予算 {fmt(b['営業利益'])}円）" if b else ""))
        last12 = pl[-12:]
        s12 = sum(float(x["売上合計"]) for x in last12)
        p12 = sum(float(x["前年同月の売上合計"] or 0) for x in last12)
        print(f"直近12か月（{last12[0]['月']}〜{last12[-1]['月']}）：売上 {fmt(s12)}円（前年比 {pct(s12, p12)}）・"
              f"営業利益 {fmt(sum(float(x['営業利益']) for x in last12))}円")
    print(f"現金 {fmt(q.S['現金'])}円")


# ── 店舗 ─────────────────────────────────────────────────
def q_tenpo(q: Q):
    P = "store/POS_日別.csv"
    rows = q.t(P)
    w1, w0 = q.days(7), q.days(7, q.yday - dt.timedelta(days=7))
    y = rows[-1]
    print(f"■ 店舗（今日＝{jp(q.today)}）")
    if y["備考"]:
        y2 = next(r for r in reversed(rows) if not r["備考"])
        print(f"昨日 {jp(q.yday)} は{y['備考']}。直近の営業日 {jp(d(y2['日付']))}：合計 {fmt(y2['合計'])}円・客 {y2['客数']}人・客単価 {fmt(y2['客単価'])}円")
    else:
        print(f"昨日 {jp(q.yday)} {y['天気']}：合計 {fmt(y['合計'])}円（前年同曜日 {fmt(y['前年同曜日の合計'] or 0)}円 {pct(float(y['合計']), float(y['前年同曜日の合計'] or 0))}）"
              f"・客 {y['客数']}人・客単価 {fmt(y['客単価'])}円")
    print("\n直近7日（前の7日・前年同曜日と比べる）")
    print("| 部門 | 直近7日 | 前週比 |")
    print("|---|---|---|")
    for c in ("食料品", "日用品", "酒類", "合計"):
        a, b = q.sumcol(P, c, w1), q.sumcol(P, c, w0)
        print(f"| {c} | {fmt(a)} | {pct(a, b)} |")
    a, p = q.sumcol(P, "合計", w1), q.sumcol(P, "前年同曜日の合計", w1)
    op1 = [r for r in rows if r["日付"] in set(w1) and not r["備考"]]
    op0 = [r for r in rows if r["日付"] in set(w0) and not r["備考"]]
    c1 = sum(int(r["客数"]) for r in op1) / max(1, len(op1))
    c0 = sum(int(r["客数"]) for r in op0) / max(1, len(op0))
    print(f"前年同週比 {pct(a, p)}・客数 1日 {c1:.0f}人（前週 {c0:.0f}人）・客単価 {fmt(a / max(1, sum(int(r['客数']) for r in op1)))}円")
    alc = [r for r in rows if not r["備考"]][-12:]
    print("酒類の日ごと（直近12営業日）：" + "　".join(f"{d(r['日付']).month}/{d(r['日付']).day} {int(r['酒類']) // 1000}千" for r in alc))
    it = q.t("store/POS_商品別_直近14日.csv")
    dates = sorted({r["日付"] for r in it})
    recent, before = set(dates[-5:]), set(dates[:-5])
    drops = []
    for iid, name, *_ in ITEMS:
        a = sum(int(r["数量"] or 0) for r in it if r["商品ID"] == iid and r["日付"] in recent) / max(1, len(recent))
        b = sum(int(r["数量"] or 0) for r in it if r["商品ID"] == iid and r["日付"] in before) / max(1, len(before))
        if b >= 1 and a < b * 0.7:
            zero = [x for x in sorted(recent) if not any(int(r["数量"] or 0) for r in it if r["商品ID"] == iid and r["日付"] == x)]
            drops.append((b - a) * ITEM[iid][4])
            drops[-1] = ((b - a) * ITEM[iid][4], f"- {name}：1日 {b:.1f}{unit(iid)} → {a:.1f}{unit(iid)}" + (f"（{jp(d(zero[0]))}から0）" if len(zero) >= 2 else ""))
    print("\n落ちた商品（直近5営業日とその前を比べる）")
    for _, line in sorted(drops, reverse=True)[:5]:
        print(line)
    if not drops:
        print("- 目立って落ちた商品はない")
    st = q.S["在庫"]
    outs = [ITEM[i][1] for i in st if st[i] <= 0]
    print(f"\n在庫0：{'・'.join(outs) if outs else 'なし'}")
    lost = q.sumcol("accounting/日計表.csv", "欠品で逃した売上", w1)
    print(f"欠品で逃した売上（直近7日）：{fmt(lost)}円")
    ev = next((e for e in q.S["行事"] if d(e["日付"]) >= q.today), None)
    if ev:
        print(f"次の行事：{jp(d(ev['日付']))} {ev['名前']}（倍率 {ev['倍率']}・屋台 {'あり' if ev['屋台'] else 'なし'}・告知 {'済み' if ev['告知'] else 'まだ'}）")


# ── 仕入れ ────────────────────────────────────────────────
def q_shiire(q: Q):
    inv = {r["商品ID"]: r for r in q.t("purchasing/在庫.csv")}
    orders = q.S["発注"]
    it14 = q.t("store/POS_商品別_直近14日.csv")
    print(f"■ 仕入れ（{jp(q.today)}の朝の在庫）")

    def usual(iid):
        sold_days = [int(r["数量"] or 0) for r in it14 if r["商品ID"] == iid and int(r["数量"] or 0) > 0]
        return sum(sold_days) / len(sold_days) if sold_days else ITEM[iid][6]

    def pend(iid):
        ps = [o for o in orders if o["商品ID"] == iid and o["状態"] == "未入荷"]
        return "・".join(f"{jp(d(o['入荷予定日']))}に{qty_s(iid, o['数量'])}" for o in ps)

    print("手を打つ品：在庫0・発注点割れ（定期で入荷を待っているだけの品と、毎日の生ものは除く）")
    print("※数は「単位」で数える。例：播磨ゴールド（350ml×6缶パック）の 80パック＝6缶入りが80個")
    print("| 商品 | 在庫 | 発注点 | 売れる日の1日平均 | 仕入先 | 発注の決め方 | 入荷待ち |")
    print("|---|---|---|---|---|---|---|")
    flagged = []
    for iid, r in inv.items():
        if iid not in ITEM or iid in DAILY_FRESH:
            continue
        stock, rop = int(r["在庫（今朝）"]), int(r["発注点"] or 0)
        manual = ITEM[iid][8] in MANUAL_SUPPLIERS
        if stock <= 0 or (stock < rop and (manual or not pend(iid))):
            flagged.append(iid)
            print(f"| {ITEM[iid][1]} | {qty_s(iid, stock)} | {qty_s(iid, rop)} | {usual(iid):.1f}{unit(iid)} | {ITEM[iid][8]} | "
                  f"{'承認がいる' if manual else '定期（自動）'} | {pend(iid) or 'なし'} |")
    if not flagged:
        print("| なし | | | | | | |")
    print("\nいつもの手配の抜け（承認がいる仕入先・直近4週）")
    for sup in MANUAL_SUPPLIERS:
        os_ = sorted([o for o in orders if o["仕入先"] == sup], key=lambda o: o["発注日"])
        if not os_:
            continue
        last = d(os_[-1]["発注日"])
        gap = (q.today - last).days
        print(f"- {sup}：最後の発注 {jp(last)}（{gap}日前）" + ("　←いつもは週1回。抜けている" if gap > 8 else ""))
    evs = [e for e in q.S["行事"] if d(e["日付"]) >= q.today and e["倍率"] > 1]
    for e in evs:
        x = d(e["日付"])
        need = x - dt.timedelta(days=1)
        print(f"\n行事：{jp(x)} {e['名前']}（酒類と飲料 約{e['倍率']}倍・屋台 {'あり' if e['屋台'] else 'なし'}）。前日 {jp(need)} までに入れるには：")
        for sup, lead, cut in (("播磨麦酒（架空）", 3, "平日15時"),):
            last_ok = None
            y = q.today
            while y < need:
                arr = add_business_days(y, lead) if sup.startswith("播磨") else y + dt.timedelta(days=lead)
                if (y.weekday() < 5 or not sup.startswith("播磨")) and arr <= need:
                    last_ok = y
                y += dt.timedelta(days=1)
            msg = f"{jp(last_ok)}の{cut}まで" + ("　←今日が最後" if last_ok == q.today else "") if last_ok else "もう間に合わない"
            print(f"- {sup}（{'3営業日・土日は配送なし' if sup.startswith('播磨') else '3日'}）：{msg}")
    print("\n手配の目安（承認がいる仕入先の品目）＝売れる日の1日平均 ×（次の入荷までの日数＋7日）＋行事の上乗せ")
    for iid in flagged:
        if ITEM[iid][8] not in MANUAL_SUPPLIERS:
            continue
        u = usual(iid)
        extra = 0
        if evs and iid == "S01":
            extra = 25 + int(round(u * (evs[0]["倍率"] - 1)))
        qty = int(round(u * (ITEM[iid][9] + 7) + extra))
        print(f"- {ITEM[iid][1]}：{u:.1f}{unit(iid)} ×（{ITEM[iid][9]}＋7日）＋{extra} ≒ {qty_s(iid, qty)}（原価 {fmt(qty * ITEM[iid][5])}円）")
    auto = [o for o in orders if o["状態"] == "未入荷" and o["発注者"] == "定期（自動）"]
    if auto:
        print("\n定期（自動）で入荷待ち：" + "・".join(f"{o['商品']} {qty_s(o['商品ID'], o['数量'])}（{jp(d(o['入荷予定日']))}）" for o in auto[:8])
              + (f" ほか{len(auto) - 8}件" if len(auto) > 8 else ""))


# ── 経理 ─────────────────────────────────────────────────
def q_keiri(q: Q):
    pl = q.t("accounting/月次PL.csv")
    bud = {r["月"]: r for r in q.t("accounting/予算.csv")}
    r = pl[-1]
    b = bud.get(r["月"])
    print(f"■ 経理（今日＝{jp(q.today)}）")
    print(f"先月 {r['月']}：売上 {fmt(r['売上合計'])}円（予算比 {ratio(float(r['売上合計']), float(b['売上合計'])) if b else '―'}・前年比 "
          f"{pct(float(r['売上合計']), float(r['前年同月の売上合計'] or 0))}）・粗利 {fmt(r['粗利'])}円（{r['粗利率(%)']}%）・"
          f"営業利益 {fmt(r['営業利益'])}円（予算 {fmt(b['営業利益']) if b else '―'}円）")
    print("| 事業 | 売上 | 予算 | 予算比 | 粗利率 |")
    print("|---|---|---|---|---|")
    for k in ("店舗", "配達", "EC", "法人", "ギフト"):
        s = float(r["売上_" + k])
        bb = float(b["売上_" + k]) if b else 0
        print(f"| {k} | {fmt(s)} | {fmt(bb)} | {ratio(s, bb)} | {ratio(float(r['粗利_' + k]), s)} |")
    last12 = pl[-12:]
    s12 = sum(float(x["売上合計"]) for x in last12)
    p12 = sum(float(x["前年同月の売上合計"] or 0) for x in last12)
    print(f"直近12か月：売上 {fmt(s12)}円（前年比 {pct(s12, p12)}）・営業利益 {fmt(sum(float(x['営業利益']) for x in last12))}円")
    import sim
    bt = sim.budget_to_date(q.p, q.today)
    mt = [x["日付"] for x in q.t("accounting/日計表.csv") if x["日付"].startswith(ym(q.today))]
    if mt and bt:
        s = q.sumcol("accounting/日計表.csv", "売上合計", mt)
        print(f"今月（{q.today.month}/1〜昨日）：売上 {fmt(s)}円（予算の今日までの分 {fmt(bt['合計'])}円・予算比 {ratio(s, bt['合計'])}）")
    print()
    q_kijitsu(q, short=True)
    cf = q.t("accounting/資金繰り.csv")
    v = {x["項目"]: x for x in cf}
    cols = list(cf[0].keys())
    print(f"\n資金繰り：今の残高 {fmt(q.S['現金'])}円 → 今月末の見込み {fmt(v['月末の残高（見込み）'][cols[2]])}円 → 来月末の見込み "
          f"{fmt(v['月末の残高（見込み）'][cols[3]])}円")
    memo = v.get("法人の売掛金の回収", {}).get("メモ")
    if memo:
        print(f"  ※{memo}")
    ap = sum(float(x["金額"]) for x in q.t("accounting/買掛金.csv") if x["状態"] == "支払い予定")
    print(f"今月末に払う仕入れ（買掛金）：{fmt(ap)}円")


def q_kijitsu(q: Q, short=False):
    rows = [r for r in q.t("accounting/売掛金.csv") if r["期日から何日過ぎたか"]]
    if not short:
        print(f"■ 期日を過ぎた売掛金（今日＝{jp(q.today)}）")
    if not rows:
        print("期日を過ぎた売掛金：なし")
        return
    print("期日を過ぎた売掛金")
    print("| 取引先 | 請求の月 | 金額 | 支払期日 | 何日過ぎたか | 状態 |")
    print("|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['取引先']} | {r['請求の月']} | {fmt(r['請求額'])} | {r['支払期日']} | {r['期日から何日過ぎたか']}日 | {r['状態']} |")
    tot = sum(float(r["請求額"]) for r in rows)
    who = sorted({r["取引先ID"] for r in rows})
    ship = q.t("b2b/納品_日別.csv")
    for cid in who:
        n = [x for x in ship if x["取引先ID"] == cid and x["日付"] >= (q.today - dt.timedelta(days=14)).isoformat()]
        print(f"合計 {fmt(tot)}円。{CUST[cid][1]} への納品は直近14日で {len(n)}回・{fmt(sum(float(x['金額']) for x in n))}円（出荷は続いている）")
    late = [r for r in q.t("accounting/売掛金.csv") if "遅れ" in r["状態"]]
    for r in late:
        print(f"前にも遅れ：{r['取引先']} {r['請求の月']}分は{r['状態']}")
    c = [x for x in q.t("legal/契約.csv") if any(CUST[w][1] == x["相手"] for w in who) and x["メモ"]]
    for x in c:
        print(f"契約：{x['相手']}「{x['メモ']}」")


# ── EC ──────────────────────────────────────────────────
def q_ec(q: Q):
    E = "ec/注文_日別.csv"
    w1, w0, w28, w280 = q.days(7), q.days(7, q.yday - dt.timedelta(days=7)), q.days(28), q.days(28, q.yday - dt.timedelta(days=28))
    print(f"■ ネットショップとギフト（今日＝{jp(q.today)}）")
    for label, a_, b_ in (("直近7日", w1, w0), ("直近28日", w28, w280)):
        s, s0 = q.sumcol(E, "売上", a_), q.sumcol(E, "売上", b_)
        o, v = q.sumcol(E, "注文数", a_), q.sumcol(E, "訪問数", a_)
        py = q.sumcol(E, "前年同曜日の売上", a_)
        print(f"{label}：売上 {fmt(s)}円（前の期間比 {pct(s, s0)}・前年比 {pct(s, py)}）・注文 {int(o)}件・購入率 {ratio(o, v)}")
    f1 = {c: q.sumcol(E, c, w1) for c in ("流入_検索", "流入_Instagram", "流入_直接", "流入_その他")}
    f0 = {c: q.sumcol(E, c, w0) for c in f1}
    print("流入（直近7日・前週比・自社サイトは GA4）：" + "・".join(f"{c[3:]} {int(v)}（{pct(v, f0[c])}）" for c, v in f1.items()))
    ch = channel_month(q)
    print(f"\nネット3店（今月 {q.today.month}/1〜昨日・通常＋ギフトのネット分・架空の連携）")
    print("| 店 | 注文 | 売上 | 手数料 | 割合 |")
    print("|---|---|---|---|---|")
    tot = sum(c["value"] for c in ch) or 1
    for c in ch:
        print(f"| {c['name']} | {c['orders']}件 | {fmt(c['value'])}円 | {fmt(c['fee'])}円 | {c['value'] / tot * 100:.0f}% |")
    g = q.t("gift/ギフト受注_週別.csv")
    if g:
        print(f"\nギフト（{g[0]['シーズン']}・{g[0]['週の初め（月曜）']}の週から昨日まで）")
        print("| 受付 | 件数 | 売上 | 前年同期の件数 | 前年比 |")
        print("|---|---|---|---|---|")
        for ch in ("店頭", "電話", "ネット", "法人"):
            n = sum(int(r["件数（送り先の数）"]) for r in g if r["受付"] == ch)
            s = sum(int(r["売上"]) for r in g if r["受付"] == ch)
            p = sum(int(r["前年同週の件数"]) for r in g if r["受付"] == ch)
            print(f"| {ch} | {n} | {fmt(s)} | {p} | {pct(n, p) if p else '去年はこの時期まだ受付前'} |")
    pages = q.t("ec/商品ページ.csv")
    print("\n商品ページ（直近4週・購入は注文の件数・在庫は単位の数）")
    print("| 商品 | 購入 | 前年同期 | 購入率 | サイトの在庫 | 実際の在庫 | 未出荷 | 20歳未満の表示 |")
    print("|---|---|---|---|---|---|---|---|")
    for r in pages:
        flag = ""
        if r["サイトに出ている在庫"].isdigit() and r["サイトに出ている在庫"] != r["実際の在庫（今朝）"]:
            flag = " ←ずれ"
        u = r["単位"] if r["サイトに出ている在庫"].isdigit() else ""
        print(f"| {r['商品']} | {r['購入数（直近4週）']}件 | {r['前年同期の購入数（4週）']}件 | {r['購入率(%)']}% | {r['サイトに出ている在庫']}{u}{flag} | "
              f"{r['実際の在庫（今朝）']}{u} | {r['まだ出荷していない注文（件）']}件 | {r['「20歳未満の飲酒は法律で禁止」の表示']} |")
    print(f"在庫連動：{'あり（毎日そろう）' if q.S['在庫連動'] else 'なし（手で更新）'}")


def channel_month(q: Q):
    """今月のネット3店の数字（ダッシュボードと同じ計算）。"""
    from sources import EC_CHANNELS
    rows = [r for r in q.t("ec/チャネル別_日別.csv") if r["日付"].startswith(ym(q.today))]
    out = []
    for name, src, _, _ in EC_CHANNELS:
        rs = [r for r in rows if r["チャネル"] == name]
        out.append({"name": name, "value": sum(int(r["売上"]) for r in rs), "orders": sum(int(r["注文数"]) for r in rs),
                    "fee": sum(int(r["手数料"]) for r in rs), "source": src,
                    "通常": sum(int(r["売上"]) for r in rs if r["種類"] == "通常"), "ギフト": sum(int(r["売上"]) for r in rs if r["種類"] == "ギフト")})
    return out


# ── 配達・受付 ─────────────────────────────────────────────
def dl_split(q: Q, weeks=8):
    rows = [r for r in q.t("delivery/配達_日別.csv") if not r["備考"] and r["日付"] >= (q.today - dt.timedelta(days=7 * weeks)).isoformat()]
    rain = [r for r in rows if r["天気"] == "雨"]
    dry = [r for r in rows if r["天気"] != "雨"]

    def avg(rs, k):
        return sum(float(r[k]) for r in rs) / max(1, len(rs))
    return rows, rain, dry, avg


def q_haitatsu(q: Q):
    F = "delivery/配達_日別.csv"
    w1, w0 = q.days(7), q.days(7, q.yday - dt.timedelta(days=7))
    print(f"■ 配達（今日＝{jp(q.today)}）")
    a, b, p = q.sumcol(F, "配達の売上", w1), q.sumcol(F, "配達の売上", w0), q.sumcol(F, "前年同曜日の配達の売上", w1)
    n = q.sumcol(F, "配達件数", w1)
    print(f"直近7日：{int(n)}件・{fmt(a)}円（前週比 {pct(a, b)}・前年比 {pct(a, p)}）")
    rows, rain, dry, avg = dl_split(q, 4)
    tot = sum(float(r["配達件数"]) for r in rows) or 1
    print("\n地区（直近4週）")
    print("| 地区 | 件数 | 割合 |")
    print("|---|---|---|")
    for k in ("東地区", "西地区", "南地区", "北地区（高台の団地）"):
        c = sum(float(r[k]) for r in rows)
        print(f"| {k} | {int(c)} | {c / tot * 100:.0f}% |")
    nm = sum(float(r["うち北地区（分）"]) for r in rows)
    nn = sum(float(r["北地区（高台の団地）"]) for r in rows)
    am = sum(float(r["配達にかかった時間（分）"]) for r in rows)
    print(f"1件あたりの時間：北地区 {nm / max(1, nn):.1f}分・ほか {(am - nm) / max(1, tot - nn):.1f}分")
    a_ = sum(float(r["午前便"]) for r in rows)
    print(f"午前便 {a_ / tot * 100:.0f}%・午後便 {100 - a_ / tot * 100:.0f}%（北地区を午後便にまとめる：{'する' if q.S['配達']['北地区を午後便にまとめる'] else 'していない'}）")
    print(f"雨の日 1日 {avg(rain, '配達件数'):.1f}件 / 雨以外 {avg(dry, '配達件数'):.1f}件（直近4週）")
    uns = q.S["未出荷"]
    print(f"\nネットの未出荷：{len(uns)}件" + ("（" + "・".join(sorted({ITEM[u['商品ID']][1] for u in uns})) + "。在庫が無くて出せない）" if uns else ""))


def q_uketsuke(q: Q):
    print(f"■ 電話の受付（今日＝{jp(q.today)}・直近8週の営業日）")
    rows, rain, dry, avg = dl_split(q, 8)
    print("| 天気 | 日数 | 着信 | 取れなかった電話 | 配達件数 | 午前の着信の割合 |")
    print("|---|---|---|---|---|---|")
    for lab, rs in (("雨", rain), ("雨以外", dry)):
        share = sum(float(r["着信_午前"]) for r in rs) / max(1, sum(float(r["電話の着信"]) for r in rs)) * 100
        print(f"| {lab} | {len(rs)} | {avg(rs, '電話の着信'):.1f} | {avg(rs, '取れなかった電話'):.1f} | {avg(rs, '配達件数'):.1f} | {share:.0f}% |")
    per = sum(float(r["配達の売上"]) for r in rows) / max(1, sum(float(r["配達件数"]) for r in rows))
    lost = (avg(rain, "取れなかった電話") - avg(dry, "取れなかった電話")) * 0.6 * per
    print(f"1件の配達の売上の平均 {fmt(per)}円。雨の日に取れなかった電話の6割が注文だったとすると、1日 約{fmt(lost)}円を取り逃がし")
    import sim
    fc = [(q.today + dt.timedelta(days=i)) for i in range(5)]
    print("天気予報：" + "　".join(f"{jp(x)} {sim.weather(q.S, x)}" for x in fc))
    nxt = next((x for x in fc if sim.weather(q.S, x) == "雨" and is_open(x)), None)
    print(f"次の雨の営業日：{jp(nxt) if nxt else '5日以内はなし'}。午前の電話番を足す：{'する' if q.S['シフト']['雨の日の午前の電話番'] else 'していない'}")
    print("午前の電話はレジ・電話のパート1人（レジと兼務 9:00〜14:00）。お知らせの「雨の日の配達のご案内」で、つながらないときは午後に、とお願いしている")


# ── 法人 ─────────────────────────────────────────────────
def q_houjin(q: Q):
    rows = q.t("b2b/法人売上_月別.csv")
    months = sorted({r["月"] for r in rows})
    m3, p3 = months[-3:], months[-6:-3]
    print(f"■ 法人（直近3か月 {m3[0]}〜{m3[-1]} と、その前の3か月）")
    print("| 取引先 | 直近3か月の月平均 | その前 | 増減 | 1回あたり | 月の納品回数 |")
    print("|---|---|---|---|---|---|")
    for cid, name, *_ in CUSTOMERS:
        a = [r for r in rows if r["取引先ID"] == cid and r["月"] in m3]
        b = [r for r in rows if r["取引先ID"] == cid and r["月"] in p3]
        sa = sum(float(r["売上"]) for r in a) / max(1, len(a))
        sb = sum(float(r["売上"]) for r in b) / max(1, len(b))
        va = sum(float(r["納品回数"]) for r in a) / max(1, len(a))
        print(f"| {name} | {fmt(sa)} | {fmt(sb)} | {pct(sa, sb)} | {fmt(sa / va if va else 0)} | {va:.0f} |")
    mt = [r for r in q.t("b2b/納品_日別.csv") if r["日付"].startswith(ym(q.today))]
    print(f"今月（昨日まで）：{fmt(sum(float(r['金額']) for r in mt))}円・{len(mt)}回")
    for c in q.t("legal/契約.csv"):
        if c["次の更新日"][:4].isdigit() and any(x[1] == c["相手"] for x in CUSTOMERS):
            left = (d(c["次の更新日"]) - q.today).days
            if left <= 90:
                dl = c["条件を変えたいときの申し出期限"]
                print(f"契約：{c['相手']} 次の更新日 {c['次の更新日']}（あと{left}日）" + (f"・条件を変えるなら申し出は {dl} まで（あと{(d(dl) - q.today).days}日）" if dl else "")
                      + f"・状態：{c['状態']}")
    over = [r for r in q.t("accounting/売掛金.csv") if r["期日から何日過ぎたか"]]
    for cid in sorted({r["取引先ID"] for r in over}):
        print(f"支払いの遅れ：{CUST[cid][1]}（経理と話してから提案する）")
    print("いま扱っている介護用品：大人用おむつ（パンツ型）。とろみ剤・介護食は扱いを増やせる（◯◯日用品卸）")


# ── 広告 ─────────────────────────────────────────────────
def q_koukoku(q: Q):
    ads = q.t("marketing/広告.csv")
    pl = q.t("accounting/月次PL.csv")
    gm = float(pl[-1]["粗利率(%)"]) / 100 if pl else 0.3
    months = sorted({r["月"] for r in ads})[-3:]
    print(f"■ 広告（直近3か月・粗利率 {gm * 100:.1f}% で損得を見る。売上÷費用が {1 / gm:.1f} を超えると黒字）")
    print("| 月 | 媒体 | 費用 | 反応 | 反応からの売上 | 売上÷費用 | 粗利で見た損得 |")
    print("|---|---|---|---|---|---|---|")
    for r in ads:
        if r["月"] not in months:
            continue
        cost = float(r["費用"] or 0)
        rev = float(r["反応からの売上"]) if r["反応からの売上"] else None
        pl_ = f"{fmt(rev * gm - cost)}円" if (rev is not None and cost) else "測れない"
        print(f"| {r['月']} | {r['媒体']} | {fmt(cost)} | {r['反応']} {r['反応の中身']} | {fmt(rev) if rev is not None else '―'} | {r['売上÷費用'] or '―'} | {pl_} |")
    a = q.S["広告"]
    print(f"今の配分：チラシ 月{a['チラシの回数']}回（1回 {fmt(a['チラシ1回の費用'])}円）・Instagram広告 月{fmt(a['Instagram広告'])}円・回覧板とポスター 月{fmt(a['回覧板・店頭ポスター'])}円")


# ── 口コミ ────────────────────────────────────────────────
def q_kuchikomi(q: Q):
    rows = q.t("marketing/口コミ.csv")
    r30 = [r for r in rows if r["日付"] >= (q.today - dt.timedelta(days=30)).isoformat()]
    p30 = [r for r in rows if (q.today - dt.timedelta(days=60)).isoformat() <= r["日付"] < (q.today - dt.timedelta(days=30)).isoformat()]

    def av(rs):
        return sum(int(r["星"]) for r in rs) / len(rs) if rs else 0
    print(f"■ 口コミ（今日＝{jp(q.today)}）")
    print(f"直近30日：{len(r30)}件・星の平均 {av(r30):.1f}（その前の30日 {len(p30)}件・{av(p30):.1f}）")
    un = [r for r in rows if r["返信"] == "未返信"]
    print(f"未返信：{len(un)}件（うち星3以下 {sum(1 for r in un if int(r['星']) <= 3)}件）")
    for r in sorted(un, key=lambda r: (int(r["星"]), r["日付"])):
        print(f"- {r['日付']} 星{r['星']}（{r['どこの口コミ']}）{r['本文']}")
    theme = Counter()
    for r in rows:
        if int(r["星"]) <= 3:
            for k, ws in {"品切れ・播磨ゴールド": ("播磨", "無かった", "売り切れ", "まだ入って"), "レジ待ち": ("レジ",), "配達": ("配達",)}.items():
                if any(w in r["本文"] for w in ws):
                    theme[k] += 1
    print("星3以下の中身：" + ("・".join(f"{k} {v}件" for k, v in theme.most_common()) or "なし"))
    print(f"夕方のレジを2人に：{'している' if q.S['シフト']['夕方のレジを2人に'] else 'していない（夕方のレジはパート1人）'}")


# ── 広報 ─────────────────────────────────────────────────
def q_kouhou(q: Q):
    notes = q.S["お知らせ"]
    print(f"■ 広報（今日＝{jp(q.today)}）")
    print("最近出したお知らせ：" + "・".join(f"{n[0]} {n[1]}（{n[2]}）" for n in sorted(notes, reverse=True)[:3]))
    for e in q.S["行事"]:
        x = d(e["日付"])
        if q.today <= x <= q.today + dt.timedelta(days=14) and not e["屋台"]:
            print(f"- {jp(x)} {e['名前']}（あと{(x - q.today).days}日）：店の告知は要らない。売場の準備だけ")
        elif q.today <= x <= q.today + dt.timedelta(days=14):
            key = e["名前"].replace("△△町 ", "")
            hit = [n for n in notes if key in n[1] and n[0] >= (q.today - dt.timedelta(days=30)).isoformat()]
            print(f"- {jp(x)} {e['名前']}（あと{(x - q.today).days}日・屋台 {'あり' if e['屋台'] else 'なし'}）：告知 "
                  + (f"済み（{hit[0][0]}）" if hit else "まだ（サイトにも Instagram にも出ていない）"))
    sns = q.t("marketing/SNS.csv")[-4:]
    print("Instagram（直近4週）：" + "・".join(f"{r['週の初め（月曜）'][5:]} 投稿{r['投稿数']}・リーチ{r['リーチ']}・{r['主な投稿']}" for r in sns))
    print(f"フォロワー：{sns[-1]['フォロワー（週末）']}人" if sns else "")
    ln = q.t("marketing/LINE.csv")[-4:]
    if ln:
        print("LINE 公式アカウント（直近4週）：" + "・".join(f"{r['週の初め（月曜）'][5:]} 友だち{r['友だちの数（週末）']}人・配信{r['配信の回数']}回・開封{r['開封率(%)']}%" for r in ln))


# ── 法務 ─────────────────────────────────────────────────
def q_houmu(q: Q):
    print(f"■ 法務（今日＝{jp(q.today)}・90日以内の期限）")
    items = []
    for c in q.t("legal/契約.csv"):
        for col in ("次の更新日", "条件を変えたいときの申し出期限"):
            v = c[col]
            if v[:4].isdigit():
                left = (d(v) - q.today).days
                if 0 <= left <= 90:
                    items.append((left, f"{c['相手']}（{c['契約の種類']}）の{col} {v}・あと{left}日・自動更新 {c['自動更新']}・状態 {c['状態']}"))
    for r in q.t("legal/許認可.csv"):
        v = r["期限"][:10]
        if v[:4].isdigit():
            left = (d(v) - q.today).days
            if 0 <= left <= 180:
                items.append((left, f"{r['名前']} の期限 {v}・あと{left}日（{r['管理する人']}）"))
    for _, line in sorted(items):
        print("- " + line)
    if not items:
        print("- なし")
    miss = [r for r in q.t("ec/商品ページ.csv") if r["「20歳未満の飲酒は法律で禁止」の表示"] != "○"]
    print("お酒のページの「20歳未満」の表示もれ：" + ("・".join(r["商品"] for r in miss) if miss else "なし"))
    over = [r for r in q.t("accounting/売掛金.csv") if r["期日から何日過ぎたか"]]
    for cid in sorted({r["取引先ID"] for r in over}):
        c = next((x for x in q.t("legal/契約.csv") if x["相手"] == CUST[cid][1]), None)
        print(f"支払いの遅れ：{CUST[cid][1]}（最大 {max(int(r['期日から何日過ぎたか']) for r in over if r['取引先ID'] == cid)}日）"
              + (f"。契約：{c['メモ']}" if c and c["メモ"] else ""))
    print("お知らせの言い方の点検：最近の題に「通常価格」「日本一」などの言い方は " +
          ("ある" if any(("通常価格" in n[1] or "日本一" in n[1]) for n in q.S["お知らせ"]) else "ない"))


# ── KPI ─────────────────────────────────────────────────
def q_kpi(q: Q):
    w = q.days(7)
    J = "accounting/日計表.csv"
    P = "store/POS_日別.csv"
    pos = [r for r in q.t(P) if r["日付"] in set(w) and not r["備考"]]
    sales = q.sumcol(J, "売上合計", w)
    gp = q.sumcol(J, "粗利", w)
    store = sum(float(r["合計"]) for r in pos)
    cust = sum(int(r["客数"]) for r in pos)
    lost = q.sumcol(J, "欠品で逃した売上", w)
    store_cost = q.sumcol(J, "原価_店舗", w)
    inv_val = sum(q.S["在庫"].get(i, 0) * ITEM[i][5] for i in q.S["在庫"] if i in ITEM)
    it = q.t("store/POS_商品別_直近14日.csv")
    cooked_cost = sum(float(r["売上"]) - float(r["粗利"]) for r in it if r["商品ID"] in ("F05", "F06", "F07") and r["日付"] in set(w))
    waste = q.sumcol(J, "廃棄（原価）", w)
    ec_o, ec_v = q.sumcol("ec/注文_日別.csv", "注文数", w), q.sumcol("ec/注文_日別.csv", "訪問数", w)
    ads = [r for r in q.t("marketing/広告.csv") if r["月"] == q.t("marketing/広告.csv")[-1]["月"]]
    ad_cost = sum(float(r["費用"] or 0) for r in ads if r["反応からの売上"])
    ad_rev = sum(float(r["反応からの売上"] or 0) for r in ads)
    recv = sum(float(r["請求額"]) for r in q.t("accounting/売掛金.csv") if not r["入金日"])
    b3 = sum(float(r["売上"]) for r in q.t("b2b/法人売上_月別.csv")[-18:]) / 92
    hours = sum(STAFF_HOURS[d(x).weekday()] for x in w if is_open(d(x)))
    pl = q.t("accounting/月次PL.csv")[-1]
    dl_last = sum(float(r["配達件数"]) for r in q.t("delivery/配達_日別.csv") if r["日付"].startswith(pl["月"]))
    rows = [
        ("売上（直近7日）", f"{fmt(sales)}円", "予算どおり", "AI経理"),
        ("粗利率", f"{gp / sales * 100:.1f}%" if sales else "―", f"{TARGET['粗利率']}%以上", "AI経理"),
        ("客数（1日）", f"{cust / max(1, len(pos)):.0f}人", f"{TARGET['客数']}人以上", "AI店長"),
        ("客単価", f"{fmt(store / max(1, cust))}円", f"{fmt(TARGET['客単価'])}円以上", "AI店長"),
        ("欠品率", f"{lost / (store + lost) * 100:.1f}%" if store else "―", f"{TARGET['欠品率']}%未満", "AI仕入れ"),
        ("在庫日数", f"{inv_val / (store_cost / max(1, len(pos))):.1f}日" if store_cost else "―", f"{TARGET['在庫日数']}日以下", "AI仕入れ"),
        ("廃棄率（店内調理）", f"{waste / cooked_cost * 100:.1f}%" if cooked_cost else "―", f"{TARGET['廃棄率']}%未満", "AI店長"),
        ("EC 購入率", f"{ec_o / ec_v * 100:.2f}%" if ec_v else "―", f"{TARGET['EC購入率']}%以上", "AI EC販売"),
        ("ROAS（広告1円あたりの売上・先月）", f"{ad_rev / ad_cost:.1f}" if ad_cost else "―", f"{TARGET['ROAS']}以上", "AI広告"),
        ("売掛金の回収日数", f"{recv / b3:.0f}日" if b3 else "―", f"{TARGET['回収日数']}日以下", "AI経理"),
        ("人時売上", f"{fmt(sales / hours)}円" if hours else "―", f"{fmt(TARGET['人時売上'])}円以上", "AI社長"),
        ("配達1件あたりの原価（先月）", f"{fmt((150000 + float(pl['車両費'])) / dl_last)}円" if dl_last else "―",
         f"{TARGET['配達1件の原価']}円以下", "AI物流"),
    ]
    print(f"■ KPI（直近7日 {w[0]}〜{w[-1]}。決め方は company/KPI.md）")
    print("| KPI | 今 | 目標 | 担当 |")
    print("|---|---|---|---|")
    for r in rows:
        print("| " + " | ".join(r) + " |")


# ── その他 ────────────────────────────────────────────────
def q_table(q: Q, rel, last, cols):
    rows = q.t(rel)
    if not rows:
        print(f"{rel} はありません（data/ からの道）")
        return
    keys = cols.split(",") if cols else list(rows[0].keys())
    print("| " + " | ".join(keys) + " |")
    print("|" + "---|" * len(keys))
    for r in rows[-last:]:
        print("| " + " | ".join(str(r.get(k, "")) for k in keys) + " |")


QUERIES = {
    "全体": (q_zentai, "全体の数字（昨日・直近7日・今月の予算比・先月・12か月）"),
    "店舗": (q_tenpo, "店の部門別・客数・落ちた商品・在庫0（AI店長）"),
    "仕入れ": (q_shiire, "在庫0・発注点割れ・入荷待ち・発注の抜け・行事の締め・手配の目安（AI仕入れ）"),
    "経理": (q_keiri, "先月の損益と予算比・事業別・今月・売掛金・資金繰り（AI経理）"),
    "期日超過": (q_kijitsu, "期日を過ぎた売掛金"),
    "EC": (q_ec, "ネットとギフト・流入・商品ページ・在庫のずれ（AI EC販売）"),
    "配達": (q_haitatsu, "配達の件数・地区・時間・便・ネットの未出荷（AI物流）"),
    "受付": (q_uketsuke, "電話の着信と取りこぼし・雨の日・天気予報（AI受付）"),
    "法人": (q_houjin, "取引先ごとの増減・1回あたり・契約の更新（AI営業）"),
    "広告": (q_koukoku, "媒体ごとの費用と効果・粗利で見た損得（AI広告）"),
    "口コミ": (q_kuchikomi, "口コミの数・星・未返信・不満の中身（AI接客）"),
    "広報": (q_kouhou, "行事の告知が出ているか・お知らせ・Instagram（AI広報）"),
    "法務": (q_houmu, "90日以内の期限・お酒の表示・支払いの遅れと契約（AI法務）"),
    "KPI": (q_kpi, "KPI と目標（company/KPI.md）"),
}
ALIAS = {"部門別売上": "店舗", "欠品": "仕入れ", "物流": "配達", "営業": "法人", "接客": "口コミ", "会計": "経理", "kpi": "KPI", "ec": "EC"}


def main(argv=None):
    ap = argparse.ArgumentParser(description="やまだ商店（架空）の数字を早く見る（読むだけ）")
    ap.add_argument("--root")
    ap.add_argument("name", help="一覧・全体・店舗・仕入れ・経理…／表")
    ap.add_argument("rest", nargs="*")
    ap.add_argument("--last", type=int, default=20)
    ap.add_argument("--cols")
    a = ap.parse_args(argv)
    paths = Paths(a.root)
    name = ALIAS.get(a.name, a.name)
    if name == "一覧":
        for k, (_, desc) in QUERIES.items():
            print(f"- {k}：{desc}")
        print("- 承認待ち：承認待ちの提案（期限が近い順）")
        print("- 表 <data/からの道>：CSV をそのまま表で（--last 行数・--cols 列,列）")
        return 0
    if name == "承認待ち":
        import approvals
        approvals.cmd_list(paths, None)
        return 0
    q = Q(paths)
    if name == "表":
        if not a.rest:
            print("使い方：python3 tools/q.py 表 store/POS_日別.csv --last 7")
            return 1
        q_table(q, a.rest[0], a.last, a.cols)
        return 0
    if name not in QUERIES:
        print(f"「{a.name}」はありません。python3 tools/q.py 一覧 で見てください。")
        return 1
    QUERIES[name][0](q)
    return 0


if __name__ == "__main__":
    sys.exit(main())
