"""一日進める：同じなら同じ結果・在庫はマイナスにならない・お金の足し算が合う・月末を締める。"""
import sim
from common import load_state
from helpers import digest, fresh, rows


def test_advance_is_deterministic():
    a, b = fresh(), fresh()
    sim.cmd_advance(a, 3, quiet=True)
    sim.cmd_advance(b, 3, quiet=True)
    assert digest(a) == digest(b)


def test_stock_never_negative_and_cash_consistent():
    p = fresh()
    sim.cmd_advance(p, 10, quiet=True)
    S = load_state(p)
    assert all(v >= 0 for v in S["在庫"].values())
    j = rows(p, "accounting/日計表.csv")
    for x, y in zip(j, j[1:]):
        assert int(x["現金残高"]) + int(y["入金"]) - int(y["出金"]) == int(y["現金残高"]), y["日付"]
    assert int(j[-1]["現金残高"]) == S["現金"]


def test_month_close():
    p = fresh()
    sim.cmd_advance(p, 25, quiet=True)            # 11/10 → 12/5
    pl = {r["月"]: r for r in rows(p, "accounting/月次PL.csv")}
    assert "2026-11" in pl
    nov = sum(int(r["合計"]) for r in rows(p, "store/POS_日別.csv") if r["日付"].startswith("2026-11"))
    assert nov == int(pl["2026-11"]["売上_店舗"])
    j = [r for r in rows(p, "accounting/日計表.csv") if r["日付"].startswith("2026-11")]
    for b in ("店舗", "配達", "EC", "法人", "ギフト"):
        assert sum(int(r["売上_" + b]) for r in j) == int(pl["2026-11"]["売上_" + b])
    assert any(r["請求の月"] == "2026-11" for r in rows(p, "accounting/売掛金.csv"))
    assert int(pl["2026-11"]["前年同月の売上合計"]) > 0
