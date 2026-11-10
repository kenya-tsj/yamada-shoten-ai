"""やまだ商店（架空）のモデル：商品・取引先・季節の決まりと、過去2年分の歴史を作る部分。

ここの数字（売れ方・季節・天気の確率）は sim.py の「一日進める」でも同じものを使う。決まりの説明は sim/ルール.md。
"""
from __future__ import annotations

import datetime as dt
import math
import random

from common import add_months, is_open, month_last, yen
from sources import EC_CHANNELS, GIFT_CHANNELS

SEED = 20261109
DEFAULT_START = dt.date(2026, 11, 10)

# ID, 商品, 部門, 分類, 単価, 原価, 1日の平均の数（平日・店頭）, 発注点, 仕入先, 納期（日）, EC掲載
ITEMS = [
    ("S01", "播磨ゴールド（350ml×6缶パック）", "酒類", "ビール", 1580, 1150, 6.5, 20, "播磨麦酒（架空）", 3, True),
    ("S02", "缶ビール・大手（350ml×6缶パック）", "酒類", "ビール", 1280, 1040, 4.0, 15, "△△酒販（架空）", 2, False),
    ("S03", "発泡酒（350ml×6缶パック）", "酒類", "ビール", 880, 720, 1.5, 8, "△△酒販（架空）", 2, False),
    ("S04", "缶チューハイ（350ml缶）", "酒類", "チューハイ", 160, 120, 16.0, 60, "△△酒販（架空）", 2, False),
    ("S05", "ハイボール（350ml缶）", "酒類", "チューハイ", 180, 135, 4.0, 24, "△△酒販（架空）", 2, False),
    ("S06", "地酒・純米（720ml瓶）", "酒類", "日本酒", 1650, 1180, 1.8, 8, "□□酒造（架空）", 4, True),
    ("S07", "地酒・本醸造（1.8L瓶）", "酒類", "日本酒", 2480, 1800, 0.4, 3, "□□酒造（架空）", 4, True),
    ("S08", "芋焼酎（900ml瓶）", "酒類", "焼酎", 1180, 870, 0.8, 4, "△△酒販（架空）", 2, False),
    ("S09", "赤ワイン（720ml瓶）", "酒類", "ワイン", 680, 470, 1.0, 6, "△△酒販（架空）", 2, False),
    ("S10", "梅酒・地元の梅（720ml瓶）", "酒類", "梅酒", 1280, 880, 0.3, 3, "□□酒造（架空）", 4, True),
    ("S11", "地酒の飲みくらべ（3本入りセット）", "酒類", "日本酒", 4800, 3300, 0.05, 3, "□□酒造（架空）", 4, True),
    ("S12", "地ビールの飲みくらべ（6本入りセット）", "酒類", "ビール", 3600, 2500, 0.05, 3, "播磨麦酒（架空）", 3, True),
    ("S13", "ノンアルコールビール（350ml×6缶パック）", "酒類", "ノンアル", 980, 790, 0.6, 4, "△△酒販（架空）", 2, False),
    ("F01", "県産米（5kg袋）", "食料品", "米", 2380, 1850, 4.2, 12, "◯◯米穀（架空）", 2, False),
    ("F02", "食パン（6枚切りの1袋）", "食料品", "パン", 230, 160, 14.0, 10, "地元のパン屋（架空）", 1, False),
    ("F03", "牛乳（1Lパック）", "食料品", "日配", 248, 190, 22.0, 25, "◯◯乳業（架空）", 1, False),
    ("F04", "卵（10個入りパック）", "食料品", "日配", 298, 220, 16.0, 20, "◯◯養鶏（架空）", 1, False),
    ("F05", "惣菜（日替わり）", "食料品", "店内調理", 398, 160, 20.0, 0, "店内調理", 0, False),
    ("F06", "お弁当（日替わり）", "食料品", "店内調理", 498, 230, 9.0, 0, "店内調理", 0, False),
    ("F07", "おにぎり（2個入り）", "食料品", "店内調理", 238, 110, 10.0, 0, "店内調理", 0, False),
    ("F08", "豆腐", "食料品", "日配", 98, 68, 15.0, 15, "△△食品卸（架空）", 1, False),
    ("F09", "納豆（3個組）", "食料品", "日配", 98, 70, 12.0, 15, "△△食品卸（架空）", 1, False),
    ("F10", "野菜（地元産・日替わりの袋）", "食料品", "青果", 198, 130, 10.0, 8, "△△青果（架空）", 1, False),
    ("F11", "バナナ", "食料品", "青果", 198, 140, 8.0, 10, "△△青果（架空）", 1, False),
    ("F12", "鶏むね肉（300gパック）", "食料品", "精肉", 380, 270, 6.0, 8, "△△食品卸（架空）", 1, False),
    ("F13", "豚こま切れ（200gパック）", "食料品", "精肉", 398, 290, 6.0, 8, "△△食品卸（架空）", 1, False),
    ("F14", "塩さば（2切れパック）", "食料品", "鮮魚", 298, 200, 4.0, 6, "△△食品卸（架空）", 1, False),
    ("F15", "カップ麺", "食料品", "加工食品", 168, 120, 7.0, 24, "△△食品卸（架空）", 2, False),
    ("F16", "冷凍うどん（5食入り袋）", "食料品", "冷凍", 398, 290, 3.0, 6, "△△食品卸（架空）", 2, False),
    ("F17", "しょうゆ（1Lボトル）", "食料品", "調味料", 298, 210, 3.0, 6, "△△食品卸（架空）", 2, False),
    ("F18", "みそ（750gパック）", "食料品", "調味料", 398, 280, 2.0, 4, "△△食品卸（架空）", 2, False),
    ("F19", "お茶（2Lペットボトル）", "食料品", "飲料", 148, 95, 12.0, 24, "△△飲料（架空）", 2, False),
    ("F20", "缶コーヒー（185g缶）", "食料品", "飲料", 120, 75, 10.0, 24, "△△飲料（架空）", 2, False),
    ("F21", "ラムネ・ジュース（瓶）", "食料品", "飲料", 150, 95, 4.0, 24, "△△飲料（架空）", 2, False),
    ("F22", "アイス", "食料品", "冷凍", 128, 85, 6.0, 20, "△△食品卸（架空）", 2, False),
    ("F23", "お菓子（袋）", "食料品", "菓子", 198, 140, 8.0, 20, "△△食品卸（架空）", 2, False),
    ("F24", "地元の漬物", "食料品", "加工食品", 380, 250, 3.0, 5, "△△食品卸（架空）", 2, True),
    ("F25", "サラダ油（1000gボトル）", "食料品", "調味料", 398, 300, 2.0, 4, "△△食品卸（架空）", 2, False),
    ("D01", "ティッシュ（5箱パック）", "日用品", "紙製品", 398, 280, 5.0, 12, "◯◯日用品卸（架空）", 3, False),
    ("D02", "トイレットペーパー（12ロール入り）", "日用品", "紙製品", 548, 390, 4.0, 8, "◯◯日用品卸（架空）", 3, False),
    ("D03", "洗濯洗剤（詰め替え）", "日用品", "洗剤", 328, 230, 3.5, 8, "◯◯日用品卸（架空）", 3, False),
    ("D04", "食器用洗剤", "日用品", "洗剤", 198, 130, 3.0, 6, "◯◯日用品卸（架空）", 3, False),
    ("D05", "シャンプー（詰め替え）", "日用品", "生活雑貨", 398, 270, 1.5, 4, "◯◯日用品卸（架空）", 3, False),
    ("D06", "歯みがき粉", "日用品", "生活雑貨", 248, 165, 2.0, 5, "◯◯日用品卸（架空）", 3, False),
    ("D07", "ゴミ袋 45L（10枚入り）", "日用品", "生活雑貨", 298, 190, 3.0, 8, "◯◯日用品卸（架空）", 3, False),
    ("D08", "キッチンペーパー", "日用品", "紙製品", 248, 170, 2.5, 6, "◯◯日用品卸（架空）", 3, False),
    ("D09", "ラップ", "日用品", "生活雑貨", 248, 175, 2.0, 5, "◯◯日用品卸（架空）", 3, False),
    ("D10", "単3乾電池（4本パック）", "日用品", "生活雑貨", 398, 260, 1.0, 4, "◯◯日用品卸（架空）", 3, False),
    ("D11", "マスク（30枚入り箱）", "日用品", "生活雑貨", 498, 320, 1.0, 4, "◯◯日用品卸（架空）", 3, False),
    ("D12", "大人用おむつ（パンツ型）", "日用品", "介護用品", 1280, 900, 0.8, 4, "◯◯日用品卸（架空）", 3, False),
]
ITEM = {it[0]: it for it in ITEMS}
# 数える単位（発注・在庫・入荷の数はこの単位）。名前の中の「6缶」「5箱」は1つの中身で、数ではない
UNIT = {"S01": "パック", "S02": "パック", "S03": "パック", "S04": "本", "S05": "本", "S06": "本", "S07": "本", "S08": "本",
        "S09": "本", "S10": "本", "S11": "セット", "S12": "セット", "S13": "パック",
        "F01": "袋", "F02": "袋", "F03": "本", "F04": "パック", "F05": "パック", "F06": "個", "F07": "パック", "F08": "丁",
        "F09": "パック", "F10": "袋", "F11": "房", "F12": "パック", "F13": "パック", "F14": "パック", "F15": "個", "F16": "袋",
        "F17": "本", "F18": "個", "F19": "本", "F20": "本", "F21": "本", "F22": "個", "F23": "袋", "F24": "袋", "F25": "本",
        "D01": "パック", "D02": "パック", "D03": "袋", "D04": "本", "D05": "袋", "D06": "本", "D07": "パック", "D08": "パック",
        "D09": "本", "D10": "パック", "D11": "箱", "D12": "パック", "G01": "件", "G02": "件", "G03": "件"}
STALL = {"S01": 25, "F21": 40, "S06": 6}          # 祭りの屋台で売れる数（その日の店の分に足す）
OTHER = {"酒類": ("S99", "その他の酒類", 1500, 0.76),
         "食料品": ("F99", "その他の食料品", 5700, 0.74),
         "日用品": ("D99", "その他の日用品", 10000, 0.70)}
GIFTS = [
    ("G01", "ギフト：地酒の飲みくらべ（3本入り・のし・全国発送）", 4800, 3400),
    ("G02", "ギフト：地ビール（12本入り・のし・全国発送）", 5400, 3900),
    ("G03", "ギフト：地酒と漬物のセット（のし・全国発送）", 3800, 2700),
]
GIFT = {g[0]: g for g in GIFTS}
G02_START = dt.date(2026, 10, 20)
GIFT_W = {"G01": 0.5, "G02": 0.3, "G03": 0.2}

SUPPLIERS = [
    ("播磨麦酒（架空）", "播磨ゴールド・地ビールのセット", "3営業日（土日は配送なし）", "平日15時まで", "電話・FAX", "4ケース（24パック）から", "月末締め翌月末払い", "承認がいる（特約店・数が限られる）"),
    ("△△酒販（架空）", "大手のビール・チューハイ・焼酎・ワイン", "2日", "前日16時まで", "電話・ネット", "1ケースから", "月末締め翌月末払い", "定期（発注点で自動）"),
    ("□□酒造（架空）", "地酒・梅酒・飲みくらべセット", "4日", "平日12時まで", "電話", "6本から", "月末締め翌月末払い", "定期（発注点で自動）"),
    ("◯◯米穀（架空）", "米", "2日", "前日17時まで", "電話", "10袋から", "月末締め翌月末払い", "定期（発注点で自動）"),
    ("地元のパン屋（架空）", "食パン", "1日（毎朝）", "前日18時まで", "電話", "なし", "月末締め翌月末払い", "毎日の定期発注"),
    ("◯◯乳業（架空）", "牛乳", "1日（毎朝）", "前日18時まで", "FAX", "なし", "月末締め翌月末払い", "毎日の定期発注"),
    ("◯◯養鶏（架空）", "卵", "1日（毎朝）", "前日18時まで", "電話", "なし", "月末締め翌月末払い", "毎日の定期発注"),
    ("△△食品卸（架空）", "豆腐・納豆・肉・魚・加工食品・お菓子", "1〜2日", "前日17時まで", "ネット", "5,000円から", "月末締め翌月末払い", "日配は毎日・ほかは定期（発注点で自動）"),
    ("△△青果（架空）", "野菜・果物", "1日（毎朝）", "前日18時まで", "電話", "なし", "月末締め翌月末払い", "毎日の定期発注"),
    ("△△飲料（架空）", "お茶・コーヒー・ラムネ", "2日", "前日16時まで", "ネット", "3ケースから", "月末締め翌月末払い", "定期（発注点で自動）"),
    ("◯◯日用品卸（架空）", "日用品（紙・洗剤・生活雑貨・介護用品）", "3日", "前日17時まで", "ネット", "10,000円から", "月末締め翌月末払い", "承認がいる（週1回まとめて手配）"),
    ("◯◯包装（架空）", "ギフトの箱・のし紙・送り状", "5日", "随時", "ネット", "なし", "月末締め翌月末払い", "承認がいる"),
]
MANUAL_SUPPLIERS = ["播磨麦酒（架空）", "◯◯日用品卸（架空）", "◯◯包装（架空）"]
DAILY_FRESH = {"F02", "F03", "F04", "F08", "F09", "F10", "F11", "F12", "F13", "F14"}
COOKED = {"F05", "F06", "F07"}

CUSTOMERS = [
    ("C01", "居酒屋 千鳥足（架空）", "飲食店（居酒屋）", "酒類・食材", (1, 4), 128000, "2019-04"),
    ("C02", "焼き鳥 まめ吉（架空）", "飲食店（焼き鳥）", "酒類・鶏肉・調味料", (0, 3), 98000, "2017-10"),
    ("C03", "いろは食堂（架空）", "飲食店（定食）", "米・卵・調味料・野菜", (0, 2, 4), 118000, "2015-06"),
    ("C04", "喫茶 こもれび（架空）", "喫茶店", "牛乳・パン・卵", (2,), 38000, "2021-09"),
    ("C05", "介護施設 あおぞらの家（架空）", "介護施設（入居）", "食材・飲料・日用品", (0, 2, 4), 82000, "2024-01"),
    ("C06", "デイサービス のぞみ（架空）", "介護（通い）", "お茶・お菓子・日用品", (1, 4), 56000, "2022-04"),
]
CUST = {c[0]: c for c in CUSTOMERS}
OVERDUE = "C01"
DECLINING = "C05"
DECLINE = {4: 0.93, 3: 0.87, 2: 0.81, 1: 0.77, 0: 0.77}

STAFF = [
    ("山田 太郎", "代表取締役（三代目店主）", "役員", "最後の判断・仕入れの目利き・お酒の担当", "月〜土 8:30〜19:30", "AI社長"),
    ("山田 恵子", "専務取締役", "役員", "経理・総務・ギフトの受付", "月〜金 9:00〜17:00", "AI経理・AI法務"),
    ("山田 健太", "店長代理（四代目候補）", "正社員", "ネットショップ・Instagram・法人の窓口", "火〜土 9:00〜18:00", "AI EC販売・AI広告・AI広報・AI営業"),
    ("藤井 誠", "配達・仕入れ", "正社員", "配達（午前便）・発注・品出し", "月〜土 8:00〜17:00", "AI仕入れ・AI物流"),
    ("小林 学", "配達", "パート", "配達（午後便）", "月・水・金・土 13:00〜18:00", "AI物流"),
    ("岡本 典子", "レジ・電話", "パート", "レジ・電話の受付・品出し", "月〜金 9:00〜14:00", "AI受付・AI接客"),
    ("西川 美穂", "レジ", "パート", "夕方のレジ", "月〜土 15:00〜19:00", "AI接客"),
    ("森田 由美", "惣菜", "パート", "惣菜・お弁当づくり（食品衛生責任者）", "月〜土 7:00〜12:00", "AI店長"),
]
# 人の働いた時間（曜日ごと・時間）。人時売上の計算に使う（月〜土）
STAFF_HOURS = [53, 49, 53, 49, 53, 49, 0]

SEASON = {1: 0.90, 2: 0.92, 3: 1.00, 4: 1.00, 5: 1.02, 6: 0.97, 7: 1.04, 8: 1.10, 9: 0.98, 10: 1.00, 11: 1.00, 12: 1.15}
ALC = {1: 1.05, 7: 1.08, 8: 1.12, 12: 1.20}
WDF = [0.95, 1.00, 0.97, 1.00, 1.05, 1.25, 0.0]
RAIN_P = {6: 0.45, 7: 0.30, 9: 0.35}
GROWTH = {"店舗": -0.03, "配達": 0.08, "EC": 0.12, "法人": 0.0,
          "ギフト_店頭": -0.05, "ギフト_電話": 0.0, "ギフト_ネット": 0.70, "ギフト_法人": 0.0}
CHANNELS = ["店頭", "電話", "ネット", "法人"]
GIFT_BASE = {"お歳暮": {"店頭": 2.6, "電話": 1.4, "ネット": 2.2, "法人": 0.7},
             "お中元": {"店頭": 2.2, "電話": 1.1, "ネット": 1.4, "法人": 0.5}}
EC_W = [("S01", 0.22), ("S06", 0.22), ("S07", 0.10), ("S10", 0.08), ("S11", 0.15), ("S12", 0.15), ("F24", 0.08)]
DISTRICTS = [("東地区", 0.20, 10), ("西地区", 0.20, 10), ("南地区", 0.18, 11), ("北地区（高台の団地）", 0.42, 18)]
PERSONNEL = 900000
BONUS = {7: 150000, 12: 200000}
LOAN = 100000
OPEN_BALANCE = 4_800_000          # 歴史の窓の最初の日の朝の残高（ここから現金を積み上げる）


def unit(iid: str) -> str:
    return UNIT.get(iid, "個")


def qty_s(iid: str, n) -> str:
    """数に単位をつける（例：80パック）。"""
    return f"{int(n) if float(n) == int(float(n)) else n}{unit(iid)}"


def is_manual(iid: str) -> bool:
    return ITEM[iid][8] in MANUAL_SUPPLIERS


def ec_daily(iid: str) -> float:
    return dict(EC_W).get(iid, 0) * 3.4 * (2.0 if iid == "S01" else 1.1)


def reorder_point(iid: str) -> int:
    """発注点。定期（自動）の品は（店＋ネットの1日平均）×（納期＋3日）。手配の品と生ものはマスタのまま。"""
    it = ITEM[iid]
    if is_manual(iid) or iid in DAILY_FRESH or it[8] == "店内調理":
        return it[7]
    return math.ceil((it[6] + ec_daily(iid)) * (it[9] + 3))


def personnel(month: int, extra: int = 0) -> int:
    return PERSONNEL + BONUS.get(month, 0) + extra


def festival_name(day: dt.date) -> str:
    return {12: "冬の市", 1: "冬の市", 2: "冬の市", 3: "春祭り", 4: "春祭り", 5: "春祭り",
            6: "夏祭り", 7: "夏祭り", 8: "夏祭り"}.get(day.month, "秋祭り")


def gift_season(day: dt.date, ch: str):
    y = day.year
    start = dt.date(y, 10, 20) if (ch == "ネット" or y >= 2026) else dt.date(y, 11, 20)  # 2025年までの店頭は11/20から
    if start <= day <= dt.date(y, 12, 25):
        return "お歳暮"
    if dt.date(y, 6, 10) <= day <= dt.date(y, 7, 31):
        return "お中元"
    return None


def gift_shape(day: dt.date, season: str) -> float:
    y = day.year
    if season == "お歳暮":
        return 0.45 if day <= dt.date(y, 11, 20) else (1.6 if day <= dt.date(y, 12, 10) else 0.7)
    return 0.8 if day <= dt.date(y, 6, 30) else (1.5 if day <= dt.date(y, 7, 20) else 0.6)


def sround(rnd: random.Random, lam: float) -> int:
    """確率で四捨五入（平均は lam のまま・ばらつきは小さい）"""
    if lam <= 0:
        return 0
    return int(lam) + (1 if rnd.random() < lam - int(lam) else 0)


def poisson(rnd: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, int(round(rnd.gauss(lam, math.sqrt(lam)))))
    lim, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rnd.random()
        if p <= lim:
            return k
        k += 1


def pick(rnd, weighted):
    x, acc = rnd.random(), 0.0
    tot = sum(w for _, w in weighted)
    for k, w in weighted:
        acc += w / tot
        if x <= acc:
            return k
    return weighted[-1][0]


def add_channel(acc: dict, name: str, amount: int):
    """販路ごとに注文数・売上・手数料を足す。"""
    rate = {n: r for n, _, _, r in EC_CHANNELS}[name]
    a = acc.setdefault(name, {"orders": 0, "sales": 0, "fee": 0})
    a["orders"] += 1
    a["sales"] += amount
    a["fee"] = int(round(a["sales"] * rate))


def b2b_month_amount(rnd, cid, m: dt.date, m0: dt.date) -> int:
    c = CUST[cid]
    s = c[5] * rnd.uniform(0.93, 1.07)
    if c[2] in ("飲食店（居酒屋）", "飲食店（焼き鳥）"):
        s *= {12: 1.25, 8: 1.10, 1: 0.85}.get(m.month, 1.0)
    if cid == DECLINING:
        back = (m0.year - m.year) * 12 + m0.month - m.month
        s *= DECLINE.get(back, 1.0)
    return yen(s)


def visit_days(cid, m: dt.date, dows=None):
    dows = dows if dows is not None else CUST[cid][4]
    out, x = [], m.replace(day=1)
    while x.month == m.month:
        if x.weekday() in dows and is_open(x):
            out.append(x)
        x += dt.timedelta(days=1)
    return out


def build_history(today: dt.date) -> dict:
    """「今日」の前の日までの2年分の会社の動き（日ごとの記録）を作る。"""
    rnd = random.Random(SEED)
    yday = today - dt.timedelta(days=1)
    m0 = today.replace(day=1)
    start = add_months(m0, -24)
    stockout = today - dt.timedelta(days=5)
    fest = today + dt.timedelta(days=(5 - today.weekday()) % 7 or 7)
    fest_last = fest - dt.timedelta(days=364)
    insta_start = add_months(m0, -5)

    def tr(key, day):
        return (1 + GROWTH[key]) ** ((day - today).days / 365)

    chrnd = random.Random(SEED + 7)               # 販路（自社・楽天・Amazon）は別の乱数で決める（ほかの数字を変えないため）
    days, x = [], start
    while x <= yday:
        days.append(x)
        x += dt.timedelta(days=1)

    L = {}
    for day in days:
        r = {"date": day}
        rain = rnd.random() < RAIN_P.get(day.month, 0.25)
        r["weather"] = "雨" if rain else ("晴れ" if rnd.random() < 0.6 else "くもり")
        qty, sales, cost = {}, {}, {}
        dept = {"食料品": 0, "日用品": 0, "酒類": 0}
        lost = waste = 0
        if is_open(day):
            base = WDF[day.weekday()] * SEASON[day.month] * tr("店舗", day) * (0.88 if rain else 1.0)
            if day.month == 12 and day.day >= 28:
                base *= 1.35
            for iid, name, dp, cat, price, c, avg, *_ in ITEMS:
                lam = avg * base
                if dp == "酒類":
                    lam *= ALC.get(day.month, 1.0)
                if day == fest_last and (dp == "酒類" or cat == "飲料"):
                    lam *= 1.9
                if day >= stockout:
                    lam *= {"S02": 1.08, "S05": 1.05}.get(iid, 0.93 if dp == "酒類" else 1.0)
                expect = lam
                lam *= rnd.uniform(0.85, 1.15)
                q = sround(rnd, lam)
                if iid == "S01" and day >= stockout:
                    lost += int(round(avg * base * ALC.get(day.month, 1.0))) * price   # 在庫があれば売れたはずの分
                    q = 0
                if iid in COOKED:
                    made = math.ceil(expect * 1.03)
                    waste += max(0, made - q) * c
                qty[iid], sales[iid], cost[iid] = q, q * price, q * c
                dept[dp] += q * price
            for dp, (oid, oname, obase, orate) in OTHER.items():
                amt = obase * base * rnd.uniform(0.92, 1.08) * (ALC.get(day.month, 1.0) if dp == "酒類" else 1.0)
                if day == fest_last and dp == "酒類":
                    amt *= 1.9
                amt = yen(amt)
                sales[oid], cost[oid] = amt, amt * orate
                dept[dp] += amt
            cust = 108 * WDF[day.weekday()] * math.sqrt(SEASON[day.month]) * tr("店舗", day) * (0.9 if rain else 1.0)
            cust *= rnd.uniform(0.93, 1.07) * (0.96 if day >= stockout else 1.0) * (1.3 if day == fest_last else 1.0)
            r["cust"] = int(round(cust))
        else:
            r["cust"] = 0
        r.update(qty=qty, sales=sales, cost=cost, dept=dept, store=sum(dept.values()),
                 store_cost=sum(cost.values()), lost=lost, waste=yen(waste))
        dl = {"orders": 0, "sales": 0, "cost": 0, "calls": 0, "am_calls": 0, "missed": 0,
              "dist": {k: 0 for k, *_ in DISTRICTS}, "am": 0, "pm": 0, "minutes": 0, "north_min": 0}
        if is_open(day):
            n = poisson(rnd, 8.5 * tr("配達", day) * (1.55 if rain else 1.0) * (1.15 if day.weekday() == 0 else 1.0))
            missed = poisson(rnd, 5.0 if rain else 0.7)
            ask = poisson(rnd, 1.5)
            calls = n + missed + ask
            dl.update(orders=n, missed=missed, calls=calls)
            dl["am_calls"] = int(round(calls * rnd.uniform(0.62, 0.75)))
            for _ in range(n):
                amt = yen(rnd.uniform(1300, 3600))
                dl["sales"] += amt + (200 if amt < 3000 else 0)
                dl["cost"] += amt * 0.72
                k = pick(rnd, [(k, p) for k, p, _ in DISTRICTS])
                mins = dict((k2, m2) for k2, _, m2 in DISTRICTS)[k]
                dl["dist"][k] += 1
                mm = max(5, int(round(rnd.gauss(mins, 3))))
                dl["minutes"] += mm
                if k.startswith("北"):
                    dl["north_min"] += mm
                if rnd.random() < 0.68:
                    dl["am"] += 1
                else:
                    dl["pm"] += 1
        r["dl"] = dl
        ec = {"orders": 0, "sales": 0, "cost": 0, "by": {}, "byo": {}, "unshipped": [], "ch": {}}
        ecs = {12: 1.3, 11: 1.1, 8: 1.15}.get(day.month, 1.0)
        n = poisson(rnd, 3.4 * ecs * tr("EC", day) * (1.15 if day.weekday() >= 5 else 1.0))
        for _ in range(n):
            iid = pick(rnd, EC_W)
            q = rnd.choice([1, 2, 2, 3]) if iid == "S01" else (2 if rnd.random() < 0.1 else 1)
            it = ITEM[iid]
            ec["orders"] += 1
            ec["sales"] += it[4] * q
            ec["cost"] += it[5] * q
            ec["by"][iid] = ec["by"].get(iid, 0) + q
            ec["byo"][iid] = ec["byo"].get(iid, 0) + 1
            add_channel(ec["ch"], pick(chrnd, [(n, w) for n, _, w, _ in EC_CHANNELS]), it[4] * q)
            if iid == "S01" and day >= stockout:
                ec["unshipped"].append((iid, q))
        visits = int(rnd.gauss(150, 20) * ecs * tr("EC", day) * (1.15 if day.weekday() >= 5 else 1.0)) + n * 12
        ig = 0.34 if day >= insta_start else 0.24
        split = [s * rnd.uniform(0.85, 1.15) for s in (0.44, ig, 0.16, 0.10)]
        tot = sum(split)
        ec["flow"] = [int(round(visits * s / tot)) for s in split]
        ec["visits"] = sum(ec["flow"])
        r["ec"] = ec
        gift = {ch: {"n": 0, "sales": 0, "cost": 0, "by": {}, "ch": {}} for ch in CHANNELS}
        for ch in CHANNELS:
            season = gift_season(day, ch)
            if not season or (ch != "ネット" and not is_open(day)):
                continue
            k = sround(rnd, GIFT_BASE[season][ch] * gift_shape(day, season) * tr("ギフト_" + ch, day))
            for _ in range(k):
                pool = [(g, GIFT_W[g]) for g in GIFT if g != "G02" or day >= G02_START]
                g = pick(rnd, pool)
                gift[ch]["n"] += 1
                gift[ch]["sales"] += GIFT[g][2]
                gift[ch]["cost"] += GIFT[g][3]
                gift[ch]["by"][g] = gift[ch]["by"].get(g, 0) + 1
                if ch == "ネット":
                    add_channel(gift[ch]["ch"], pick(chrnd, [(n, w) for n, _, w, _ in GIFT_CHANNELS]), GIFT[g][2])
        r["gift"] = gift
        r["gift_sales"] = sum(v["sales"] for v in gift.values())
        r["gift_cost"] = sum(v["cost"] for v in gift.values())
        L[day] = r

    months = [add_months(m0, -i) for i in range(24, 0, -1)]
    b2b = {}
    for m in months:
        for cid, *_ in CUSTOMERS:
            s = b2b_month_amount(rnd, cid, m, m0)
            vd = visit_days(cid, m)
            if cid == DECLINING and rnd.random() < 0.3 and vd:
                vd = vd[:-1]
            b2b[(m, cid)] = {"sales": s, "cost": yen(s * 0.82), "visits": len(vd), "days": vd}
    # 今月（途中）の法人：1回の目安で、昨日までの配達の日に入れる
    cur = {}
    for cid, *_ in CUSTOMERS:
        s = b2b_month_amount(rnd, cid, m0, m0)
        vd = visit_days(cid, m0)
        per = s / max(1, len(vd))
        cur[cid] = {"per_visit": per, "days": [x for x in vd if x < today]}
    return dict(today=today, yday=yday, m0=m0, days=days, L=L, months=months, b2b=b2b, b2b_cur=cur,
                stockout=stockout, fest=fest, fest_last=fest_last, insta_start=insta_start, rnd=rnd)


def b2b_daily(W, day_list):
    """法人の月の売上を、その月の配達の日に分ける（合計は月の売上と同じ）。"""
    out = {}
    for (m, cid), b in W["b2b"].items():
        if not b["days"]:
            continue
        n = len(b["days"])
        base = b["sales"] // n
        for i, x in enumerate(b["days"]):
            amt = base + (b["sales"] - base * n if i == n - 1 else 0)
            out.setdefault(x, {})[cid] = amt
    for cid, c in W["b2b_cur"].items():
        for x in c["days"]:
            out.setdefault(x, {})[cid] = yen(c["per_visit"])
    return {x: out.get(x, {}) for x in day_list}
