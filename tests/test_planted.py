"""はじめの日（2026-11-10）に、各部の「気づいてほしい話」が入っているか。"""
import datetime as dt

from common import load_state
from helpers import fresh, rows


def test_harima_gold_stockout_and_alcohol_drop():
    p = fresh()
    S = load_state(p)
    assert S["今日"] == "2026-11-10"
    assert S["在庫"]["S01"] == 0
    items = rows(p, "store/POS_商品別_直近14日.csv")
    after = [int(r["数量"]) for r in items if r["商品ID"] == "S01" and r["日付"] >= "2026-11-05"]
    assert after and sum(after) == 0
    pos = [r for r in rows(p, "store/POS_日別.csv") if not r["備考"]]
    a = [int(r["酒類"]) for r in pos if r["日付"] >= "2026-11-05"]
    b = [int(r["酒類"]) for r in pos if "2026-10-08" <= r["日付"] < "2026-11-05"]
    assert sum(a) / len(a) <= 0.8 * sum(b) / len(b)


def test_tissue_below_reorder_point():
    S = load_state(fresh())
    assert S["在庫"]["D01"] == 9


def test_overdue_receivable_over_30_days():
    p = fresh()
    over = [r for r in rows(p, "accounting/売掛金.csv") if r["期日から何日過ぎたか"] and int(r["期日から何日過ぎたか"]) > 30]
    assert over and over[0]["取引先ID"] == "C01"


def test_festival_saturday_and_rain_tomorrow():
    S = load_state(fresh())
    ev = S["行事"][0]
    assert ev["日付"] == "2026-11-14" and "秋祭り" in ev["名前"] and ev["屋台"] and not ev["告知"]
    assert S["天気の上書き"]["2026-11-11"] == "雨"


def test_contract_deadline_soon_and_notice_missing():
    p = fresh()
    c = next(r for r in rows(p, "legal/契約.csv") if "あおぞら" in r["相手"])
    left = (dt.date.fromisoformat(c["条件を変えたいときの申し出期限"]) - dt.date(2026, 11, 10)).days
    assert 0 < left <= 31
    notes = (p.data / "pr/お知らせ.md").read_text(encoding="utf-8")
    assert "秋祭り" not in notes and "祭" not in notes


def test_flyer_worse_than_instagram():
    p = fresh()
    ads = rows(p, "marketing/広告.csv")
    last = ads[-1]["月"]
    r = {a["媒体"]: a for a in ads if a["月"] == last}
    assert float(r["新聞折込チラシ"]["売上÷費用"]) < 3 < float(r["Instagram広告"]["売上÷費用"])


def test_ec_site_stock_mismatch_and_label():
    p = fresh()
    pages = {r["商品ID"]: r for r in rows(p, "ec/商品ページ.csv")}
    assert pages["S01"]["サイトに出ている在庫"] == "12" and pages["S01"]["実際の在庫（今朝）"] == "0"
    assert int(pages["S01"]["まだ出荷していない注文（件）"]) > 0
    assert pages["G02"]["「20歳未満の飲酒は法律で禁止」の表示"] == "×"


def test_reviews_unanswered():
    p = fresh()
    low = [r for r in rows(p, "marketing/口コミ.csv") if r["返信"] == "未返信" and int(r["星"]) <= 3]
    assert len(low) >= 4
