"""やまだ商店（架空）が使っている「ことにしている」サービスとデータの出どころ（データマップ）。

**全部シミュレーションです。どのサービスにも実際にはつないでいません**（simulated: true）。
data/ のファイルは tools/sim.py が作っていますが、「本物の会社なら、このサービスからこう取り込む」という対応を書いています。
sim.py init が data/_sources.json に書き出し、company/データマップ.md と dashboard_data.json がこれを使います。
"""

# id, サービス名, 分類, 何のデータ, 取り込み方, 頻度, data/ のファイル, 使う AI
_S = [
    ("smaregi", "スマレジ（POS レジ）", "店舗", "店の売上・客数・客単価・品目ごとの売れ数・在庫・発注", "API", "毎晩",
     ["store/POS_日別.csv", "store/POS_商品別_直近14日.csv", "purchasing/在庫.csv", "purchasing/発注履歴.csv", "master/商品.csv"],
     ["AI店長", "AI仕入れ"]),
    ("shopify", "自社ネットショップ（Shopify）", "EC", "自社サイトの注文・商品ページ・のしギフト・サイトのお知らせ", "API", "毎晩",
     ["ec/注文_日別.csv", "ec/チャネル別_日別.csv", "ec/注文_商品別_直近28日.csv", "ec/商品ページ.csv", "gift/ギフト受注_日別.csv", "pr/お知らせ.md"],
     ["AI EC販売", "AI物流", "AI広報"]),
    ("rakuten", "楽天市場（RMS）", "EC", "楽天の店の注文・手数料・ギフトの注文", "CSV書き出し", "毎朝",
     ["ec/注文_日別.csv", "ec/チャネル別_日別.csv", "ec/注文_商品別_直近28日.csv", "ec/商品ページ.csv", "gift/ギフト受注_日別.csv"],
     ["AI EC販売"]),
    ("amazon", "Amazon（セラーセントラル）", "EC", "Amazon の注文・手数料・ギフトの注文", "API", "毎晩",
     ["ec/注文_日別.csv", "ec/チャネル別_日別.csv", "ec/注文_商品別_直近28日.csv", "ec/商品ページ.csv", "gift/ギフト受注_日別.csv"],
     ["AI EC販売"]),
    ("ga4", "Google アナリティクス 4", "Web", "ネットショップの訪問（セッション）・流入元・購入率", "API", "毎朝",
     ["ec/注文_日別.csv", "ec/商品ページ.csv"], ["AI EC販売", "AI広告"]),
    ("google_ads", "Google 広告", "広告", "検索広告の費用・表示・クリック・反応からの売上", "API", "毎朝",
     ["marketing/広告.csv"], ["AI広告"]),
    ("meta_ads", "Meta 広告（Instagram 広告）", "広告", "Instagram 広告の費用・表示・クリック・反応からの売上", "API", "毎朝",
     ["marketing/広告.csv"], ["AI広告"]),
    ("flyer_invoice", "新聞折込チラシ（印刷会社の請求書）", "広告", "チラシの費用・配った部数・クーポンの回収", "手入力", "月次",
     ["marketing/広告.csv"], ["AI広告", "AI経理"]),
    ("freee_accounting", "freee 会計", "会計", "仕訳・毎日の帳簿・月次の損益・売掛金・買掛金・取引先", "API", "毎晩",
     ["accounting/日計表.csv", "accounting/月次PL.csv", "accounting/売掛金.csv", "accounting/買掛金.csv", "master/仕入先.csv",
      "master/法人顧客.csv"], ["AI経理", "AI社長"]),
    ("freee_invoice", "freee 請求書", "会計", "法人への納品と請求書", "API", "毎晩",
     ["b2b/納品_日別.csv", "b2b/法人売上_月別.csv", "accounting/売掛金.csv"], ["AI営業", "AI経理"]),
    ("mf_expense", "マネーフォワード クラウド経費", "会計", "経費の精算（ガソリン・消耗品・立て替え）", "CSV書き出し", "毎週",
     ["accounting/月次PL.csv"], ["AI経理"]),
    ("netbank", "ネットバンキング（△△銀行・架空）", "会計", "口座の入金・出金・残高", "CSV書き出し", "毎朝",
     ["accounting/日計表.csv", "accounting/資金繰り.csv", "accounting/売掛金.csv"], ["AI経理"]),
    ("gbp", "Google ビジネスプロフィール", "口コミ・SNS", "地図の口コミ・電話と道順のタップ", "API", "毎朝",
     ["marketing/口コミ.csv", "marketing/広告.csv"], ["AI接客", "AI広報"]),
    ("instagram", "Instagram（Meta ビジネススイート）", "口コミ・SNS", "投稿・リーチ・フォロワー・お知らせの投稿", "API", "毎週",
     ["marketing/SNS.csv", "pr/お知らせ.md"], ["AI広報", "AI広告"]),
    ("line_oa", "LINE 公式アカウント", "口コミ・SNS", "友だちの数・配信・開封・クーポンの利用", "CSV書き出し", "毎週",
     ["marketing/LINE.csv"], ["AI広報"]),
    ("delivery_sheet", "配達・電話注文台帳（Google スプレッドシート）", "社内", "電話の着信・取れなかった電話・配達の件数・地区・便・時間", "手入力", "毎晩",
     ["delivery/配達_日別.csv"], ["AI受付", "AI物流"]),
    ("gift_sheet", "ギフト受注台帳（Google スプレッドシート）", "社内", "店頭・電話・法人のお歳暮・お中元の承り", "手入力", "毎晩",
     ["gift/ギフト受注_日別.csv", "gift/ギフト受注_週別.csv"], ["AI EC販売"]),
    ("staff_sheet", "名簿とシフト表（Google スプレッドシート）", "社内", "人の役割・勤務の時間", "手入力", "月次",
     ["master/従業員.csv"], ["AI店長", "AI社長"]),
    ("contracts_pdf", "契約書（PDF）", "社内", "契約の相手・期間・更新日・申し出期限・条項", "PDF読み取り", "月次",
     ["legal/契約.csv"], ["AI法務", "AI営業"]),
    ("licenses_pdf", "許認可（PDF）", "社内", "酒類の免許・営業許可・研修の期限", "PDF読み取り", "月次",
     ["legal/許認可.csv"], ["AI法務"]),
    ("kessansho_pdf", "前期の決算書（PDF）", "社内", "去年の月ごとの売上と損益（前年比のもと）", "PDF読み取り", "月次",
     ["accounting/月次PL.csv", "gift/ギフト受注_週別.csv"], ["AI経理", "AI社長"]),
    ("budget_excel", "事業計画・予算（Excel）", "社内", "今年度の月ごと・事業ごとの予算", "CSV書き出し", "月次",
     ["accounting/予算.csv"], ["AI経理", "AI社長"]),
    ("owner_memo", "地域の予定（店主のメモ）", "社内", "町の行事・屋台・天気の見通し", "手入力", "毎週",
     ["pr/地域の予定.md"], ["AI広報", "AI仕入れ", "AI受付"]),
]

SOURCES = [{"id": i, "name": n, "category": c, "what": w, "how": h, "freq": f, "files": [f"data/{x}" for x in fs],
            "agents": ag, "simulated": True} for i, n, c, w, h, f, fs, ag in _S]
SOURCE_IDS = {s["id"] for s in SOURCES}

# ネットの販路（自社・楽天・Amazon）：シェアと手数料率（架空の目安）
EC_CHANNELS = [("自社サイト", "shopify", 0.45, 0.036), ("楽天市場", "rakuten", 0.35, 0.095), ("Amazon", "amazon", 0.20, 0.10)]
GIFT_CHANNELS = [("自社サイト", "shopify", 0.55, 0.036), ("楽天市場", "rakuten", 0.30, 0.095), ("Amazon", "amazon", 0.15, 0.10)]
CH_RATE = {n: r for n, _, _, r in EC_CHANNELS}
CH_SOURCE = {n: s for n, s, _, _ in EC_CHANNELS}

AGENTS = [("ai-shacho", "AI社長", "社長"), ("ai-tencho", "AI店長", "店舗部"), ("ai-sekkyaku", "AI接客", "店舗部"),
          ("ai-uketsuke", "AI受付", "店舗部"), ("ai-shiire", "AI仕入れ", "仕入れ・物流部"), ("ai-butsuryu", "AI物流", "仕入れ・物流部"),
          ("ai-eigyo", "AI営業", "販売部"), ("ai-ec", "AI EC販売", "販売部"), ("ai-koukoku", "AI広告", "マーケ部"),
          ("ai-kouhou", "AI広報", "マーケ部"), ("ai-keiri", "AI経理", "管理部"), ("ai-houmu", "AI法務", "管理部")]


def sources_json(today: str) -> dict:
    return {"note": "やまだ商店は架空のサンプル企業。どのサービスにも実際にはつないでいない（すべてシミュレーション）。"
                    "data/ のファイルは tools/sim.py が作り、ここには「本物の会社なら、どのサービスから取り込むか」を書いている。",
            "today": today, "sources": SOURCES}
