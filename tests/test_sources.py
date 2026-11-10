"""データの出どころ（_sources.json）とダッシュボードのデータ（dashboard_data.json）。"""
import io
import json
import re
from contextlib import redirect_stdout

import dashboard
import q as qmod
from helpers import REPO, fresh, rows

KEYS = {"id", "name", "category", "what", "how", "freq", "files", "agents", "simulated"}


def test_sources_json_valid_and_covers_data():
    p = fresh()
    data = json.loads((p.data / "_sources.json").read_text(encoding="utf-8"))
    src = data["sources"]
    ids = [s["id"] for s in src]
    assert len(ids) == len(set(ids)) >= 20
    for s in src:
        assert KEYS <= set(s) and s["simulated"] is True
        assert s["how"] in ("API", "CSV書き出し", "手入力", "PDF読み取り") and s["freq"] in ("毎晩", "毎朝", "毎週", "月次")
        for f in s["files"]:
            assert (p.root / f).exists(), f
    fed = {f for s in src for f in s["files"]}
    for f in p.data.rglob("*"):
        if f.is_file() and f.name not in ("README.md", "_sources.json"):
            assert f"data/{f.relative_to(p.data)}" in fed, f
    doc = (REPO / "company/データマップ.md").read_text(encoding="utf-8")
    assert all(f"`{i}`" in doc for i in ids) and "シミュレーション" in doc


def _dash(p):
    dashboard.main(["--root", str(p.root)])
    return json.loads((p.reports / "dashboard_data.json").read_text(encoding="utf-8"))


def test_dashboard_data_shape_and_sources():
    p = fresh()
    d = _dash(p)
    for k in ("company", "today", "as_of", "kpis", "by_business", "by_channel", "series", "alerts", "sources", "agents"):
        assert k in d
    ids = {s["id"] for s in d["sources"]}
    assert 6 <= len(d["kpis"]) <= 8
    for k in d["kpis"]:
        assert {"id", "label", "value", "unit", "how", "files", "sources"} <= set(k)
        assert set(k["sources"]) <= ids, k["id"]
    for b in d["by_business"]:
        assert set(b["sources"]) <= ids
    assert {c["source"] for c in d["by_channel"]} <= ids and len(d["by_channel"]) == 3
    assert len(d["series"]["酒類_日別"]) >= 40 and len(d["series"]["売上_日別"]) == len(d["series"]["予算_日別"]) == 56
    assert d["alerts"]["stockouts"][0]["商品ID"] == "S01" and d["alerts"]["overdue"]
    assert len(d["agents"]) == 12


def test_dashboard_numbers_match_q_and_data():
    p = fresh()
    d = _dash(p)
    k = {x["id"]: x for x in d["kpis"]}
    j = rows(p, "accounting/日計表.csv")
    assert k["sales_yesterday"]["value"] == int(j[-1]["売上合計"])
    out = io.StringIO()
    with redirect_stdout(out):
        qmod.main(["--root", str(p.root), "全体"])
    text = out.getvalue()
    table = dict(re.findall(r"^\| (店舗|配達|EC|ギフト|法人|合計) \| ([\d,]+) \| [\d,]+ \| [\d.]+% \|$", text, re.M))
    for b in d["by_business"]:
        assert int(table[b["name"]].replace(",", "")) == b["value"], b["name"]
    assert int(table["合計"].replace(",", "")) == k["sales_mtd"]["value"]
    ch = rows(p, "ec/チャネル別_日別.csv")
    mt = [r for r in ch if r["日付"].startswith(d["today"][:7])]
    assert sum(c["value"] for c in d["by_channel"]) == sum(int(r["売上"]) for r in mt)
    ec = sum(int(r["売上_EC"]) for r in j if r["日付"].startswith(d["today"][:7]))
    net_gift = sum(int(r["売上"]) for r in rows(p, "gift/ギフト受注_日別.csv") if r["受付"] == "ネット" and r["日付"].startswith(d["today"][:7]))
    assert sum(c["value"] for c in d["by_channel"]) == ec + net_gift


def test_channel_fees_in_pl():
    p = fresh()
    ch = rows(p, "ec/チャネル別_日別.csv")
    pl = rows(p, "accounting/月次PL.csv")[-1]
    pos = sum(int(r["合計"]) for r in rows(p, "store/POS_日別.csv") if r["日付"].startswith(pl["月"]))
    fee = sum(int(r["手数料"]) for r in ch if r["日付"].startswith(pl["月"]))
    assert int(pl["支払手数料"]) == int(round(pos * 0.006 + fee, -2))


def test_template_injection():
    p = fresh()
    (p.root / "tools").mkdir(exist_ok=True)
    (p.root / "tools/dashboard_template.html").write_text("<html><body><!--DASH_DATA--><div id=app></div></body></html>", encoding="utf-8")
    dashboard.main(["--root", str(p.root)])
    html = (p.reports / "dashboard.html").read_text(encoding="utf-8")
    assert "<!--DASH_DATA-->" not in html and "window.DASH = {" in html and "株式会社やまだ商店（架空）" in html


def test_daily_budget_spreads_whole_month():
    """予算_日別：月の予算を、その月の全部の日（去年の同じ曜日の売れ方）に割り振る。"""
    import calendar
    import csv
    import datetime as dt

    import sim
    p = fresh()
    d = _dash(p)
    with open(p.prior, encoding="utf-8") as f:
        next(f)
        pr = {r["日付"]: r for r in csv.DictReader(f)}
    bud = {r["月"]: r for r in rows(p, "accounting/予算.csv")}
    cols = {"店舗": ["店の合計"], "配達": ["配達の売上"], "EC": ["ECの売上"],
            "ギフト": [f"ギフト_{c}_売上" for c in ("店頭", "電話", "ネット", "法人")]}
    by_month = {}
    for x in d["series"]["予算_日別"]:
        by_month.setdefault(x["d"][:7], []).append(x)
    checked_full = checked_part = 0
    for m, pts in by_month.items():
        y, mo = map(int, m.split("-"))
        n = calendar.monthrange(y, mo)[1]
        all_days = [f"{m}-{i:02d}" for i in range(1, n + 1)]
        got = {x["d"] for x in pts}
        exp = int(bud[m]["売上_法人"]) * len(got) / n
        for k, cs in cols.items():
            w = {x: sum(int(pr[x][c]) for c in cs) for x in all_days}
            assert all(x in pr for x in all_days), m
            tot = sum(w.values())
            exp += int(bud[m]["売上_" + k]) * (sum(w[x] for x in got) / tot if tot else len(got) / n)
        total = sum(x["v"] for x in pts)
        assert abs(total - exp) <= exp * 0.01, (m, total, exp)
        if len(got) == n:
            assert abs(total - int(bud[m]["売上合計"])) <= int(bud[m]["売上合計"]) * 0.01, m
            checked_full += 1
        elif min(got) > f"{m}-01":
            assert total < int(bud[m]["売上合計"]) * 0.75, (m, total)        # 9/15〜30 は月の予算の一部だけ
            checked_part += 1
    assert checked_full >= 1 and checked_part == 1
    nov = [dt.date(2026, 11, i) for i in range(1, 31)]
    assert abs(sum(sim.daily_budget(p, x) for x in nov) - int(bud["2026-11"]["売上合計"])) <= int(bud["2026-11"]["売上合計"]) * 0.01
    bt = sim.budget_to_date(p, dt.date(2026, 11, 10))
    assert abs(bt["合計"] - sum(sim.daily_budget(p, x) for x in nov[:9])) < 1
    k = {x["id"]: x for x in d["kpis"]}
    assert k["sales_mtd"]["budget"] == round(bt["合計"])
