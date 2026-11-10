#!/usr/bin/env python3
"""やまだ商店（架空）の経営シミュレーション。data/ を書くのはこの道具だけ。

    python3 tools/sim.py init [--date 2026-11-10]   はじめの状態に戻す（既定は 2026-11-10・火）
    python3 tools/sim.py advance [--days N]          会社を N 日進める（既定 1）
    python3 tools/sim.py apply <承認ID>               承認された提案の効果を会社に入れる
    python3 tools/sim.py status                      今の会社を10行で見る

書き終わると data/ と sim/state.json は「読むだけ」（書き込み不可）になる。決まりは sim/ルール.md。
どのコマンドも --root で別の場所のリポを扱える（テスト用）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (NOTE, WD, Paths, add_business_days, add_months, append_csv, check_proposal, d, find_proposal,  # noqa: E402
                    fmt, header_of, is_open, jp, load_state, lock, month_last, parse_proposal, read_csv,
                    save_state, unlock, weekday_back, write_csv, ym, yen)
from sim_model import (ALC, CHANNELS, COOKED, CUST, CUSTOMERS, DAILY_FRESH, DISTRICTS, EC_W, GIFT,  # noqa: E402
                       GIFT_BASE, GIFT_W, GIFTS, G02_START, GROWTH, ITEM, ITEMS, LOAN, MANUAL_SUPPLIERS,
                       OPEN_BALANCE, OTHER, OVERDUE, RAIN_P, SEASON, SEED, STAFF, STALL, SUPPLIERS, WDF, DEFAULT_START,
                       add_channel, is_manual, qty_s, reorder_point, unit,
                       b2b_daily, build_history, festival_name, gift_season, gift_shape, personnel, pick,
                       poisson, sround)

from sources import CH_SOURCE, EC_CHANNELS, GIFT_CHANNELS, sources_json  # noqa: E402

STOCKED = [it[0] for it in ITEMS if it[8] != "店内調理"]
UTIL = {1: 122, 2: 120, 3: 108, 4: 100, 5: 100, 6: 108, 7: 126, 8: 130, 9: 115, 10: 102, 11: 105, 12: 120}
BIZ = ["店舗", "配達", "EC", "ギフト", "法人"]
JOURNAL_H = ["日付", "曜日", "天気", "売上_店舗", "売上_配達", "売上_EC", "売上_ギフト", "売上_法人", "売上合計",
             "原価_店舗", "原価_配達", "原価_EC", "原価_ギフト", "原価_法人", "原価合計", "粗利",
             "欠品で逃した売上", "廃棄（原価）", "入金", "出金", "現金残高", "メモ"]
PL_COLS = ["月", "売上_店舗", "売上_配達", "売上_EC", "売上_法人", "売上_ギフト", "売上合計", "売上原価", "粗利", "粗利率(%)",
           "粗利_店舗", "粗利_配達", "粗利_EC", "粗利_法人", "粗利_ギフト", "人件費", "広告宣伝費", "地代家賃", "水道光熱費",
           "車両費", "支払手数料", "減価償却費", "その他経費", "販管費合計", "営業利益", "前年同月の売上合計"]
CASH_EXP = ["広告宣伝費", "地代家賃", "水道光熱費", "車両費", "支払手数料", "その他経費"]
BUDGET_G = {"店舗": 1.00, "配達": 1.05, "EC": 1.10, "法人": 1.00, "ギフト": 1.10}
DLV_SPLIT = (("△△食品卸（架空）", 0.5), ("△△酒販（架空）", 0.25), ("◯◯日用品卸（架空）", 0.25))
EC_SPLIT = (("□□酒造（架空）", 0.55), ("播磨麦酒（架空）", 0.30), ("◯◯包装（架空）", 0.15))
OTHER_SUP = {"S99": "△△酒販（架空）", "F99": "△△食品卸（架空）", "D99": "◯◯日用品卸（架空）"}


# ══ 共通の計算 ═════════════════════════════════════════════
def month_expenses(m: dt.date, store, ec_fee, dl_orders, ads_cost, extra=0):
    return {
        "人件費": personnel(m.month, extra),
        "広告宣伝費": ads_cost,
        "地代家賃": 30000,
        "水道光熱費": yen(UTIL[m.month] * 1000 * ((m.month * 7 % 5) / 100 + 0.98)),
        "車両費": 40000 + dl_orders * 10,
        "支払手数料": int(round(store * 0.006 + ec_fee, -2)),          # カードの手数料＋ネット3店の手数料
        "減価償却費": 30000,
        "その他経費": 72000 + (m.month * 1300) % 6000,
    }


def ad_rows(m: dt.date, ads: dict):
    """その月の広告：媒体, 回数, 費用, 配布/表示, 反応, 反応の中身, 反応からの売上（決まった式・sim/ルール.md）"""
    h = (m.year * 12 + m.month) * 7919
    n_flyer = ads["チラシの回数"] + (1 if (m.month == 12 and ads["チラシの回数"] > 0) else 0)
    coupons = 15 + h % 7
    rows = []
    if n_flyer:
        rows.append(["新聞折込チラシ", f"{n_flyer}回（各3,000部）", ads["チラシ1回の費用"] * n_flyer, 3000 * n_flyer,
                     coupons * n_flyer, "チラシのクーポン回収（枚）", coupons * n_flyer * (1750 + h % 300)])
    g = ads.get("Google広告", 0)
    if g:
        rows.append(["Google広告（検索）", "毎日（自動）", g, int(g * 2.5), int(g * (0.024 + (h % 5) / 1000)),
                     "サイトへのクリック（回）", int(8000 * (4.0 + (h % 7) / 10) * (g / 8000) ** 0.8)])
    cost = ads["Instagram広告"]
    if cost:
        roas = 5.6 + (h % 11) / 10
        rev = int(12000 * roas * (cost / 12000) ** 0.8)            # 増やすほど1円あたりは少し下がる
        rows.append(["Instagram広告", "毎日（自動）", cost, int(cost * 1.5), int(cost * (0.033 + (h % 9) / 1000)),
                     "サイトへのクリック（回）", rev])
    if ads.get("回覧板・店頭ポスター", 0):
        rows.append(["回覧板の広告枠・店頭ポスター", "月1回", ads["回覧板・店頭ポスター"], 1200, "", "測れていない", ""])
    rows.append(["Google ビジネスプロフィール（無料）", "常時", 0, 2600 + h % 400, 140 + h % 40, "電話・道順のタップ（回）", ""])
    return rows


def ads_cost(m, ads):
    return sum(r[2] for r in ad_rows(m, ads))


def history_ads(m: dt.date, insta_start: dt.date):
    ig = 0 if m < insta_start else (8000 if m == insta_start else 12000)
    return {"チラシの回数": 2, "チラシ1回の費用": 19000, "Google広告": 0 if m < insta_start else 8000, "Instagram広告": ig,
            "回覧板・店頭ポスター": 5000}


def store_ad_factor(ads):
    return 1 + 0.006 * (ads["チラシの回数"] - 2) + 0.002 * (ads["Instagram広告"] - 12000) / 10000


def ec_ad_factor(ads):
    return 1 + 0.05 * (ads["Instagram広告"] - 12000) / 10000 + 0.03 * (ads.get("Google広告", 8000) - 8000) / 10000


def pl_row(m, sums, exp, prev_total):
    sales = sum(sums["売上_" + b] for b in BIZ)
    cogs = sum(sums["原価_" + b] for b in BIZ)
    gp = sales - cogs
    sga = sum(exp.values())
    row = {"月": ym(m), "売上_店舗": sums["売上_店舗"], "売上_配達": sums["売上_配達"], "売上_EC": sums["売上_EC"],
           "売上_法人": sums["売上_法人"], "売上_ギフト": sums["売上_ギフト"], "売上合計": sales, "売上原価": cogs, "粗利": gp,
           "粗利率(%)": round(gp / sales * 100, 1) if sales else 0}
    for b in ("店舗", "配達", "EC", "法人", "ギフト"):
        row["粗利_" + b] = sums["売上_" + b] - sums["原価_" + b]
    row.update(exp)
    row["販管費合計"] = sga
    row["営業利益"] = gp - sga
    row["前年同月の売上合計"] = prev_total
    return row


def supplier_alloc(costs_by_item: dict, dlv_b2b_cost: float, ec_gift_cost: float) -> dict:
    by = {}
    for iid, c in costs_by_item.items():
        s = OTHER_SUP.get(iid) or ITEM[iid][8]
        if s == "店内調理":
            s = "△△食品卸（架空）"
        by[s] = by.get(s, 0) + c
    for s, share in DLV_SPLIT:
        by[s] = by.get(s, 0) + dlv_b2b_cost * share
    for s, share in EC_SPLIT:
        by[s] = by.get(s, 0) + ec_gift_cost * share
    return by


# ══ init ═══════════════════════════════════════════════════
def clean_approvals(paths: Paths):
    """承認の箱と意思決定ログを空にする（撮り直し用。人が init --clean で動かす）。"""
    n = 0
    for folder in (paths.pending, paths.approved, paths.rejected):
        folder.mkdir(parents=True, exist_ok=True)
        for f in folder.glob("*.md"):
            f.unlink()
            n += 1
        (folder / ".gitkeep").touch()
    paths.logs.mkdir(parents=True, exist_ok=True)
    import approvals
    (paths.logs / "意思決定ログ.md").write_text(approvals.LOG_HEAD, encoding="utf-8")
    return n


def cmd_init(paths: Paths, today: dt.date, quiet=False):
    t0 = time.time()
    W = build_history(today)
    L, m0 = W["L"], W["m0"]
    win_start = min(today - dt.timedelta(days=56), add_months(m0, -1))
    window = [x for x in W["days"] if x >= win_start]
    bd = b2b_daily(W, W["days"])

    # 日ごとの帳簿（全期間）
    books = {}
    for x in W["days"]:
        r = L[x]
        b2b_s = sum(bd[x].values())
        b2b_c = sum(yen(v * 0.82) for v in bd[x].values())
        books[x] = {"売上_店舗": r["store"], "売上_配達": r["dl"]["sales"], "売上_EC": r["ec"]["sales"],
                    "売上_ギフト": r["gift_sales"], "売上_法人": b2b_s,
                    "原価_店舗": yen(r["store_cost"]), "原価_配達": yen(r["dl"]["cost"]), "原価_EC": r["ec"]["cost"],
                    "原価_ギフト": r["gift_cost"], "原価_法人": b2b_c, "lost": r["lost"], "waste": r["waste"],
                    "dl_orders": r["dl"]["orders"], "net_gift": r["gift"]["ネット"]["sales"],
                    "ec_fee": sum(v["fee"] for v in r["ec"]["ch"].values()) + sum(v["fee"] for v in r["gift"]["ネット"]["ch"].values())}

    def month_sums(m):
        rows = [b for x, b in books.items() if x.year == m.year and x.month == m.month]
        keys = [f"{a}_{b}" for a in ("売上", "原価") for b in BIZ] + ["dl_orders", "net_gift", "ec_fee"]
        return {k: sum(r[k] for r in rows) for k in keys}

    pls = {}
    for m in W["months"]:
        s = month_sums(m)
        exp = month_expenses(m, s["売上_店舗"], s["ec_fee"], s["dl_orders"],
                             ads_cost(m, history_ads(m, W["insta_start"])))
        prev = pls.get(add_months(m, -12))
        pls[m] = pl_row(m, s, exp, prev["売上合計"] if prev else "")

    unlock(paths)
    D = paths.data
    for p in sorted(D.rglob("*"), reverse=True) if D.exists() else []:
        if p.is_file():
            p.unlink()
    D.mkdir(parents=True, exist_ok=True)

    S = initial_state(W, today, pls, books, window, bd)

    # master
    write_csv(D / "master/商品.csv",
              ["商品ID", "商品", "単位", "部門", "分類", "単価", "原価", "粗利率(%)", "仕入先", "納期（日）", "発注点", "発注の決め方", "ネットショップに出しているか"],
              [[i, n, unit(i), dp, c, p, cst, round((p - cst) / p * 100, 1), s, lead, reorder_point(i) if s != "店内調理" else "",
                "店内で作る" if s == "店内調理" else ("毎日の定期" if i in DAILY_FRESH else ("承認がいる" if is_manual(i) else "定期（自動）")),
                "○" if ec else ""]
               for i, n, dp, c, p, cst, avg, rop, s, lead, ec in ITEMS]
              + [[oid, on, "", dp, "その他（まとめ）", "", "", round((1 - rate) * 100, 1), "いろいろ", "", "", "", ""]
                 for dp, (oid, on, base, rate) in OTHER.items()]
              + [[g, n, unit(g), "ギフト", "のし付き・全国発送", p, c, round((p - c) / p * 100, 1), "□□酒造・播磨麦酒（架空）ほか", 4, "", "注文ごと", "○"]
                 for g, n, p, c in GIFTS],
              "単価・原価は「単位」1つあたり（例：播磨ゴールドは6缶入りのパック1つ）。発注点と数量もこの単位で数える")
    write_csv(D / "master/仕入先.csv", ["仕入先", "主な商品", "納期", "発注の締め", "発注のしかた", "最低の発注", "支払条件", "発注の決め方"],
              [list(s) for s in SUPPLIERS], "「承認がいる」仕入先は、AI仕入れが提案して山田社長が承認したときだけ発注される")
    write_csv(D / "master/法人顧客.csv",
              ["取引先ID", "取引先", "業種", "主な商品", "定期配達の曜日", "1か月の売上の目安", "支払条件", "取引開始"],
              [[c, n, k, g, "・".join(WD[x] for x in dows), base, "月末締め翌月末払い", since]
               for c, n, k, g, dows, base, since in CUSTOMERS])
    write_csv(D / "master/従業員.csv", ["名前（架空）", "役職", "雇用", "主な仕事", "勤務", "一緒に動くAI"], [list(s) for s in STAFF],
              "人は8人。お金が動くことと約束ごとは代表の山田太郎が決める")

    # store
    rows = []
    for x in window:
        r = L[x]
        py = L.get(x - dt.timedelta(days=364))
        rows.append(pos_row(x, r["weather"], r["dept"], r["cust"], py["store"] if py else ""))
    write_csv(D / "store/POS_日別.csv", POS_H, rows, "前年同曜日＝364日前（同じ曜日）")
    rows = []
    for x in [y for y in W["days"][-14:] if is_open(y)]:
        r = L[x]
        rows += item_rows(x, r["qty"], r["sales"], r["cost"])
    write_csv(D / "store/POS_商品別_直近14日.csv", ITEM_H, rows, "営業日だけ。部門ごとの合計は POS_日別 と同じ")

    # delivery
    rows = []
    for x in window:
        py = L.get(x - dt.timedelta(days=364))
        rows.append(dl_row(x, L[x]["weather"], L[x]["dl"], py["dl"]["sales"] if py else ""))
    write_csv(D / "delivery/配達_日別.csv", DL_H, rows,
              "ご近所への電話注文の配達だけ（法人の定期配達は b2b）。配達料200円（3,000円以上は無料）を含む")

    # ec
    rows = []
    for x in window:
        e = L[x]["ec"]
        py = L.get(x - dt.timedelta(days=364))
        rows.append(ec_row(x, e, py["ec"]["sales"] if py else ""))
    write_csv(D / "ec/注文_日別.csv", EC_H, rows,
              "ネットショップの通常の注文（自家用の地酒・地ビールなど）。のし付きギフトは gift/。日曜も注文は入る")
    rows = []
    for x in W["days"][-28:]:
        e = L[x]["ec"]
        for iid in sorted(e["byo"]):
            rows.append([x.isoformat(), iid, ITEM[iid][1], e["byo"][iid], e["by"][iid], unit(iid)])
    write_csv(D / "ec/注文_商品別_直近28日.csv", EC_ITEM_H, rows, "ネットの通常の注文を商品ごとに")
    rows = []
    for x in window:
        rows += ch_rows(x, L[x]["ec"]["ch"], L[x]["gift"]["ネット"]["ch"])
    write_csv(D / "ec/チャネル別_日別.csv", CH_H, rows,
              "ネット3店（自社サイト＝Shopify・楽天市場・Amazon）の注文。通常＋ギフトのネット分。手数料は各店の料率の目安（架空の連携）")

    # gift
    rows = []
    for x in window:
        for ch in CHANNELS:
            g = L[x]["gift"][ch]
            if g["n"]:
                rows.append(gift_row(x, ch, g))
    write_csv(D / "gift/ギフト受注_日別.csv", GIFT_H, rows, "のし付きギフトの承り（受けた日に売上）。件数＝送り先の数")

    # b2b
    rows = []
    for x in window:
        for cid, amt in sorted(bd[x].items()):
            rows.append([x.isoformat(), cid, CUST[cid][1], amt, amt - yen(amt * 0.82)])
    write_csv(D / "b2b/納品_日別.csv", B2B_DAY_H, rows, "法人への納品（定期配達の日）")
    rows = []
    for m in W["months"][-12:]:
        for c in CUSTOMERS:
            rows.append(b2b_month_row(m, c[0], [(x, v[c[0]]) for x, v in bd.items()
                                                 if x.year == m.year and x.month == m.month and c[0] in v]))
    write_csv(D / "b2b/法人売上_月別.csv", B2B_MON_H, rows, "近所の飲食店・介護施設への卸と定期配達")

    # accounting
    write_csv(D / "accounting/月次PL.csv", PL_COLS, [[pls[m][c] for c in PL_COLS] for m in W["months"][-12:]],
              "締まった月だけ。店舗の売上＝POS の合計。法人＝b2b/納品_日別 の合計")
    write_budget(D, today, pls)
    write_csv(D / "accounting/日計表.csv", JOURNAL_H, S.pop("_journal"),
              "毎日の帳簿。入金＝その日に入ったお金（店・配達・ネット・ギフトはその日・法人は入金の日）。出金＝25日の給料と月末の支払い")

    # marketing・pr・legal
    rows = []
    for m in W["months"][-3:]:
        rows += [[ym(m)] + r + [round(r[6] / r[2], 1) if (r[2] and r[6] != "") else ""]
                 for r in ad_rows(m, history_ads(m, W["insta_start"]))]
    write_csv(D / "marketing/広告.csv", AD_H, rows, "月ごと。月次PL の広告宣伝費＝この費用の合計")
    write_csv(D / "marketing/口コミ.csv", ["日付", "どこの口コミ", "星", "本文", "返信"], reviews(today))
    write_csv(D / "marketing/SNS.csv", SNS_H, sns_history(W, S), "お店の Instagram（週ごと）")
    write_csv(D / "marketing/LINE.csv", LINE_H, line_history(today), "LINE 公式アカウント（週ごと・架空の連携）")
    write_csv(D / "legal/許認可.csv", ["名前", "番号", "取った日", "期限", "管理する人", "メモ"], licenses())

    # 前年の参照（sim/）
    paths.sim.mkdir(parents=True, exist_ok=True)
    rows = []
    x = win_start.replace(day=1)                                  # 月の初めから（予算を月の全部の日に割り振るため）
    while x <= month_last(today + dt.timedelta(days=365)):
        r = L.get(x - dt.timedelta(days=364))
        if r:
            g = r["gift"]
            rows.append([x.isoformat(), r["store"], r["dept"]["酒類"], r["dl"]["sales"], r["ec"]["sales"]]
                        + [g[ch]["n"] for ch in CHANNELS] + [g[ch]["sales"] for ch in CHANNELS]
                        + [r["ec"]["byo"].get(i, 0) for i, _ in EC_W] + [g["ネット"]["by"].get(k, 0) for k in GIFT])
        x += dt.timedelta(days=1)
    write_csv(paths.prior, PRIOR_H, rows, "シミュレーションの参照用：その日の364日前（去年の同じ曜日）の数字")

    morning(S, today)
    refresh_derived(paths, S)
    save_state(paths, S)
    lock(paths)
    if not quiet:
        print(f"はじめの状態を作りました：今日＝{today}（{WD[today.weekday()]}）・データは昨日まで（{time.time() - t0:.1f}秒）")
        print(status_text(paths, S))
    return S


POS_H = ["日付", "曜日", "天気", "食料品", "日用品", "酒類", "合計", "客数", "客単価", "前年同曜日の合計", "備考"]
ITEM_H = ["日付", "曜日", "商品ID", "商品", "部門", "数量", "単位", "売上", "粗利"]
DL_H = ["日付", "曜日", "天気", "電話の着信", "着信_午前", "着信_午後", "取れなかった電話", "配達件数", "配達の売上",
        *[k for k, *_ in DISTRICTS], "午前便", "午後便", "配達にかかった時間（分）", "うち北地区（分）", "前年同曜日の配達の売上", "備考"]
EC_H = ["日付", "曜日", "訪問数", "注文数", "売上", "購入率(%)", "流入_検索", "流入_Instagram", "流入_直接", "流入_その他", "前年同曜日の売上"]
EC_ITEM_H = ["日付", "商品ID", "商品", "注文数", "数量", "単位"]
GIFT_H = ["日付", "受付", "件数", "売上", "G01", "G02", "G03"]
B2B_DAY_H = ["日付", "取引先ID", "取引先", "金額", "粗利"]
B2B_MON_H = ["月", "取引先ID", "取引先", "業種", "売上", "粗利", "納品回数", "1回あたりの売上"]
AD_H = ["月", "媒体", "回数", "費用", "配った数・表示回数", "反応", "反応の中身", "反応からの売上", "売上÷費用"]
CH_H = ["日付", "チャネル", "種類", "注文数", "売上", "手数料", "出どころ"]
LINE_H = ["週の初め（月曜）", "友だちの数（週末）", "配信の回数", "開封率(%)", "クーポンの利用（枚）"]
SNS_H = ["週の初め（月曜）", "投稿数", "フォロワー（週末）", "リーチ", "いいね", "保存", "プロフィールへのアクセス", "サイトへのクリック", "主な投稿"]
PRIOR_H = (["日付", "店の合計", "酒類", "配達の売上", "ECの売上"] + [f"ギフト_{c}_件数" for c in CHANNELS]
           + [f"ギフト_{c}_売上" for c in CHANNELS] + [f"EC_{i}" for i, _ in EC_W] + [f"ネット_{g}" for g in GIFT])


def ch_rows(x, ec_ch, gift_ch):
    rows = []
    for kind, acc in (("通常", ec_ch), ("ギフト", gift_ch)):
        for name, _, _, _ in EC_CHANNELS:
            a = acc.get(name)
            if a and a["orders"]:
                rows.append([x.isoformat(), name, kind, a["orders"], a["sales"], a["fee"], CH_SOURCE[name]])
    return rows


def line_history(today):
    rnd = random.Random(SEED + 3)
    mon = today - dt.timedelta(days=today.weekday())
    rows, fr = [], 402
    for i in range(8, 0, -1):
        fr += rnd.randint(2, 6)
        rows.append([(mon - dt.timedelta(days=7 * i)).isoformat(), fr, rnd.choice([1, 1, 2]), round(rnd.uniform(52, 64), 1), rnd.randint(6, 15)])
    return rows


def closed_note(x):
    return "年始休み" if (x.month == 1 and x.day <= 3) else ("定休日" if x.weekday() == 6 else "")


def pos_row(x, weather, dept, cust, prior):
    tot = sum(dept.values())
    return [x.isoformat(), WD[x.weekday()], weather, dept["食料品"], dept["日用品"], dept["酒類"], tot, cust,
            round(tot / cust) if cust else 0, prior, closed_note(x)]


def item_rows(x, qty, sales, cost):
    rows = []
    for iid, name, dp, *_ in ITEMS:
        rows.append([x.isoformat(), WD[x.weekday()], iid, name, dp, qty.get(iid, 0), unit(iid), sales.get(iid, 0),
                     yen(sales.get(iid, 0) - cost.get(iid, 0))])
    for dp, (oid, on, base, rate) in OTHER.items():
        rows.append([x.isoformat(), WD[x.weekday()], oid, on, dp, "", "", sales.get(oid, 0), yen(sales.get(oid, 0) - cost.get(oid, 0))])
    return rows


def dl_row(x, weather, dl, prior):
    return [x.isoformat(), WD[x.weekday()], weather, dl["calls"], dl["am_calls"], dl["calls"] - dl["am_calls"], dl["missed"],
            dl["orders"], dl["sales"], *[dl["dist"][k] for k, *_ in DISTRICTS], dl["am"], dl["pm"], dl["minutes"], dl["north_min"], prior,
            closed_note(x)]


def ec_row(x, e, prior):
    return [x.isoformat(), WD[x.weekday()], e["visits"], e["orders"], e["sales"],
            round(e["orders"] / e["visits"] * 100, 2) if e["visits"] else 0, *e["flow"], prior]


def gift_row(x, ch, g):
    return [x.isoformat(), ch, g["n"], g["sales"], g["by"].get("G01", 0), g["by"].get("G02", 0), g["by"].get("G03", 0)]


def b2b_month_row(m, cid, day_amts):
    s = sum(a for _, a in day_amts)
    gp = sum(a - yen(a * 0.82) for _, a in day_amts)
    n = len(day_amts)
    return [ym(m), cid, CUST[cid][1], CUST[cid][2], s, gp, n, round(s / n) if n else 0]


def write_budget(D, today, pls):
    fy = today.year if today.month >= 4 else today.year - 1
    rows = []
    for i in range(12):
        m = dt.date(fy, 4, 1)
        m = add_months(m, i)
        p = pls.get(add_months(m, -12))
        if not p:
            continue
        b = {k: int(round(p["売上_" + k] * g, -3)) for k, g in BUDGET_G.items()}
        tot = sum(b.values())
        gp = sum(int(round(b[k] * (p["粗利_" + k] / p["売上_" + k] if p["売上_" + k] else 0), -3)) for k in b)
        op = gp - int(round(p["販管費合計"], -3))
        rows.append([ym(m), b["店舗"], b["配達"], b["EC"], b["法人"], b["ギフト"], tot, gp, op])
    write_csv(D / "accounting/予算.csv", ["月", "売上_店舗", "売上_配達", "売上_EC", "売上_法人", "売上_ギフト", "売上合計", "粗利", "営業利益"],
              rows, f"{fy}年度（{fy}年4月〜{fy + 1}年3月）の予算。前年の実績×伸び（店舗±0%・配達+5%・EC+10%・法人±0%・ギフト+10%）")


def initial_state(W, today, pls, books, window, bd):
    L, m0 = W["L"], W["m0"]
    last28 = [x for x in W["days"] if x >= today - dt.timedelta(days=28)]
    nopen = sum(1 for x in last28 if is_open(x)) or 1
    rnd = random.Random(SEED + 1)
    stock, avg = {}, {}
    for iid in STOCKED:
        it = ITEM[iid]
        per = (sum(L[x]["qty"].get(iid, 0) for x in last28) + sum(L[x]["ec"]["by"].get(iid, 0) for x in last28)) / nopen
        avg[iid] = round(per, 2)
        if iid in DAILY_FRESH:
            q = max(int(per * rnd.uniform(0.8, 1.4)) + 2, it[7] + rnd.randint(2, 6))
        elif is_manual(iid):
            q = int(it[7] + per * rnd.uniform(8, 12)) + 2          # 手配の品は、先週の手配が抜けても1週間は持つ
        else:
            q = int(reorder_point(iid) + per * rnd.uniform(4, 8)) + 2   # 定期（自動）の品は余裕をもって
        stock[iid] = q
    stock["S01"], stock["D01"], stock["S07"] = 0, 9, 3
    site = {iid: stock[iid] for iid, _ in EC_W}
    site["S01"], site["S07"] = 12, stock["S07"] + 2
    unshipped = [{"注文日": x.isoformat(), "商品ID": iid, "数量": q} for x in W["days"] if x >= W["stockout"]
                 for iid, q in L[x]["ec"]["unshipped"]]

    orders = history_orders(W, rnd)
    # 売掛金（直近4か月の請求）
    recv = []
    for back in (4, 3, 2, 1):
        m = add_months(m0, -back)
        due = month_last(add_months(m, 1))
        for c in CUSTOMERS:
            amt = sum(v for x, dd in bd.items() if x.year == m.year and x.month == m.month for k, v in dd.items() if k == c[0])
            paid = None
            if due < today:
                if c[0] == OVERDUE and back == 4 and (today - month_last(add_months(m0, -2))).days > 30:
                    paid = (due + dt.timedelta(days=19)).isoformat()
                elif c[0] != OVERDUE:
                    paid = weekday_back(due - dt.timedelta(days=(int(c[0][1:]) * 3) % 6)).isoformat()
            recv.append({"取引先ID": c[0], "取引先": c[1], "請求の月": ym(m), "請求額": amt, "請求日": month_last(m).isoformat(),
                         "支払期日": due.isoformat(), "入金日": paid})
    # 買掛金（先月分＝今月末に払う・今月分＝来月末に払う）
    pay = {}
    for m in (add_months(m0, -1), m0):
        by = {}
        for x in W["days"]:
            if x.year == m.year and x.month == m.month:
                r = L[x]
                al = supplier_alloc(r["cost"], r["dl"]["cost"] + books[x]["原価_法人"], r["ec"]["cost"] + r["gift_cost"])
                for s, v in al.items():
                    by[s] = by.get(s, 0) + v
        pay[ym(m)] = {s: yen(v) for s, v in by.items()}
    # 現金（窓の最初から、入金と出金の決まりで積み上げる）
    journal, cash = [], OPEN_BALANCE
    paid_on = {}
    for inv in recv:
        if inv["入金日"]:
            paid_on.setdefault(inv["入金日"], []).append(inv)
    # 窓より前の請求（窓の中で入金されるもの）
    first_m = window[0].replace(day=1)
    for back in range(1, 4):
        m = add_months(first_m, -back)
        due = month_last(add_months(m, 1))
        for c in CUSTOMERS:
            if c[0] == OVERDUE or due < window[0]:
                continue
            key = weekday_back(due - dt.timedelta(days=(int(c[0][1:]) * 3) % 6)).isoformat()
            if any(r["請求の月"] == ym(m) and r["取引先ID"] == c[0] for r in recv):
                continue
            amt = W["b2b"].get((m, c[0]), {}).get("sales", 0)
            paid_on.setdefault(key, []).append({"請求額": amt})
    for x in window:
        b = books[x]
        sales_in = b["売上_店舗"] + b["売上_配達"] + b["売上_EC"] + b["売上_ギフト"]
        coll = sum(int(i["請求額"]) for i in paid_on.get(x.isoformat(), []))
        out, memo = 0, []
        if x.day == 25:
            out += pls[x.replace(day=1)]["人件費"] if x.replace(day=1) in pls else personnel(x.month)
            memo.append("給料")
        if x == month_last(x) and x.replace(day=1) in pls:
            p = pls[x.replace(day=1)]
            prev = pls.get(add_months(x.replace(day=1), -1))
            out += (prev["売上原価"] if prev else 0) + sum(p[k] for k in CASH_EXP) + LOAN
            memo.append("月末の支払い（仕入れ・経費・借入金）")
        if coll:
            memo.append("法人の入金")
        cash += sales_in + coll - out
        s_tot = sum(b["売上_" + k] for k in BIZ)
        c_tot = sum(b["原価_" + k] for k in BIZ)
        journal.append([x.isoformat(), WD[x.weekday()], L[x]["weather"], b["売上_店舗"], b["売上_配達"], b["売上_EC"],
                        b["売上_ギフト"], b["売上_法人"], s_tot, b["原価_店舗"], b["原価_配達"], b["原価_EC"], b["原価_ギフト"],
                        b["原価_法人"], c_tot, s_tot - c_tot, b["lost"], b["waste"], sales_in + coll, out, cash, "・".join(memo)])
    cur = W["b2b_cur"]
    fest = W["fest"]
    nxt = today + dt.timedelta(days=1)
    if nxt.weekday() == 6:
        nxt += dt.timedelta(days=1)
    S = {
        "版": 2, "基準日": today.isoformat(), "今日": today.isoformat(), "現金": cash,
        "在庫": stock, "平均販売": avg, "サイト在庫": site, "在庫連動": False, "未出荷": unshipped,
        "発注": orders, "売掛金": recv, "買掛金": pay,
        "値下げ": [], "広告": {"チラシの回数": 2, "チラシ1回の費用": 19000, "Google広告": 8000, "Instagram広告": 12000, "回覧板・店頭ポスター": 5000},
        "契約": contracts(today), "シフト": {"雨の日の午前の電話番": False, "夕方のレジを2人に": False},
        "配達": {"北地区を午後便にまとめる": False},
        "法人": {c[0]: {"曜日": list(c[4]), "1回の目安": round(cur[c[0]]["per_visit"]), "出荷": True} for c in CUSTOMERS},
        "督促": {}, "表示": {"G02": "×"}, "お知らせ": [list(n) for n in notice_items(today)],
        "行事": [{"日付": fest.isoformat(), "名前": f"△△町 {festival_name(fest)}", "倍率": 1.9, "屋台": True, "告知": False},
                 {"日付": (fest + dt.timedelta(days=8)).isoformat(), "名前": "小学校の運動会", "倍率": 1.0, "屋台": False, "告知": False}],
        "天気の上書き": {nxt.isoformat(): "雨", fest.isoformat(): "晴れ"},
        "人件費の上乗せ": {}, "ページ改善": False, "フォロワー": 0,
        "欠品記録": {"S01": {"since": W["stockout"].isoformat(), "lost": sum(L[x]["lost"] for x in W["days"] if x >= W["stockout"])}},
        "施策": [], "適用済み": [], "月の締め": ym(add_months(m0, -1)),
        "_journal": journal,
    }
    auto_reorder(S, today - dt.timedelta(days=1))           # 前の晩の定期発注（行事の先読みも）
    return S


def history_orders(W, rnd):
    today = W["today"]
    plan = {
        "△△酒販（架空）": ([27, 24, 20, 17, 13, 10, 6, 3], ["S02", "S03", "S04", "S05", "S08", "S09", "S13"], 3.5),
        "□□酒造（架空）": ([26, 12], ["S06", "S07", "S10", "S11"], 14),
        "◯◯米穀（架空）": ([28, 21, 14, 7], ["F01"], 7),
        "△△食品卸（架空）": ([25, 18, 11, 4], ["F15", "F16", "F17", "F18", "F22", "F23", "F24", "F25"], 7),
        "△△飲料（架空）": ([26, 19, 12, 5], ["F19", "F20", "F21"], 7),
        "◯◯日用品卸（架空）": ([24, 17, 10, 3], ["D02", "D03", "D04", "D05", "D06", "D07", "D08", "D09", "D10", "D11", "D12"], 7),
    }
    rows = []
    for sup, (offs, ids, interval) in plan.items():
        for off in offs:
            od = weekday_back(today - dt.timedelta(days=off))
            if sup == "◯◯日用品卸（架空）" and off == 3:
                continue                                   # 先週の日用品の手配が抜けている
            for iid in ids:
                if len(ids) > 2 and rnd.random() > 0.6:
                    continue
                q = max(2, int(round(ITEM[iid][6] * 6.2 * interval / 6 * rnd.uniform(0.9, 1.2))))
                rows.append((od, sup, iid, q, "定期（自動）" if sup not in MANUAL_SUPPLIERS else "手配（配達・仕入れの担当）"))
    s01 = weekday_back(today - dt.timedelta(days=15))
    for k in (14, 7, 0):
        rows.append((s01 - dt.timedelta(days=k), "播磨麦酒（架空）", "S01", 48, "手配（配達・仕入れの担当）"))
    rows.append((s01 - dt.timedelta(days=7), "播磨麦酒（架空）", "S12", 6, "手配（配達・仕入れの担当）"))
    for off in (24, 17, 10):
        rows.append((weekday_back(today - dt.timedelta(days=off)), "◯◯日用品卸（架空）", "D01", 35, "手配（配達・仕入れの担当）"))
    out = []
    for i, (od, sup, iid, q, who) in enumerate(sorted(rows, key=lambda x: (x[0], x[1], x[2]))):
        arr = arrival_date(od, iid)
        out.append({"番号": f"H{i + 1:03d}", "発注日": od.isoformat(), "仕入先": sup, "商品ID": iid, "商品": ITEM[iid][1],
                    "数量": q, "金額": ITEM[iid][5] * q, "入荷予定日": arr.isoformat(),
                    "状態": "入荷済み" if arr < today else "未入荷", "発注者": who})
    return out


def arrival_date(od: dt.date, iid: str) -> dt.date:
    it = ITEM[iid]
    if it[8] == "播磨麦酒（架空）":
        return add_business_days(od, it[9])
    arr = od + dt.timedelta(days=it[9])
    return arr + dt.timedelta(days=1) if arr.weekday() == 6 else arr


# ══ 一日進める ═══════════════════════════════════════════════
def weather(S, day: dt.date) -> str:
    o = S["天気の上書き"].get(day.isoformat())
    if o:
        return o
    r = random.Random(f"{SEED}-天気-{day.isoformat()}")
    rain = r.random() < RAIN_P.get(day.month, 0.25)
    return "雨" if rain else ("晴れ" if r.random() < 0.6 else "くもり")


def price_of(S, iid, day: dt.date) -> int:
    base = (ITEM.get(iid) or GIFT.get(iid))[4 if iid in ITEM else 2]
    for v in S["値下げ"]:
        if v["商品ID"] == iid and d(v["から"]) <= day <= d(v["まで"]):
            return int(round(base * (1 - v["率"]), -1))
    return base


def prior(paths: Paths, cache: dict, day: dt.date):
    if "rows" not in cache:
        cache["rows"] = {r["日付"]: r for r in read_csv(paths.prior)}
    return cache["rows"].get(day.isoformat())


def simulate_day(paths: Paths, S: dict, day: dt.date, cache: dict) -> dict:
    rnd = random.Random(f"{SEED}-{day.isoformat()}")
    D = paths.data
    base_day = d(S["基準日"])
    notes = []

    def tr(key):
        return (1 + GROWTH[key]) ** ((day - base_day).days / 365)

    if S.get("朝の処理済み") != day.isoformat():
        notes += morning(S, day)

    w = weather(S, day)
    rain = w == "雨"
    ev = next((e for e in S["行事"] if e["日付"] == day.isoformat()), None)
    fest = ev if (ev and ev["倍率"] > 1) else None
    ads = S["広告"]

    # 店
    qty, sales, cost = {}, {}, {}
    dept = {"食料品": 0, "日用品": 0, "酒類": 0}
    lost = waste = cust = 0
    if is_open(day):
        base = WDF[day.weekday()] * SEASON[day.month] * tr("店舗") * (0.88 if rain else 1.0) * store_ad_factor(ads)
        if day.month == 12 and day.day >= 28:
            base *= 1.35
        out1 = S["在庫"].get("S01", 0) == 0
        fmult = (fest["倍率"] + (0.2 if fest["告知"] else 0)) if fest else 1.0
        for iid, name, dp, cat, p0, c, avg, rop, sup, lead, ec in ITEMS:
            price = price_of(S, iid, day)
            lam = avg * base * (1 + 1.5 * (p0 - price) / p0)
            if dp == "酒類":
                lam *= ALC.get(day.month, 1.0)
            if fest and (dp == "酒類" or cat == "飲料"):
                lam *= fmult
            if out1:
                lam *= {"S02": 1.08, "S05": 1.05}.get(iid, 0.93 if dp == "酒類" else 1.0)
            expect = lam
            want = sround(rnd, lam * rnd.uniform(0.85, 1.15))
            extra = (STALL.get(iid, 0) + (5 if (iid == "S01" and fest["告知"]) else 0)) if (fest and fest["屋台"]) else 0
            want += extra
            if iid == "S01" and out1:
                want = sround(rnd, avg * base * ALC.get(day.month, 1.0) * (fmult if fest else 1.0)) + extra
            if iid in COOKED:
                q = want
                waste += max(0, math.ceil(expect * 1.03) - q) * c
            else:
                q = min(want, S["在庫"].get(iid, 0))
                lost += (want - q) * price
                S["在庫"][iid] = S["在庫"].get(iid, 0) - q
                if S["在庫"][iid] <= 0:
                    rec = S["欠品記録"].setdefault(iid, {"since": day.isoformat(), "lost": 0})
                    rec["lost"] += (want - q) * price
            qty[iid], sales[iid], cost[iid] = q, q * price, q * c
            dept[dp] += q * price
        for dp, (oid, oname, obase, orate) in OTHER.items():
            amt = obase * base * rnd.uniform(0.92, 1.08) * (ALC.get(day.month, 1.0) if dp == "酒類" else 1.0)
            if fest and dp == "酒類":
                amt *= fmult
            amt = yen(amt)
            sales[oid], cost[oid] = amt, amt * orate
            dept[dp] += amt
        cust = 108 * WDF[day.weekday()] * math.sqrt(SEASON[day.month]) * tr("店舗") * (0.9 if rain else 1.0) * store_ad_factor(ads)
        cust = int(round(cust * rnd.uniform(0.93, 1.07) * (0.96 if out1 else 1.0) * (1.3 if fest else 1.0)))
        if fest and not out1:
            notes.append(f"［行事］{fest['名前']}：酒類と飲料がよく出た")
        elif fest:
            notes.append(f"［行事］{fest['名前']}：播磨ゴールドが無く、屋台で取り逃がし")
    store_total = sum(dept.values())
    store_cost = sum(cost.values())

    # 配達
    dl = {"orders": 0, "sales": 0, "cost": 0, "calls": 0, "am_calls": 0, "missed": 0,
          "dist": {k: 0 for k, *_ in DISTRICTS}, "am": 0, "pm": 0, "minutes": 0, "north_min": 0}
    if is_open(day):
        n = poisson(rnd, 8.5 * tr("配達") * (1.55 if rain else 1.0) * (1.15 if day.weekday() == 0 else 1.0))
        lam_m = (5.0 if rain else 0.7) * (0.3 if (rain and S["シフト"]["雨の日の午前の電話番"]) else 1.0)
        missed = poisson(rnd, lam_m)
        calls = n + missed + poisson(rnd, 1.5)
        dl.update(orders=n, missed=missed, calls=calls)
        dl["am_calls"] = int(round(calls * rnd.uniform(0.62, 0.75)))
        north_pm = S["配達"]["北地区を午後便にまとめる"]
        for _ in range(n):
            amt = yen(rnd.uniform(1300, 3600))
            dl["sales"] += amt + (200 if amt < 3000 else 0)
            dl["cost"] += amt * 0.72
            k = pick(rnd, [(k, p) for k, p, _ in DISTRICTS])
            mins = {k2: m2 for k2, _, m2 in DISTRICTS}[k]
            if north_pm and k.startswith("北"):
                mins = 14
            dl["dist"][k] += 1
            mm = max(5, int(round(rnd.gauss(mins, 3))))
            dl["minutes"] += mm
            if k.startswith("北"):
                dl["north_min"] += mm
            am = rnd.random() < 0.68
            if north_pm and k.startswith("北"):
                am = False
            dl["am" if am else "pm"] += 1

    # ネット（通常の注文）
    ec = {"orders": 0, "sales": 0, "cost": 0, "by": {}, "byo": {}, "ch": {}}
    chrnd = random.Random(f"{SEED}-販路-{day.isoformat()}")
    ecs = {12: 1.3, 11: 1.1, 8: 1.15}.get(day.month, 1.0)
    lam = 3.4 * ecs * tr("EC") * (1.15 if day.weekday() >= 5 else 1.0) * ec_ad_factor(ads) * (1.05 if S["ページ改善"] else 1.0)
    n = poisson(rnd, lam)
    for _ in range(n):
        iid = pick(rnd, EC_W)
        q = rnd.choice([1, 2, 2, 3]) if iid == "S01" else (2 if rnd.random() < 0.1 else 1)
        price = price_of(S, iid, day)
        if S["在庫"].get(iid, 0) >= q:
            S["在庫"][iid] -= q
        elif not S["在庫連動"] and S["サイト在庫"].get(iid, 0) >= q:
            S["未出荷"].append({"注文日": day.isoformat(), "商品ID": iid, "数量": q})
        else:
            continue                                     # サイトに「品切れ」と出ていて注文が入らない
        if not S["在庫連動"]:
            S["サイト在庫"][iid] = max(0, S["サイト在庫"].get(iid, 0) - q)
        ec["orders"] += 1
        ec["sales"] += price * q
        ec["cost"] += ITEM[iid][5] * q
        ec["by"][iid] = ec["by"].get(iid, 0) + q
        ec["byo"][iid] = ec["byo"].get(iid, 0) + 1
        add_channel(ec["ch"], pick(chrnd, [(nm, w) for nm, _, w, _ in EC_CHANNELS]), price * q)
    if S["在庫連動"]:
        for iid, _ in EC_W:
            S["サイト在庫"][iid] = S["在庫"].get(iid, 0)
    visits = int(rnd.gauss(150, 20) * ecs * tr("EC") * (1.15 if day.weekday() >= 5 else 1.0) * ec_ad_factor(ads)) + n * 12
    split = [s * rnd.uniform(0.85, 1.15) for s in (0.44, 0.34 * ec_ad_factor(ads), 0.16, 0.10)]
    tot = sum(split)
    ec["flow"] = [int(round(visits * s / tot)) for s in split]
    ec["visits"] = sum(ec["flow"])

    # ギフト
    gift = {ch: {"n": 0, "sales": 0, "cost": 0, "by": {}, "ch": {}} for ch in CHANNELS}
    for ch in CHANNELS:
        season = gift_season(day, ch)
        if not season or (ch != "ネット" and not is_open(day)):
            continue
        k = sround(rnd, GIFT_BASE[season][ch] * gift_shape(day, season) * tr("ギフト_" + ch) * (1.05 if (ch == "ネット" and S["ページ改善"]) else 1.0))
        for _ in range(k):
            g = pick(rnd, [(g, GIFT_W[g]) for g in GIFT if g != "G02" or day >= G02_START])
            gift[ch]["n"] += 1
            gift[ch]["sales"] += GIFT[g][2]
            gift[ch]["cost"] += GIFT[g][3]
            gift[ch]["by"][g] = gift[ch]["by"].get(g, 0) + 1
            if ch == "ネット":
                add_channel(gift[ch]["ch"], pick(chrnd, [(nm, w) for nm, _, w, _ in GIFT_CHANNELS]), GIFT[g][2])
    gift_sales = sum(v["sales"] for v in gift.values())
    fee_today = sum(v["fee"] for v in ec["ch"].values()) + sum(v["fee"] for v in gift["ネット"]["ch"].values())
    gift_cost = sum(v["cost"] for v in gift.values())

    # 法人（定期配達の日）
    b2b = {}
    if is_open(day):
        for cid, c in S["法人"].items():
            if c["出荷"] and day.weekday() in c["曜日"]:
                mult = {12: 1.25, 8: 1.10, 1: 0.85}.get(day.month, 1.0) if CUST[cid][2] in ("飲食店（居酒屋）", "飲食店（焼き鳥）") else 1.0
                b2b[cid] = yen(c["1回の目安"] * mult * rnd.uniform(0.9, 1.1))
    b2b_s = sum(b2b.values())
    b2b_c = sum(yen(v * 0.82) for v in b2b.values())

    # 仕入れ（買掛金に積む：仕入れ≒原価）
    al = supplier_alloc(cost, dl["cost"] + b2b_c, ec["cost"] + gift_cost)
    mk = ym(day)
    S["買掛金"].setdefault(mk, {})
    for s, v in al.items():
        S["買掛金"][mk][s] = yen(S["買掛金"][mk].get(s, 0) + v)

    # お金：入金
    cash_in = store_total + dl["sales"] + ec["sales"] + gift_sales
    for inv in S["売掛金"]:
        if inv["入金日"]:
            continue
        due = d(inv["支払期日"])
        if inv["取引先ID"] != OVERDUE and day >= due:
            inv["入金日"] = day.isoformat()
            cash_in += inv["請求額"]
    late = [i for i in S["売掛金"] if not i["入金日"] and i["取引先ID"] == OVERDUE and d(i["支払期日"]) < day]
    if late:
        dun = S["督促"].get(OVERDUE)
        p = 0.45 if (dun and d(dun) < day) else 0.02
        if rnd.random() < p:
            payset = late if dun else late[:1]
            for inv in payset:
                inv["入金日"] = day.isoformat()
                cash_in += inv["請求額"]
            notes.append(f"［入金］{CUST[OVERDUE][1]} {fmt(sum(i['請求額'] for i in payset))}円")
    # お金：出金
    cash_out, memo = 0, []
    extra = S["人件費の上乗せ"].get(mk, 0)
    if rain and S["シフト"]["雨の日の午前の電話番"] and is_open(day):
        S["人件費の上乗せ"][mk] = extra + 4000
    if S["シフト"]["夕方のレジを2人に"] and day.weekday() in (4, 5):
        S["人件費の上乗せ"][mk] = S["人件費の上乗せ"].get(mk, 0) + 3200
    if day.day == 25:
        cash_out += personnel(day.month, S["人件費の上乗せ"].get(mk, 0))
        memo.append("給料")
    month_close = day == month_last(day)

    journal_today = {"売上_店舗": store_total, "売上_配達": dl["sales"], "売上_EC": ec["sales"], "売上_ギフト": gift_sales,
                     "売上_法人": b2b_s, "原価_店舗": yen(store_cost), "原価_配達": yen(dl["cost"]), "原価_EC": ec["cost"],
                     "原価_ギフト": gift_cost, "原価_法人": b2b_c}
    if month_close:
        cash_out_close, close_notes = close_month(paths, S, day, journal_today, dl["orders"], fee_today, b2b)
        cash_out += cash_out_close
        memo.append("月末の支払い（仕入れ・経費・借入金）")
        notes += close_notes
    cash_after = S["現金"] + cash_in - cash_out
    S["現金"] = cash_after

    # ── 書く ──
    py = prior(paths, cache, day)
    append_csv(D / "store/POS_日別.csv", [pos_row(day, w, dept, cust, int(py["店の合計"]) if py else "")])
    roll(D / "store/POS_商品別_直近14日.csv", item_rows(day, qty, sales, cost) if is_open(day) else [], day, 14, open_only=True)
    append_csv(D / "delivery/配達_日別.csv", [dl_row(day, w, dl, int(py["配達の売上"]) if py else "")])
    append_csv(D / "ec/注文_日別.csv", [ec_row(day, ec, int(py["ECの売上"]) if py else "")])
    roll(D / "ec/注文_商品別_直近28日.csv",
         [[day.isoformat(), iid, ITEM[iid][1], ec["byo"][iid], ec["by"][iid], unit(iid)] for iid in sorted(ec["byo"])], day, 28)
    append_csv(D / "gift/ギフト受注_日別.csv", [gift_row(day, ch, gift[ch]) for ch in CHANNELS if gift[ch]["n"]])
    append_csv(D / "ec/チャネル別_日別.csv", ch_rows(day, ec["ch"], gift["ネット"]["ch"]))
    append_csv(D / "b2b/納品_日別.csv", [[day.isoformat(), cid, CUST[cid][1], v, v - yen(v * 0.82)] for cid, v in sorted(b2b.items())])
    s_tot = sum(journal_today["売上_" + b] for b in BIZ)
    c_tot = sum(journal_today["原価_" + b] for b in BIZ)
    append_csv(D / "accounting/日計表.csv", [[day.isoformat(), WD[day.weekday()], w, *[journal_today["売上_" + b] for b in BIZ], s_tot,
                                           *[journal_today["原価_" + b] for b in BIZ], c_tot, s_tot - c_tot, lost, yen(waste),
                                           cash_in, cash_out, cash_after, "・".join(memo)]])
    if month_close:
        finish_month_files(paths, S, day)
    if day.weekday() == 6:
        sns_week(paths, S, day)
    new_reviews(paths, S, day, rnd, qty, fest)
    # 夜：定期の自動発注（承認がいらない仕入先だけ・行事を先読み）
    auto_reorder(S, day)
    outs = [ITEM[i][1] for i in STOCKED if S["在庫"].get(i, 0) <= 0]
    return {"day": day, "weather": w, "store": store_total, "alc": dept["酒類"], "cust": cust, "dl": dl["orders"],
            "ec": ec["orders"], "gift": sum(v["n"] for v in gift.values()), "b2b": b2b_s, "notes": notes, "outs": outs,
            "cash": cash_after, "lost": lost}


def morning(S, day) -> list:
    """朝：入荷 → ネットの未出荷を先に出す → 毎日の生ものをそろえる。"""
    notes = []
    for o in S["発注"]:
        if o["状態"] == "未入荷" and d(o["入荷予定日"]) <= day:
            S["在庫"][o["商品ID"]] = S["在庫"].get(o["商品ID"], 0) + o["数量"]
            o["状態"] = "入荷済み"
            if o["発注者"] != "定期（自動）":
                notes.append(f"［入荷］{o['商品']} {qty_s(o['商品ID'], o['数量'])}")
    shipped = 0
    for u in list(S["未出荷"]):
        if S["在庫"].get(u["商品ID"], 0) >= u["数量"]:
            S["在庫"][u["商品ID"]] -= u["数量"]
            S["未出荷"].remove(u)
            shipped += 1
    if shipped:
        notes.append(f"［出荷］ネットの待っていた注文 {shipped}件")
    for iid in DAILY_FRESH:
        target = math.ceil(S["平均販売"].get(iid, ITEM[iid][6]) * 1.6) + 2
        S["在庫"][iid] = max(S["在庫"].get(iid, 0), target)
    for iid in list(S.setdefault("欠品記録", {})):
        if S["在庫"].get(iid, 0) > 0:
            del S["欠品記録"][iid]
    S["朝の処理済み"] = day.isoformat()
    return notes


def expected(S, iid, x: dt.date) -> float:
    """その日の売れ数の見込み（店＋ネット）。行事の日は倍率と屋台の分を足す。"""
    it = ITEM[iid]
    avg = max(S["平均販売"].get(iid, 0), it[6] * 0.5)
    if not is_open(x):
        return avg * 0.15 if it[10] else 0.0
    v = avg * WDF[x.weekday()] / 1.03
    ev = next((e for e in S["行事"] if e["日付"] == x.isoformat() and e["倍率"] > 1), None)
    if ev:
        if it[2] == "酒類" or it[3] == "飲料":
            v *= ev["倍率"] + (0.2 if ev["告知"] else 0)
        if ev["屋台"]:
            v += STALL.get(iid, 0) + (5 if (iid == "S01" and ev["告知"]) else 0)
    return v


def auto_reorder(S, day: dt.date):
    """定期（自動）の発注：在庫＋入荷待ちが「入荷の日までに売れる見込み＋2日分」か発注点を下回ったら、入荷のあと7日分まで頼む。"""
    for iid in STOCKED:
        it = ITEM[iid]
        if iid in DAILY_FRESH or is_manual(iid):
            continue
        arr = arrival_date(day, iid)
        pos = S["在庫"].get(iid, 0) + sum(o["数量"] for o in S["発注"] if o["商品ID"] == iid and o["状態"] == "未入荷")
        until = [day + dt.timedelta(days=k) for k in range(1, (arr - day).days + 1)]
        cover = [arr + dt.timedelta(days=k) for k in range(1, 8)]
        avg = max(S["平均販売"].get(iid, 0), it[6] * 0.5)
        level = max(sum(expected(S, iid, x) for x in until) + 2 * avg, reorder_point(iid))
        if pos < level:
            q = max(math.ceil(level + sum(expected(S, iid, x) for x in cover) - pos), math.ceil(avg * 3), 1)
            add_order(S, day, iid, q, "定期（自動）")


def add_order(S, day, iid, q, who):
    it = ITEM[iid]
    n = len(S["発注"]) + 1
    o = {"番号": f"P{day.strftime('%m%d')}-{n:03d}", "発注日": day.isoformat(), "仕入先": it[8], "商品ID": iid, "商品": it[1],
         "数量": int(q), "金額": it[5] * int(q), "入荷予定日": arrival_date(day, iid).isoformat(), "状態": "未入荷", "発注者": who}
    S["発注"].append(o)
    return o


def roll(path, new_rows, day, keep_days, open_only=False):
    """直近だけ残すファイル：新しい行を足して、古い日付を落とす（open_only は営業日で数える）。"""
    h = header_of(path)
    rows = [[r[k] for k in h] for r in read_csv(path)] + [[str(x) for x in r] for r in new_rows]
    if open_only:
        keep = set(sorted({r[0] for r in rows})[-keep_days:])
    else:
        cut = (day - dt.timedelta(days=keep_days - 1)).isoformat()
        keep = {r[0] for r in rows if r[0] >= cut}
    write_csv(path, h, [r for r in rows if r[0] in keep], _note_of(path))


def _note_of(path):
    with open(path, encoding="utf-8") as f:
        first = f.readline().strip()
    return first[2:].replace(NOTE, "").lstrip("。")


def close_month(paths, S, day, today_j, dl_orders_today, fee_today, b2b_today):
    """月末：法人に請求・月次PL を締める・先月分の仕入れと今月の経費と借入金を払う。出金の合計を返す。"""
    D = paths.data
    m = day.replace(day=1)
    rows = [r for r in read_csv(D / "accounting/日計表.csv") if r["日付"].startswith(ym(m))]
    sums = {k: sum(int(r[k]) for r in rows) + today_j[k] for k in today_j}
    dl_orders = sum(int(r["配達件数"]) for r in read_csv(D / "delivery/配達_日別.csv") if r["日付"].startswith(ym(m))) + dl_orders_today
    fee = sum(int(r["手数料"]) for r in read_csv(D / "ec/チャネル別_日別.csv") if r["日付"].startswith(ym(m))) + fee_today
    exp = month_expenses(m, sums["売上_店舗"], fee, dl_orders, ads_cost(m, S["広告"]),
                         S["人件費の上乗せ"].get(ym(m), 0))
    pl = read_csv(D / "accounting/月次PL.csv")
    prev = next((r for r in pl if r["月"] == ym(add_months(m, -12))), None)
    row = pl_row(m, sums, exp, int(prev["売上合計"]) if prev else "")
    S["_close"] = {"pl": row, "m": ym(m), "b2b_today": b2b_today}
    # 請求（今月の納品の合計）
    b2b_rows = read_csv(D / "b2b/納品_日別.csv")
    for c in CUSTOMERS:
        amt = sum(int(r["金額"]) for r in b2b_rows if r["日付"].startswith(ym(m)) and r["取引先ID"] == c[0]) + b2b_today.get(c[0], 0)
        if amt:
            S["売掛金"].append({"取引先ID": c[0], "取引先": c[1], "請求の月": ym(m), "請求額": amt, "請求日": day.isoformat(),
                             "支払期日": month_last(add_months(m, 1)).isoformat(), "入金日": None})
    prev_pay = S["買掛金"].pop(ym(add_months(m, -1)), {})
    out = sum(prev_pay.values()) + sum(exp[k] for k in CASH_EXP) + LOAN
    S["月の締め"] = ym(m)
    notes = [f"［月末］{m.month}月を締めました：売上 {fmt(row['売上合計'])}円・営業利益 {fmt(row['営業利益'])}円"]
    return out, notes


def finish_month_files(paths, S, day):
    D = paths.data
    c = S.pop("_close")
    m = d(c["m"] + "-01")
    append_csv(D / "accounting/月次PL.csv", [[c["pl"][k] for k in PL_COLS]])
    b2b_rows = read_csv(D / "b2b/納品_日別.csv")
    rows = []
    for cid, *_ in CUSTOMERS:
        da = [(r["日付"], int(r["金額"])) for r in b2b_rows if r["日付"].startswith(c["m"]) and r["取引先ID"] == cid]
        rows.append(b2b_month_row(m, cid, da))
    append_csv(D / "b2b/法人売上_月別.csv", rows)
    append_csv(D / "marketing/広告.csv", [[c["m"]] + r + [round(r[6] / r[2], 1) if (r[2] and r[6] != "") else ""]
                                        for r in ad_rows(m, S["広告"])])


def sns_week(paths, S, sunday):
    mon = sunday - dt.timedelta(days=6)
    rnd = random.Random(f"{SEED}-SNS-{mon.isoformat()}")
    path = paths.data / "marketing/SNS.csv"
    rows = read_csv(path)
    fol = int(rows[-1]["フォロワー（週末）"]) if rows else 850
    posted = [n[1] for n in S["お知らせ"] if mon.isoformat() <= n[0] <= sunday.isoformat() and "Instagram" in n[2]]
    post = posted[0].split("（")[0] if posted else rnd.choice(["日替わり惣菜の紹介", "地酒の飲みくらべ", "店主のおすすめのおつまみ"])
    n = rnd.choice([2, 3, 3, 4]) + len(posted)
    reach = int(n * rnd.uniform(260, 420) + 300 + (600 if posted else 0)) * (1 + 0.3 * (S["広告"]["Instagram広告"] - 12000) / 12000)
    reach = int(reach)
    fol += rnd.randint(4, 13) + (8 if posted else 0)
    append_csv(path, [[mon.isoformat(), n, fol, reach, int(reach * rnd.uniform(0.07, 0.11)), int(reach * rnd.uniform(0.01, 0.025)),
                       int(reach * rnd.uniform(0.04, 0.07)), int(reach * rnd.uniform(0.02, 0.04)), post]])
    lp = paths.data / "marketing/LINE.csv"
    lr = read_csv(lp)
    fr = int(lr[-1]["友だちの数（週末）"]) if lr else 420
    append_csv(lp, [[mon.isoformat(), fr + rnd.randint(2, 6) + (5 if posted else 0), 1 + (1 if posted else 0),
                     round(rnd.uniform(52, 64), 1), rnd.randint(6, 15)]])


def new_reviews(paths, S, day, rnd, qty, fest):
    path = paths.data / "marketing/口コミ.csv"
    add = []
    if is_open(day):
        r = random.Random(f"{SEED}-口コミ-{day.isoformat()}")
        if qty.get("S01", 0) == 0 and r.random() < 0.25:
            add.append([day.isoformat(), "Googleの口コミ", 2, "播磨ゴールド、まだ入っていないんですね。いつ戻りますか。", "未返信"])
        elif qty.get("S01", 0) > 0 and S.get("播磨ゴールド_前の営業日は欠品") and r.random() < 0.6:
            add.append([day.isoformat(), "Googleの口コミ", 5, "播磨ゴールドが戻ってた！祭りの前に買えてよかった。", "未返信"])
        if fest and qty.get("S01", 0) > 0:
            add.append([day.isoformat(), "Googleの口コミ", 5, "祭りの屋台の地ビール、冷えていておいしかった。", "未返信"])
        if day.weekday() in (4, 5) and not S["シフト"]["夕方のレジを2人に"] and r.random() < 0.08:
            add.append([day.isoformat(), "Googleの口コミ", 3, "夕方のレジ待ちが長かった。", "未返信"])
        S["播磨ゴールド_前の営業日は欠品"] = qty.get("S01", 0) == 0
    append_csv(path, add)


def cmd_advance(paths: Paths, days: int, quiet=False):
    t0 = time.time()
    S = load_state(paths)
    unlock(paths)
    cache = {}
    digests = []
    try:
        for _ in range(days):
            day = d(S["今日"])
            digests.append(simulate_day(paths, S, day, cache))
            S["今日"] = (day + dt.timedelta(days=1)).isoformat()
            S["値下げ"] = [v for v in S["値下げ"] if d(v["まで"]) >= d(S["今日"])]
        morning_notes = morning(S, d(S["今日"]))
        refresh_derived(paths, S)
        save_state(paths, S)
    finally:
        lock(paths)
    if not quiet:
        print(f"{days}日進めました（{time.time() - t0:.1f}秒）。今日＝{jp(d(S['今日']))}")
        for g in digests:
            x = g["day"]
            if not is_open(x):
                line = f"{jp(x)} {g['weather']}　定休日（ネットの注文 {g['ec']}件）"
            else:
                line = (f"{jp(x)} {g['weather']}　店 {fmt(g['store'])}円（酒類 {fmt(g['alc'])}）・客 {g['cust']}人・"
                        f"配達 {g['dl']}件・ネット {g['ec']}件・ギフト {g['gift']}件")
                if g["lost"]:
                    line += f"・欠品で取り逃がし {fmt(g['lost'])}円"
            print(line + ("　" + "　".join(g["notes"]) if g["notes"] else ""))
        if morning_notes:
            print(f"{jp(d(S['今日']))}の朝：" + "　".join(morning_notes))
        print(status_text(paths, S))
    return S, digests


# ══ 派生ファイル（state から作り直す） ═══════════════════════════════
def refresh_derived(paths: Paths, S: dict):
    D = paths.data
    today = d(S["今日"])
    # 在庫
    rows = []
    items14 = read_csv(D / "store/POS_商品別_直近14日.csv")
    ec28 = read_csv(D / "ec/注文_商品別_直近28日.csv")
    open14 = len({r["日付"] for r in items14}) or 1
    for iid in STOCKED:
        it = ITEM[iid]
        sold = sum(int(r["数量"] or 0) for r in items14 if r["商品ID"] == iid)
        sold += sum(int(r["数量"]) for r in ec28 if r["商品ID"] == iid and r["日付"] >= (today - dt.timedelta(days=14)).isoformat())
        per = round(sold / open14, 1)
        S["平均販売"][iid] = max(per, 0.1)
        q = S["在庫"].get(iid, 0)
        pend = sorted(o["入荷予定日"] for o in S["発注"] if o["商品ID"] == iid and o["状態"] == "未入荷")
        arr = "毎朝（定期）" if iid in DAILY_FRESH else ("・".join(
            f"{p} に {qty_s(iid, sum(o['数量'] for o in S['発注'] if o['商品ID'] == iid and o['入荷予定日'] == p and o['状態'] == '未入荷'))}"
            for p in sorted(set(pend))))
        how = "毎日の定期" if iid in DAILY_FRESH else ("承認がいる" if is_manual(iid) else "定期（自動）")
        rows.append([iid, it[1], unit(iid), it[2], q, reorder_point(iid), per, round(q / per, 1) if per else "", it[8], it[9], how,
                     price_of(S, iid, today), arr])
    for gid, gname, price, cost in GIFTS:
        rows.append([gid, gname, unit(gid), "ギフト", "", "", "", "", "□□酒造・播磨麦酒（架空）ほか", 4, "注文ごと", price, "注文ごとに組む"])
    write_csv(D / "purchasing/在庫.csv", ["商品ID", "商品", "単位", "部門", "在庫（今朝）", "発注点", "1日の平均販売（直近14日・店頭＋ネット）",
                                         "あと何日もつか（目安）", "仕入先", "納期（日）", "発注の決め方", "今の値段", "入荷予定（日付と数）"], rows,
              f"今朝＝{today}。在庫・発注点・平均は「単位」で数える（例：播磨ゴールドは6缶入りのパックの数）。惣菜・お弁当・おにぎりは店内で作るので在庫なし")
    # 発注履歴
    cut = (today - dt.timedelta(days=28)).isoformat()
    rows = [[o["発注日"], o["仕入先"], o["商品ID"], o["商品"], o["数量"], unit(o["商品ID"]), o["金額"], o["入荷予定日"],
             ("今日入荷" if o["入荷予定日"] == today.isoformat() and o["状態"] == "未入荷" else o["状態"]), o["発注者"]]
            for o in S["発注"] if o["発注日"] >= cut or o["状態"] == "未入荷"]
    write_csv(D / "purchasing/発注履歴.csv", ["発注日", "仕入先", "商品ID", "商品", "数量", "単位", "金額（原価）", "入荷予定日", "状態", "だれが"],
              rows, "直近4週と、まだ入っていない発注。毎日の定期発注（パン・牛乳・卵・豆腐・納豆・青果・肉・魚）は載せていない")
    # 売掛金
    months = sorted({r["請求の月"] for r in S["売掛金"]})[-4:]
    rows = []
    for r in S["売掛金"]:
        if r["請求の月"] not in months and r["入金日"]:
            continue
        due = d(r["支払期日"])
        if r["入金日"]:
            late = (d(r["入金日"]) - due).days
            state = "入金済み" + (f"（期日から{late}日遅れ）" if late > 0 else "")
            over = ""
        elif due >= today:
            state, over = "期日前", ""
        else:
            state, over = "期日を過ぎて未入金", (today - due).days
        dun = S["督促"].get(r["取引先ID"])
        if dun and not r["入金日"] and over != "":
            state += f"（{dun} に督促）"
        rows.append([r["取引先ID"], r["取引先"], r["請求の月"], r["請求額"], r["請求日"], r["支払期日"], r["入金日"] or "", state, over])
    write_csv(D / "accounting/売掛金.csv", ["取引先ID", "取引先", "請求の月", "請求額", "請求日", "支払期日", "入金日", "状態", "期日から何日過ぎたか"],
              rows, "法人の取引先だけ（月末締め翌月末払い）。直近4か月の請求と、まだ入っていない請求")
    # 買掛金
    rows = []
    for mk in sorted(S["買掛金"]):
        due = month_last(add_months(d(mk + "-01"), 1))
        state = "支払い予定" if mk < ym(today) else "今月の仕入れ（途中）"
        for s, v in sorted(S["買掛金"][mk].items(), key=lambda x: -x[1]):
            rows.append([s, mk, v, due.isoformat(), state])
    write_csv(D / "accounting/買掛金.csv", ["仕入先", "仕入れの月", "金額", "支払期日", "状態"], rows,
              "仕入れ≒その日の売上原価として積んでいる（在庫の増減は小さいので省いている）")
    write_cashplan(paths, S, today)
    write_ec_pages(paths, S, today)
    write_gift_weekly(paths, today)
    write_csv(D / "legal/契約.csv", ["相手", "契約の種類", "始まった日", "期間", "次の更新日", "自動更新", "条件を変えたいときの申し出期限", "担当", "メモ", "状態"],
              [[c[k] for k in ("相手", "契約の種類", "始まった日", "期間", "次の更新日", "自動更新", "条件を変えたいときの申し出期限", "担当", "メモ", "状態")]
               for c in S["契約"]])
    (D / "pr").mkdir(parents=True, exist_ok=True)
    (D / "pr/お知らせ.md").write_text(notices_md(S), encoding="utf-8")
    (D / "pr/地域の予定.md").write_text(region_md(S, today), encoding="utf-8")
    (D / "_sources.json").write_text(json.dumps(sources_json(today.isoformat()), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (D / "README.md").write_text(data_readme(paths, today), encoding="utf-8")


def write_cashplan(paths, S, today):
    D = paths.data
    m0 = today.replace(day=1)
    m1 = add_months(m0, 1)
    j = read_csv(D / "accounting/日計表.csv")[-28:]
    daily = sum(int(r["売上_店舗"]) + int(r["売上_配達"]) + int(r["売上_EC"]) + int(r["売上_ギフト"]) for r in j) / max(1, len(j))
    rest = (month_last(today) - today).days + 1
    days1 = (month_last(m1) - m1).days + 1
    sales_now = int(round(daily * rest, -3))
    sales_next = int(round(daily * days1 * SEASON[m1.month] / SEASON[m0.month], -3))
    recv_now = sum(r["請求額"] for r in S["売掛金"] if not r["入金日"] and r["取引先ID"] != OVERDUE
                   and today <= d(r["支払期日"]) <= month_last(today))
    b2b_rows = read_csv(D / "b2b/納品_日別.csv")
    mtd = {c[0]: sum(int(r["金額"]) for r in b2b_rows if r["日付"].startswith(ym(m0)) and r["取引先ID"] == c[0]) for c in CUSTOMERS}
    elapsed = max(1, (today - m0).days)
    full = (month_last(m0) - m0).days + 1
    recv_next = sum(int(round(v / elapsed * full, -3)) for cid, v in mtd.items() if cid != OVERDUE)
    recv_next += sum(r["請求額"] for r in S["売掛金"] if not r["入金日"] and r["取引先ID"] != OVERDUE and month_last(today) < d(r["支払期日"]) <= month_last(m1))
    unpaid = sum(r["請求額"] for r in S["売掛金"] if not r["入金日"] and r["取引先ID"] == OVERDUE)
    unpaid_over = sum(r["請求額"] for r in S["売掛金"] if not r["入金日"] and r["取引先ID"] == OVERDUE and d(r["支払期日"]) < today)
    ap_now = sum(S["買掛金"].get(ym(add_months(m0, -1)), {}).values())
    ap_cur = sum(S["買掛金"].get(ym(m0), {}).values())
    ap_next = int(round(ap_cur / elapsed * full, -3)) if today.day > 1 else ap_cur
    pl = read_csv(D / "accounting/月次PL.csv")
    exp_last = sum(int(pl[-1][k]) for k in CASH_EXP) if pl else 330000
    pers_now = personnel(m0.month, S["人件費の上乗せ"].get(ym(m0), 0)) if today.day <= 25 else 0
    rows_in = [("店・配達・ネット・ギフトの売上（見込み）", sales_now, sales_next, "直近28日の1日平均から"),
               ("法人の売掛金の回収", recv_now, recv_next,
                f"居酒屋 千鳥足（架空）の未回収 {fmt(unpaid)}円（うち期日を過ぎた分 {fmt(unpaid_over)}円）は入れていない" if unpaid else "")]
    rows_out = [("仕入れの支払い（買掛金）", ap_now, ap_next, ""),
                ("人件費", pers_now, personnel(m1.month), "25日" + ("（今月はもう払った）" if today.day > 25 else "")),
                ("経費（広告・家賃・光熱・車・手数料など）", exp_last, exp_last, "先月の実績から"),
                ("借入金の返済（△△銀行・架空）", LOAN, LOAN, "")]
    cash = S["現金"]
    in0, in1 = sum(r[1] for r in rows_in), sum(r[2] for r in rows_in)
    out0, out1 = sum(r[1] for r in rows_out), sum(r[2] for r in rows_out)
    end0 = cash + in0 - out0
    end1 = end0 + in1 - out1
    rows = [["残高", "今の残高（今朝）／来月初の見込み", cash, end0, "△△銀行（架空）の普通預金"]]
    rows += [["入金", k, a, b, memo] for k, a, b, memo in rows_in]
    rows.append(["入金", "入金の合計", in0, in1, ""])
    rows += [["出金", k, a, b, memo] for k, a, b, memo in rows_out]
    rows.append(["出金", "出金の合計", out0, out1, ""])
    rows.append(["残高", "月末の残高（見込み）", end0, end1, ""])
    write_csv(D / "accounting/資金繰り.csv", ["区分", "項目", f"今月の残り（{today.month}/{today.day}〜{month_last(today).day}日）",
                                             f"来月（{ym(m1)}）", "メモ"], rows, "見込み。今朝の残高から月末までの入金と出金")


def write_ec_pages(paths, S, today):
    D = paths.data
    ec28 = read_csv(D / "ec/注文_商品別_直近28日.csv")
    gifts = read_csv(D / "gift/ギフト受注_日別.csv")
    cut = (today - dt.timedelta(days=28)).isoformat()
    rows = []
    for iid, _ in EC_W:
        it = ITEM[iid]
        buys = sum(int(r["注文数"]) for r in ec28 if r["商品ID"] == iid)
        rnd = random.Random(f"{SEED}-閲覧-{iid}-{today}")
        views = int(buys / rnd.uniform(0.022, 0.035)) + 40
        ly = ly_count(paths, f"EC_{iid}", today)
        uns = sum(1 for u in S["未出荷"] if u["商品ID"] == iid)
        rows.append([iid, it[1], unit(iid), "通常", price_of(S, iid, today), views, buys, round(buys / views * 100, 1), ly,
                     S["サイト在庫"].get(iid, 0), S["在庫"].get(iid, 0), uns, "○"])
    for gid, gname, price, cost in GIFTS:
        buys = sum(int(r[gid]) for r in gifts if r["受付"] == "ネット" and r["日付"] >= cut)
        rnd = random.Random(f"{SEED}-閲覧-{gid}-{today}")
        views = int(buys / rnd.uniform(0.03, 0.045)) + 60
        ly = ly_count(paths, f"ネット_{gid}", today)
        rows.append([gid, gname, unit(gid), "ギフト", price, views, buys, round(buys / views * 100, 1), ly, "受注ごと", "受注ごと", 0,
                     S["表示"].get(gid, "○")])
    write_csv(D / "ec/商品ページ.csv", ["商品ID", "商品", "単位", "種類", "価格", "閲覧数（直近4週）", "購入数（直近4週）", "購入率(%)",
                                       "前年同期の購入数（4週）", "サイトに出ている在庫", "実際の在庫（今朝）", "まだ出荷していない注文（件）",
                                       "「20歳未満の飲酒は法律で禁止」の表示"], rows,
              "在庫の数は「単位」で数える。サイトの在庫は手で更新している（在庫連動にすると毎日そろう）。購入数は注文の件数。ギフトの購入数は gift/ のネット分")


def ly_count(paths, col, today):
    """去年の同じ4週（364日前）の数を、sim/前年_日別.csv から足す。"""
    pr = {r["日付"]: r for r in read_csv(paths.prior)}
    days = [(today - dt.timedelta(days=i)).isoformat() for i in range(1, 29)]
    return sum(int(pr[x][col]) for x in days if x in pr and col in pr[x])


def write_gift_weekly(paths, today):
    D = paths.data
    yday = today - dt.timedelta(days=1)
    rows_d = read_csv(D / "gift/ギフト受注_日別.csv")
    pr = {r["日付"]: r for r in read_csv(paths.prior)}
    seasons = []
    for y in (today.year - 1, today.year):
        seasons += [(dt.date(y, 6, 10), "お中元"), (dt.date(y, 10, 20), "お歳暮")]
    s_start, s_name = max(s for s in seasons if s[0] <= yday)
    wk = s_start - dt.timedelta(days=s_start.weekday())
    out = []
    while wk <= yday:
        wdays = [(wk + dt.timedelta(days=i)).isoformat() for i in range(7) if wk + dt.timedelta(days=i) <= yday]
        for ch in CHANNELS:
            n = sum(int(r["件数"]) for r in rows_d if r["日付"] in wdays and r["受付"] == ch)
            s = sum(int(r["売上"]) for r in rows_d if r["日付"] in wdays and r["受付"] == ch)
            pn = sum(int(pr[x][f"ギフト_{ch}_件数"]) for x in wdays if x in pr)
            ps = sum(int(pr[x][f"ギフト_{ch}_売上"]) for x in wdays if x in pr)
            out.append([wk.isoformat(), s_name, ch, n, s, pn, ps, "途中（昨日まで）" if len(wdays) < 7 else ""])
        wk += dt.timedelta(days=7)
    write_csv(D / "gift/ギフト受注_週別.csv", ["週の初め（月曜）", "シーズン", "受付", "件数（送り先の数）", "売上", "前年同週の件数", "前年同週の売上", "備考"],
              out, "のし付きギフトの承り（店頭・電話・ネット・法人）。去年のお歳暮は店頭・電話・法人の受付を11/20に始めた（ネットは10/20）")


def notices_md(S):
    items = sorted(S["お知らせ"], key=lambda x: x[0], reverse=True)
    lines = ["# お知らせ（サイト・Instagram・店頭に出したもの）", "", "※架空のデータです（株式会社やまだ商店はサンプル企業で実在しません）。", "",
             "| 日付 | 題 | 出した場所 |", "|---|---|---|"]
    lines += [f"| {x[0]} | {x[1]} | {x[2]} |" for x in items]
    lines += ["", "サイト：やまだ商店のホームページ（架空）のお知らせ欄。ここに無いものは、まだどこにも出していない。", ""]
    return "\n".join(lines)


def region_md(S, today):
    evs = [e for e in S["行事"] if d(e["日付"]) >= today]
    lines = ["# 地域の予定（店主のメモ）", "", f"※架空のデータです（株式会社やまだ商店はサンプル企業で実在しません）。今日＝{today.isoformat()}", "", "## 近いうちの予定"]
    for e in evs:
        x = d(e["日付"])
        if e["屋台"]:
            lines += [f"- {x.isoformat()}（{WD[x.weekday()]}）{e['名前']}（10時〜21時）。",
                      "  - 毎年、この日は酒類と飲料が普段の土曜の2倍近く売れる。地ビールが特に人気。",
                      "  - やまだ商店も神社の前に屋台を出す（地ビール・地酒・ラムネ）。去年の屋台では播磨ゴールドが約25パック（150缶）出た。",
                      "  - 屋台の飲み物は前の日（金曜）の夕方から冷やし始める。"]
        else:
            lines.append(f"- {x.isoformat()}（{WD[x.weekday()]}）{e['名前']}（お弁当の材料・飲み物がよく出る）")
    if not evs:
        lines.append("- いま決まっている町の行事はない。")
    lines += ["- 年末に向けて、お歳暮の承り中（地酒のセットがよく出る）。12月28日〜31日は年末の買い物で店がいちばん混む。",
              "- 年末年始：12月31日は17時まで。1月1日〜3日はお休み。", "", "## 天気予報（今日から5日）"]
    lines.append("　".join(f"{(today + dt.timedelta(days=i)).month}/{(today + dt.timedelta(days=i)).day}（{WD[(today + dt.timedelta(days=i)).weekday()]}）"
                          f"{weather(S, today + dt.timedelta(days=i))}" for i in range(5)))
    lines += ["", "## 町内のこと", "- 北地区の高台の団地は、坂がきつく、お年寄りの一人暮らしが多い。配達の注文がいちばん多い地区。",
              "- 雨の日は「お店に行けないから配達で」という電話が朝に増える。", ""]
    return "\n".join(lines)


def data_readme(paths, today):
    files = sorted(str(p.relative_to(paths.data)) for p in paths.data.rglob("*") if p.is_file() and p.name != "README.md")
    files = files if "_sources.json" in files else files + ["_sources.json"]
    desc = {
        "master/商品.csv": "商品の一覧（部門・単価・原価・仕入先・納期・発注点・ネットに出しているか）",
        "master/仕入先.csv": "仕入先と発注の決まり（納期・締め・最低の発注・承認がいるか）",
        "master/法人顧客.csv": "法人の取引先と定期配達の曜日",
        "master/従業員.csv": "8人の役割と勤務、一緒に動くAI",
        "store/POS_日別.csv": "店の売上（部門別）・客数・客単価・天気・前年同曜日。日曜は定休日で0",
        "store/POS_商品別_直近14日.csv": "直近14営業日の商品ごとの数と売上",
        "delivery/配達_日別.csv": "電話注文の配達（着信・取れなかった電話・件数・売上・地区・便・時間）",
        "ec/注文_日別.csv": "ネットショップの通常の注文（訪問・注文・売上・流入元）",
        "ec/注文_商品別_直近28日.csv": "ネットの通常の注文を商品ごとに（直近28日）",
        "ec/チャネル別_日別.csv": "ネット3店（自社サイト・楽天市場・Amazon）の注文・売上・手数料（通常＋ギフト）",
        "marketing/LINE.csv": "LINE 公式アカウントの友だち・配信・開封・クーポン（週ごと）",
        "_sources.json": "どのサービスからどのデータを取り込む「ことにしている」か（データマップ・全部シミュレーション）",
        "ec/商品ページ.csv": "ネットの商品ページ（閲覧・購入・前年同期・サイトの在庫と実際の在庫・未出荷・お酒の表示）",
        "gift/ギフト受注_日別.csv": "のし付きギフトの承り（日・受付ごと）",
        "gift/ギフト受注_週別.csv": "今のシーズンのギフト（週・受付ごと・前年同週）",
        "b2b/納品_日別.csv": "法人への納品（定期配達の日ごと）",
        "b2b/法人売上_月別.csv": "法人の売上（月×取引先・納品回数）",
        "purchasing/在庫.csv": "今朝の在庫・発注点・1日の平均販売・今の値段・入荷予定",
        "purchasing/発注履歴.csv": "直近4週の発注とまだ入っていない発注",
        "accounting/日計表.csv": "毎日の帳簿（事業別の売上と原価・欠品で逃した売上・廃棄・入金・出金・現金残高）",
        "accounting/月次PL.csv": "月の損益（事業別の売上と粗利・経費・営業利益・前年同月）",
        "accounting/予算.csv": "今年度の予算（月×事業）",
        "accounting/売掛金.csv": "法人への請求と入金",
        "accounting/買掛金.csv": "仕入先への支払い予定",
        "accounting/資金繰り.csv": "今月の残りと来月のお金の出入りの見込み",
        "marketing/広告.csv": "広告の費用と反応（月・媒体別）",
        "marketing/口コミ.csv": "Google の口コミ（Google ビジネスプロフィール）とネットショップの口コミ",
        "marketing/SNS.csv": "Instagram の週ごとの数字",
        "pr/お知らせ.md": "サイト・Instagram・店頭に出したお知らせ",
        "pr/地域の予定.md": "町の行事・天気予報・店主のメモ",
        "legal/契約.csv": "契約の一覧（相手・種類・更新日・申し出期限・状態）",
        "legal/許認可.csv": "免許・許可・責任者・個人情報の扱い",
    }
    lines = ["# data/ の説明", "", "**全部、架空のデータです。** 株式会社やまだ商店はサンプル企業で、実在しません。",
             "書くのは `tools/sim.py` だけ（AI も人も手で書きかえない。ファイルは読むだけの設定）。",
             "スマレジ・Shopify・楽天・Amazon・freee などからの取り込みは **シミュレーション**（実際にはつないでいない）。対応は `_sources.json` と `company/データマップ.md`。", "",
             f"- 今日＝{today.isoformat()}（{WD[today.weekday()]}）。データは昨日＝{(today - dt.timedelta(days=1)).isoformat()} まで。",
             "- 金額はすべて円・税抜。",
             "- CSV の1行目は `#` で始まる注意書き。2行目が見出し。手早く見るなら `python3 tools/q.py <名前>`（`python3 tools/q.py 一覧`）。",
             "- 日曜と 1月1日〜3日は店の休み（POS・配達は0）。ネットショップは毎日注文が入る。",
             "- 5つの事業：店舗（store）・配達（delivery）・EC（ec）・法人（b2b）・ギフト（gift）。月次PL と日計表の事業別の売上は、それぞれのファイルの合計と同じ。",
             "", "| ファイル | 中身 |", "|---|---|"]
    lines += [f"| `{f}` | {desc.get(f, '')} |" for f in files]
    lines.append("")
    return "\n".join(lines)


# ══ apply ══════════════════════════════════════════════════
class ApplyError(Exception):
    pass


def cmd_apply(paths: Paths, pid: str, quiet=False):
    f = find_proposal(paths.approved, pid)
    if not f:
        where = "承認待ち（approvals/pending/）にあります。/承認 で承認してから" if find_proposal(paths.pending, pid) else "見つかりません"
        raise ApplyError(f"{pid} は承認されていません（approvals/approved/ に無い）。{where}。")
    fm, body = parse_proposal(f)
    if "## 決定" not in body or "承認" not in body.split("## 決定", 1)[1]:
        raise ApplyError(f"{pid} に承認の記録（## 決定）がありません。/承認 から通してください。")
    errs = check_proposal(fm)
    if errs:
        raise ApplyError(f"{pid} の書き方に足りない所があります：{'・'.join(errs)}")
    S = load_state(paths)
    if pid in S["適用済み"]:
        raise ApplyError(f"{pid} はもう入れてあります（二重には入れません）。")
    today = d(S["今日"])
    act = fm.get("実行") or {}
    done = []
    unlock(paths)
    try:
        for kind, v in act.items():
            if kind == "発注":
                for line in v:
                    iid, q = line["商品ID"], int(line["数量"])
                    if iid not in ITEM:
                        raise ApplyError(f"商品ID {iid} がありません")
                    o = add_order(S, today, iid, q, f"承認 {pid}")
                    done.append(f"発注：{o['商品']} {qty_s(iid, q)}（{o['仕入先']}・{fmt(o['金額'])}円・入荷予定 {jp(d(o['入荷予定日']))}）")
            elif kind == "値下げ":
                for line in v:
                    days = int(line.get("日数", 7))
                    S["値下げ"].append({"商品ID": line["商品ID"], "率": float(line["率"]), "から": today.isoformat(),
                                      "まで": (today + dt.timedelta(days=days - 1)).isoformat()})
                    done.append(f"値下げ：{ITEM[line['商品ID']][1]} {int(float(line['率']) * 100)}%引き（{days}日）")
            elif kind == "広告":
                for k, val in v.items():
                    if k not in S["広告"]:
                        raise ApplyError(f"広告の項目 {k} がありません（{list(S['広告'])}）")
                    done.append(f"広告：{k} {S['広告'][k]} → {val}")
                    S["広告"][k] = int(val)
            elif kind == "督促":
                cid = v["取引先ID"]
                S["督促"][cid] = today.isoformat()
                done.append(f"督促：{CUST[cid][1]}（入金の見込みが上がる）")
            elif kind == "出荷停止":
                cid = v["取引先ID"]
                S["法人"][cid]["出荷"] = not v.get("止める", True)
                done.append(f"出荷：{CUST[cid][1]} を{'止める' if v.get('止める', True) else '再開する'}")
            elif kind == "法人":
                for cid, ch in v.items():
                    if "曜日" in ch:
                        S["法人"][cid]["曜日"] = [int(x) for x in ch["曜日"]]
                    if "1回の目安" in ch:
                        S["法人"][cid]["1回の目安"] = int(ch["1回の目安"])
                    done.append(f"法人：{CUST[cid][1]} の定期配達を {'・'.join(WD[x] for x in S['法人'][cid]['曜日'])}・1回 {fmt(S['法人'][cid]['1回の目安'])}円に")
            elif kind == "契約":
                for c in S["契約"]:
                    if v["相手"] in c["相手"]:
                        c["状態"] = f"{v.get('内容', '条件の見直しを申し出た')}（{today}・{pid}）"
                        done.append(f"契約：{c['相手']} → {c['状態']}")
            elif kind == "掲載":
                S["お知らせ"].append([today.isoformat(), v["題"], v.get("出した場所", "サイト・Instagram")])
                for e in S["行事"]:
                    if v.get("行事") and v["行事"] in e["名前"]:
                        e["告知"] = True
                done.append(f"掲載：{v['題']}（{v.get('出した場所', 'サイト・Instagram')}）")
            elif kind == "シフト":
                for k, val in v.items():
                    S["シフト"][k] = bool(val)
                    done.append(f"シフト：{k} → {'する' if val else 'しない'}")
            elif kind == "配達":
                for k, val in v.items():
                    S["配達"][k] = bool(val)
                    done.append(f"配達：{k} → {'する' if val else 'しない'}")
            elif kind == "在庫連動":
                S["在庫連動"] = bool(v)
                for iid, _ in EC_W:
                    S["サイト在庫"][iid] = S["在庫"].get(iid, 0)
                done.append("ネットの在庫：毎日、実際の在庫にそろえる")
            elif kind == "表示":
                for gid, val in v.items():
                    S["表示"][gid] = val
                    done.append(f"表示：{gid} の「20歳未満」の表示 → {val}")
            elif kind == "返信":
                path = paths.data / "marketing/口コミ.csv"
                rows = read_csv(path)
                n = 0
                for r in rows:
                    if r["返信"] == "未返信" and (v == "全部" or str(r["星"]) in [str(x) for x in (v if isinstance(v, list) else [v])]):
                        r["返信"] = "返信済み"
                        n += 1
                write_csv(path, ["日付", "どこの口コミ", "星", "本文", "返信"], [[r[k] for k in ("日付", "どこの口コミ", "星", "本文", "返信")] for r in rows])
                done.append(f"口コミ：{n}件に返信")
            elif kind == "ページ改善":
                S["ページ改善"] = bool(v)
                done.append("ネット：商品ページを直した（注文が少し増える）")
            else:
                done.append(f"（{kind} は数字の効果を入れていない。記録だけ）")
        if not act:
            done.append("（実行の欄がないので、記録だけ）")
        S["施策"].append({"承認ID": pid, "件名": fm.get("件名", ""), "日付": today.isoformat(), "内容": done})
        S["適用済み"].append(pid)
        refresh_derived(paths, S)
        save_state(paths, S)
    finally:
        lock(paths)
    if not quiet:
        print(f"{pid}「{fm.get('件名', '')}」を会社に入れました（{jp(today)}）")
        for x in done:
            print("  - " + x)
    return done


# ══ 予算の今日までの分 ════════════════════════════════════════
_PRIOR_CACHE = {}
BUDGET_COLS = {"店舗": ["店の合計"], "配達": ["配達の売上"], "EC": ["ECの売上"], "ギフト": [f"ギフト_{c}_売上" for c in CHANNELS]}


def _prior_rows(paths: Paths):
    key = (str(paths.prior), paths.prior.stat().st_mtime_ns if paths.prior.exists() else 0)
    if key not in _PRIOR_CACHE:
        _PRIOR_CACHE.clear()
        _PRIOR_CACHE[key] = {r["日付"]: r for r in read_csv(paths.prior)}
    return _PRIOR_CACHE[key]


def budget_parts(paths: Paths, day: dt.date):
    """その日の予算（事業ごと）。月の予算 × その日の重み ÷ その月の全部の日の重みの合計。
    重み＝去年の同じ曜日の日（364日前）の売上（店は日曜0）。法人は月の日数で割る。"""
    bud = {r["月"]: r for r in read_csv(paths.data / "accounting/予算.csv")}.get(ym(day))
    if not bud:
        return None
    m0 = day.replace(day=1)
    n = (month_last(day) - m0).days + 1
    days = [(m0 + dt.timedelta(days=i)).isoformat() for i in range(n)]
    pr = _prior_rows(paths)
    out = {}
    for k, cs in BUDGET_COLS.items():
        w = {x: sum(int(pr[x][c]) for c in cs) if x in pr else 0 for x in days}
        full = sum(w.values())
        out[k] = int(bud["売上_" + k]) * (w[day.isoformat()] / full if full else 1 / n)
    out["法人"] = int(bud["売上_法人"]) / n
    return out


def daily_budget(paths: Paths, day: dt.date):
    """その日の予算（全事業の合計）。"""
    p = budget_parts(paths, day)
    return sum(p.values()) if p else None


def budget_to_date(paths: Paths, today: dt.date):
    """今月の予算のうち昨日までの分（daily_budget を今月1日〜昨日で足したもの）。"""
    m0 = today.replace(day=1)
    if not budget_parts(paths, m0):
        return None
    out = {k: 0.0 for k in list(BUDGET_COLS) + ["法人"]}
    x = m0
    while x < today:
        for k, v in budget_parts(paths, x).items():
            out[k] += v
        x += dt.timedelta(days=1)
    out["合計"] = sum(out.values())
    return out


# ══ status ═════════════════════════════════════════════════
def status_text(paths: Paths, S=None) -> str:
    S = S or load_state(paths)
    D = paths.data
    today = d(S["今日"])
    j = read_csv(D / "accounting/日計表.csv")
    mk = ym(today)
    mtd = [r for r in j if r["日付"].startswith(mk)]
    sales = sum(int(r["売上合計"]) for r in mtd)
    bt = budget_to_date(paths, today)
    bline = f"（予算比 {sales / bt['合計'] * 100:.1f}%）" if bt and bt["合計"] else ""
    last = j[-1] if j else None
    outs = [ITEM[i][1] for i in STOCKED if S["在庫"].get(i, 0) <= 0]
    on_order = {o["商品ID"] for o in S["発注"] if o["状態"] == "未入荷"}
    low = [f"{ITEM[i][1]} 残り{qty_s(i, S['在庫'].get(i, 0))}" for i in STOCKED
           if 0 < S["在庫"].get(i, 0) < reorder_point(i) and i not in DAILY_FRESH and i not in on_order]
    pend = [o for o in S["発注"] if o["状態"] == "未入荷" and o["発注者"] != "定期（自動）"]
    over = [r for r in S["売掛金"] if not r["入金日"] and d(r["支払期日"]) < today]
    n_pend = len(list(paths.pending.glob("*.md"))) if paths.pending.exists() else 0
    pend_s = "・".join("{} {}（{}）".format(o["商品"], qty_s(o["商品ID"], o["数量"]), jp(d(o["入荷予定日"]))) for o in pend) or "なし"
    ev = next((e for e in S["行事"] if d(e["日付"]) >= today), None)
    lines = [f"■ やまだ商店（架空）の今：{jp(today)}の朝（データは昨日まで）",
             f"  現金：{fmt(S['現金'])}円",
             f"  今月の売上（{today.month}/1〜昨日）：{fmt(sales)}円{bline}",
             (f"  昨日：{fmt(last['売上合計'])}円（店 {fmt(last['売上_店舗'])}・配達 {fmt(last['売上_配達'])}・ネット {fmt(last['売上_EC'])}・"
              f"ギフト {fmt(last['売上_ギフト'])}・法人 {fmt(last['売上_法人'])}）" if last else "  昨日：データなし"),
             f"  欠品：{'・'.join(outs) if outs else 'なし'}",
             f"  発注点割れ：{'・'.join(low) if low else 'なし'}",
             f"  入荷待ち（手配・承認分）：{pend_s}",
             f"  期日を過ぎた売掛金：{'・'.join(sorted({r['取引先'] for r in over}))} 合計 {fmt(sum(r['請求額'] for r in over))}円" if over else "  期日を過ぎた売掛金：なし",
             f"  承認待ち：{n_pend}件（/承認待ち で見る）",
             f"  次の行事：{jp(d(ev['日付']))} {ev['名前']}" if ev else "  次の行事：なし"]
    return "\n".join(lines)


# ══ 歴史の材料（init でだけ使う） ═════════════════════════════════
def notice_items(today):
    items = []
    yy = today.year if today >= dt.date(today.year, 10, 20) else today.year - 1
    gstart = dt.date(yy, 10, 20) if yy >= 2026 else dt.date(yy, 11, 20)
    if gstart < today:
        items.append((gstart.isoformat(), "お歳暮の承りを始めました（早割は11月30日まで）", "サイト・Instagram・店頭のポスター"))
    items.append(((today - dt.timedelta(days=33)).isoformat(), "新米（県産）が入りました", "Instagram・店頭のポスター"))
    items.append(((today - dt.timedelta(days=46)).isoformat(), "雨の日の配達のご案内", "サイト・Instagram"))
    canon = [("2026-04-01", "還暦を迎えました（店主ブログ）", "サイト"), ("2026-03-10", "春の配達ダイヤのご案内", "サイト"),
             ("2026-01-05", "新年のご挨拶と本年の営業について", "サイト"), ("2025-11-20", "お歳暮の承りを始めました", "サイト・店頭のポスター")]
    items += [c for c in canon if c[0] < today.isoformat()]
    return sorted(items, reverse=True)


def sns_history(W, S):
    today = W["today"]
    rnd = random.Random(SEED + 2)
    this_mon = today - dt.timedelta(days=today.weekday())
    events = {n[0]: n[1] for n in S["お知らせ"]}
    filler = ["日替わり惣菜の紹介", "地酒の飲みくらべ", "店主のおすすめのおつまみ", "お弁当の新しいおかず"]
    rows, fol = [], 792
    for i in range(8, 0, -1):
        wk = this_mon - dt.timedelta(days=7 * i)
        hit = [t for x, t in events.items() if wk.isoformat() <= x < (wk + dt.timedelta(days=7)).isoformat()]
        if hit:
            post = hit[0].split("（早割")[0]
        elif wk + dt.timedelta(days=6) < W["stockout"] - dt.timedelta(days=6) and i % 3 == 0:
            post = "播磨ゴールド、冷えてます"
        elif any(x <= wk.isoformat() and "お歳暮" in t for x, t in events.items()) and wk > today - dt.timedelta(days=21):
            post = "お歳暮の早割（11月30日まで）"
        else:
            post = filler[i % 4]
        n = rnd.choice([2, 3, 3, 4])
        reach = int(n * rnd.uniform(260, 420) + (300 if wk >= W["insta_start"] else 0))
        fol += rnd.randint(4, 13)
        rows.append([wk.isoformat(), n, fol, reach, int(reach * rnd.uniform(0.07, 0.11)), int(reach * rnd.uniform(0.01, 0.025)),
                     int(reach * rnd.uniform(0.04, 0.07)), int(reach * rnd.uniform(0.02, 0.04)), post])
    return rows


def reviews(today):
    def ago(n):
        return (today - dt.timedelta(days=n)).isoformat()
    return [
        [ago(58), "Googleの口コミ", 5, "配達が早くて本当に助かってます。重い米も玄関まで。", "返信済み"],
        [ago(52), "Googleの口コミ", 4, "昔ながらのお店で、店主さんがいつも声をかけてくれる。", "返信済み"],
        [ago(47), "ネットショップ", 5, "地酒の飲みくらべセット、どれもおいしかったです。", "返信済み"],
        [ago(41), "Googleの口コミ", 5, "地酒の品ぞろえがいい。お歳暮にも使いました。", "返信済み"],
        [ago(35), "Googleの口コミ", 3, "夕方はレジが少し混みます。", "返信済み"],
        [ago(29), "Googleの口コミ", 4, "日替わりの惣菜がおいしい。", "返信済み"],
        [ago(24), "Googleの口コミ", 5, "電話一本で配達してくれるので、高齢の母が重宝しています。", "返信済み"],
        [ago(20), "Googleの口コミ", 2, "夕方6時ごろ、レジが1台しか開いていなくて10分近く待ちました。", "未返信"],
        [ago(16), "ネットショップ", 5, "のしの書き方まで丁寧に聞いてくれて安心しました。", "返信済み"],
        [ago(12), "Googleの口コミ", 3, "品ぞろえはいいけど、仕事帰りの時間はレジ待ちが長い。", "未返信"],
        [ago(9), "Googleの口コミ", 4, "新米がおいしかった。また配達をお願いします。", "未返信"],
        [ago(4), "Googleの口コミ", 2, "いつもの播磨ゴールドが売り切れ。週末に飲みたかったのに残念。", "未返信"],
        [ago(2), "Googleの口コミ", 3, "地ビール目当てで来たけど無かった。ほかは満足。", "未返信"],
        [ago(1), "Googleの口コミ", 5, "雨の日に配達をお願いしたら、すぐ来てくれました。", "未返信"],
    ]


def contracts(today):
    nxt_end = month_last(add_months(today.replace(day=1), 1))

    def mlast(n):
        return month_last(add_months(today.replace(day=1), n)).isoformat()
    start = (nxt_end + dt.timedelta(days=1)).replace(year=nxt_end.year + 1 - 3)
    rows = [
        ["介護施設 あおぞらの家（架空）", "取引基本契約（定期配達）", start.isoformat(), "1年", nxt_end.isoformat(), "あり",
         (nxt_end - dt.timedelta(days=30)).isoformat(), "山田 太郎",
         "週3回（月・水・金）の定期配達。値段と配達の回数は更新のときに見直せる。申し出がなければ同じ条件で1年延びる"],
        ["居酒屋 千鳥足（架空）", "取引基本契約（酒類・食材の卸）", "2019-04-01", "1年", mlast(5), "あり", "", "山田 太郎",
         "月末締め翌月末払い。支払いが2か月以上遅れたら出荷を止められる（第9条）"],
        ["焼き鳥 まめ吉（架空）", "取引基本契約（酒類・食材の卸）", "2017-10-01", "1年", mlast(4), "あり", "", "山田 太郎", ""],
        ["いろは食堂（架空）", "取引基本契約（食材の卸）", "2015-06-01", "1年", mlast(8), "あり", "", "山田 太郎", ""],
        ["喫茶 こもれび（架空）", "注文書での取引（基本契約なし）", "2021-09-01", "", "", "", "", "店長代理", "毎週の注文書だけ"],
        ["デイサービス のぞみ（架空）", "取引基本契約（定期配達）", "2022-04-01", "1年", mlast(9), "あり", "", "山田 太郎", ""],
        ["播磨麦酒（架空）", "特約店契約（地ビールの仕入れ）", "2018-04-01", "1年", mlast(6), "あり", "", "山田 太郎", "地域で決まった数の店だけが扱える"],
        ["ネットショップの仕組み（架空のサービス）", "サービス利用契約", "2019-06-01", "1か月", "毎月", "あり", "", "店長代理", "売上の5%前後の手数料"],
        ["△△リース（架空）", "レジ（POS）のリース", "2022-04-01", "5年", "2027-03-31", "なし", "2027-01-31", "専務", "終わったら買い取りか入れ替え"],
        ["△△リース（架空）", "配達の軽バン2台のリース", "2023-09-01", "5年", "2028-08-31", "なし", "", "専務", ""],
        ["△△損保（架空）", "店舗の火災保険・賠償責任保険", "2010-04-01", "1年", "2027-03-31", "あり", "", "専務", ""],
    ]
    keys = ("相手", "契約の種類", "始まった日", "期間", "次の更新日", "自動更新", "条件を変えたいときの申し出期限", "担当", "メモ")
    return [dict(zip(keys, r), 状態="そのまま") for r in rows]


def licenses():
    return [
        ["一般酒類小売業免許", "△△税務署 第0000号（架空）", "1965-04-01", "期限なし（更新は不要）", "山田 太郎", "店にお酒を売るための免許。店内に「酒類販売管理者標識」を出す"],
        ["通信販売酒類小売業免許", "△△税務署 第0000号（架空）", "2019-06-01", "期限なし（更新は不要）", "店長代理",
         "ネットでお酒を売るための免許。ネットで売れるのは地酒・地ビールなど条件に合うお酒だけ（大手のビールは売れない）"],
        ["酒類販売管理者（研修）", "―", "2025-02-14（前回の研修）", "2028-02-13（3年ごとに受け直し）", "店長代理", "お酒を売る店に必ず1人置く人"],
        ["飲食店営業許可（惣菜・お弁当）", "△△保健所 第0000号（架空）", "2021-04-01", "2027-03-31", "惣菜の担当（食品衛生責任者）", "期限の前に更新の申請がいる"],
        ["食品衛生責任者", "―", "2021-03-15", "―", "惣菜の担当（食品衛生責任者）", "惣菜・お弁当づくりの責任者"],
        ["個人情報の扱い", "―", "―", "―", "専務", "配達のお客様の名前・住所・電話は、配達の台帳（紙とレジの中）だけ。外に出さない・レポートにも書かない"],
    ]


# ══ 入口 ══════════════════════════════════════════════════
def main(argv=None):
    ap = argparse.ArgumentParser(description="やまだ商店（架空）の経営シミュレーション")
    ap.add_argument("--root", help="リポの場所（既定はこのリポ）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init", help="はじめの状態に戻す")
    p.add_argument("--date", default=DEFAULT_START.isoformat(), help="「今日」YYYY-MM-DD（既定 2026-11-10）")
    p.add_argument("--clean", action="store_true", help="承認の箱（pending/approved/rejected）と意思決定ログも空にする（撮り直し用）")
    p = sub.add_parser("advance", help="会社を進める")
    p.add_argument("--days", type=int, default=1)
    p = sub.add_parser("apply", help="承認された提案の効果を入れる")
    p.add_argument("id")
    sub.add_parser("status", help="今の会社を10行で")
    a = ap.parse_args(argv)
    paths = Paths(a.root)
    try:
        if a.cmd == "init":
            if a.clean:
                print(f"承認の箱と意思決定ログを空にしました（{clean_approvals(paths)}件）")
            cmd_init(paths, d(a.date))
        elif a.cmd == "advance":
            if a.days < 1 or a.days > 120:
                raise SystemExit("--days は 1〜120")
            cmd_advance(paths, a.days)
        elif a.cmd == "apply":
            cmd_apply(paths, a.id)
        elif a.cmd == "status":
            print(status_text(paths))
    except ApplyError as e:
        print(f"できません：{e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
