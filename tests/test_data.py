"""データの数字がそろっているか（はじめの日）。"""
from helpers import fresh, rows


def test_pos_month_equals_pl_store():
    p = fresh()
    pos = rows(p, "store/POS_日別.csv")
    pl = {r["月"]: r for r in rows(p, "accounting/月次PL.csv")}
    checked = 0
    for m, r in pl.items():
        days = [x for x in pos if x["日付"].startswith(m)]
        if len({x["日付"] for x in days}) >= 28 and days[0]["日付"].endswith("-01"):
            assert sum(int(x["合計"]) for x in days) == int(r["売上_店舗"]), m
            checked += 1
    assert checked >= 1


def test_journal_equals_pl_by_business():
    p = fresh()
    j = rows(p, "accounting/日計表.csv")
    for r in rows(p, "accounting/月次PL.csv"):
        days = [x for x in j if x["日付"].startswith(r["月"])]
        if not days or not days[0]["日付"].endswith("-01"):
            continue
        for b in ("店舗", "配達", "EC", "法人", "ギフト"):
            assert sum(int(x["売上_" + b]) for x in days) == int(r["売上_" + b]), (r["月"], b)


def test_b2b_daily_equals_monthly_and_pl():
    p = fresh()
    daily = rows(p, "b2b/納品_日別.csv")
    mon = rows(p, "b2b/法人売上_月別.csv")
    pl = {r["月"]: r for r in rows(p, "accounting/月次PL.csv")}
    for m in {r["月"] for r in mon}:
        assert sum(int(r["売上"]) for r in mon if r["月"] == m) == int(pl[m]["売上_法人"])
    last = mon[-1]["月"]
    assert sum(int(r["金額"]) for r in daily if r["日付"].startswith(last)) == int(pl[last]["売上_法人"])


def test_ads_equal_pl():
    p = fresh()
    pl = {r["月"]: r for r in rows(p, "accounting/月次PL.csv")}
    ads = rows(p, "marketing/広告.csv")
    for m in {a["月"] for a in ads}:
        assert sum(int(a["費用"]) for a in ads if a["月"] == m) == int(pl[m]["広告宣伝費"])


def test_cash_chain():
    p = fresh()
    j = rows(p, "accounting/日計表.csv")
    for a, b in zip(j, j[1:]):
        assert int(a["現金残高"]) + int(b["入金"]) - int(b["出金"]) == int(b["現金残高"]), b["日付"]
