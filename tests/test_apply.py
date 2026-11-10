"""承認：承認していないものは入らない・播磨ゴールドの発注で欠品が直る。"""
import approvals
import sim
from common import load_state
from helpers import fresh, rows, write_proposal


def _raises(fn):
    try:
        fn()
    except sim.ApplyError:
        return True
    return False


def test_apply_refuses_unknown_and_pending():
    p = fresh()
    assert _raises(lambda: sim.cmd_apply(p, "20261110-999", quiet=True))
    write_proposal(p, "20261110-251")
    assert _raises(lambda: sim.cmd_apply(p, "20261110-251", quiet=True))


def test_apply_refuses_file_moved_without_decision():
    p = fresh()
    write_proposal(p, "20261110-252", folder="approved")    # 承認の記録（## 決定）がない
    assert _raises(lambda: sim.cmd_apply(p, "20261110-252", quiet=True))


def test_approve_resolves_stockout():
    p = fresh()
    write_proposal(p, "20261110-251")
    assert approvals.cmd_approve(p, "20261110-251", "山田太郎") == 0
    assert _raises(lambda: sim.cmd_apply(p, "20261110-251", quiet=True))      # 二重には入らない
    S = load_state(p)
    o = [x for x in S["発注"] if x["発注者"] == "承認 20261110-251"]
    assert {x["商品ID"] for x in o} == {"S01", "S12"} and o[0]["入荷予定日"] == "2026-11-13"
    sim.cmd_advance(p, 4, quiet=True)                                       # 11/10〜11/13
    items = {(r["日付"], r["商品ID"]): int(r["数量"] or 0) for r in rows(p, "store/POS_商品別_直近14日.csv")}
    assert items[("2026-11-12", "S01")] == 0 and items[("2026-11-13", "S01")] > 0
    pos = {r["日付"]: int(r["酒類"]) for r in rows(p, "store/POS_日別.csv")}
    before = sum(pos[x] for x in ("2026-11-10", "2026-11-11", "2026-11-12")) / 3
    assert pos["2026-11-13"] > before * 1.3
    assert load_state(p)["在庫"]["S01"] > 0
    log = (p.logs / "意思決定ログ.md").read_text(encoding="utf-8")
    assert "20261110-251" in log and "承認" in log


def test_reject_moves_and_logs():
    p = fresh()
    write_proposal(p, "20261110-253")
    assert approvals.cmd_reject(p, "20261110-253", "今週は様子を見る", "山田太郎") == 0
    assert list(p.rejected.glob("20261110-253_*.md"))
    assert "今週は様子を見る" in (p.logs / "意思決定ログ.md").read_text(encoding="utf-8")


def test_only_planted_items_run_out_after_demo():
    """init → 251 だけ承認 → 5日進める：欠品は1〜2品まで、しかも承認がいる品（ティッシュ）だけ。"""
    from sim_model import DAILY_FRESH, ITEM, is_manual, reorder_point
    p = fresh()
    write_proposal(p, "20261110-251")
    assert approvals.cmd_approve(p, "20261110-251", "山田太郎") == 0
    sim.cmd_advance(p, 5, quiet=True)                                     # 11/10〜11/14 → 11/15 の朝
    S = load_state(p)
    assert S["今日"] == "2026-11-15"
    stocked = [i for i in ITEM if ITEM[i][8] != "店内調理"]
    outs = {i for i in stocked if S["在庫"].get(i, 0) <= 0}
    pending = {o["商品ID"] for o in S["発注"] if o["状態"] == "未入荷"}
    low = {i for i in stocked if i not in DAILY_FRESH and 0 < S["在庫"][i] < reorder_point(i) and i not in pending}
    assert len(outs) <= 2 and outs <= {"D01"}, outs                       # 播磨ゴールドは戻り、ティッシュだけ（手配の承認を待つ品）
    assert all(is_manual(i) for i in outs | low), (outs, low)
    assert S["在庫"]["S01"] > 0
    pos = {r["日付"]: int(r["酒類"]) for r in rows(p, "store/POS_日別.csv")}
    assert pos["2026-11-14"] > 2.5 * pos["2026-11-12"]                    # 祭りの土曜は酒類が大きく伸びる


def test_units_in_outputs():
    """数の読み違いを防ぐ：名前に「6缶」があっても、数には必ず単位（パック）がつく。"""
    from sim_model import ITEM, qty_s
    p = fresh()
    write_proposal(p, "20261110-251")
    approvals.cmd_approve(p, "20261110-251", "山田太郎")
    _, digests = sim.cmd_advance(p, 3, quiet=True)
    assert ITEM["S01"][1] == "播磨ゴールド（350ml×6缶パック）" and qty_s("S01", 80) == "80パック"
    inv = {r["商品ID"]: r for r in rows(p, "purchasing/在庫.csv")}
    assert inv["S01"]["単位"] == "パック" and 50 < int(inv["S01"]["在庫（今朝）"]) <= 80   # 80パック入荷・待っていたネットの注文を先に出す
    hist = [r for r in rows(p, "purchasing/発注履歴.csv") if r["商品ID"] == "S01" and r["発注日"] == "2026-11-10"]
    assert hist and hist[0]["単位"] == "パック"
