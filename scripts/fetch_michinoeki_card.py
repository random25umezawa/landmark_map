"""道の駅カードの販売有無・スタンプラリーのエリア・24時間スタンプの有無を
data/michinoeki.geojson の各地点に付与する。

道の駅カードは全国共通の一覧が無く、地方ブロックの「道の駅」連絡会ごとに発行・告知されている。
在庫状況は日々変わるため扱わず、「販売駅の一覧に載っているか(完売の明記があれば完売)」だけを見る。

  地域      取得元                                      取得方法
  東北      東北「道の駅」連絡会 カード第二弾ページ       HTML(県別の駅名列挙)
  関東      関東「道の駅」 ブロック別販売駅ページ         HTML
  北陸      北陸「道の駅」 カード発売ページ               HTML(「完売 - 駅名」の表記あり)
  中部      静岡県: 連絡会トップのお知らせ                HTML
            愛知県・三重県: 県内全駅販売のポスター        PREF_WIDE(手動)
            長野県: ポスターのみで販売駅を特定できない     PREF_UNKNOWN(手動)
  近畿      近畿「道の駅」 カードページ                   HTML
  中国      中国5県とも県内全駅販売のポスター             PREF_WIDE(手動)
  四国      四国地区「道の駅」 記念カードのお知らせ        HTML(取り消し線=完売)
  北海道・九州沖縄・岐阜県・東京都: 連絡会のカードは確認できず(プロパティを付けない)

スタンプラリーのエリアは各ブロックの連絡会単位(9エリア)。都道府県から一意に決まるが、
長野県だけは北部が関東ブロック・南信が中部ブロックに分かれるため、関東「道の駅」の
長野県駅一覧に載っている駅を関東、それ以外を中部とする。

24時間スタンプは全国的な一覧が無いため scripts/manual_overrides/michinoeki_stamp24h.json に
手動で記録する(公式の告知で確認できたものは confidence: official、
ファンサイト等の二次情報だけのものは unconfirmed)。

fetch_michinoeki.py の実行後に走らせること。
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

import certifi
import requests
from bs4 import BeautifulSoup

from fetch_michinoeki import normalize_name

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
MICHINOEKI_PATH = ROOT / "data" / "michinoeki.geojson"
UNMATCHED_PATH = ROOT / "data" / "michinoeki-card-unmatched.json"
STAMP24H_PATH = SCRIPTS / "manual_overrides" / "michinoeki_stamp24h.json"
# 北陸「道の駅」のサーバーは中間証明書を送ってこないため、発行元(GlobalSign)の
# 中間証明書を補った証明書バンドルで検証する(検証自体は省略しない)
EXTRA_CA_PATH = SCRIPTS / "certs" / "globalsign_gcc_r46_dv_tls_ca_2025.pem"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; landmark-map-research/1.0)"}
REQUEST_INTERVAL_SEC = 3.0  # いずれのサイトもrobots.txtにCrawl-delay指定は無いが間隔を空ける

ATTRIBUTION_CARD = (
    "出典(道の駅カード・スタンプラリー): 東北・関東・北陸・中部・近畿・中国・四国の各「道の駅」連絡会の"
    "公式ホームページを加工して作成"
)

STAMP_AREAS = {
    "北海道": ["北海道"],
    "東北": ["青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県"],
    "関東": ["茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県", "山梨県"],  # +長野県北部
    "北陸": ["新潟県", "富山県", "石川県"],
    "中部": ["岐阜県", "静岡県", "愛知県", "三重県"],  # +長野県南信
    "近畿": ["福井県", "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県"],
    "中国": ["鳥取県", "島根県", "岡山県", "広島県", "山口県"],
    "四国": ["徳島県", "香川県", "愛媛県", "高知県"],
    "九州沖縄": ["福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県"],
}
PREF_TO_AREA = {pref: area for area, prefs in STAMP_AREAS.items() for pref in prefs}

# 県内全駅で販売している旨のポスターしか無い県(駅名の一覧が無い)。
# ポスター作成後に開業した駅は扱っていない可能性があるため、販売状況の文言でそれと分かるようにする。
PREF_WIDE = {
    "愛知県": ("中部ブロック「道の駅」カード", "https://www.chubu-michinoeki.org/pdf/aichi_card.pdf"),
    "三重県": ("中部ブロック「道の駅」カード", "https://www.chubu-michinoeki.org/pdf/card_mie.pdf"),
    "鳥取県": ("中国「道の駅」カード", "https://chugoku-michinoeki.jp/pdf/card_tottori.pdf"),
    "島根県": ("中国「道の駅」カード", "https://chugoku-michinoeki.jp/pdf/card_shimane.pdf"),
    "岡山県": ("中国「道の駅」カード", "https://chugoku-michinoeki.jp/pdf/card_okayama.pdf"),
    "広島県": ("中国「道の駅」カード", "https://chugoku-michinoeki.jp/pdf/card_hiroshima.pdf"),
    "山口県": ("中国「道の駅」カード", "https://chugoku-michinoeki.jp/pdf/card_yamaguchi.pdf"),
}
# カードはあるが、駅単位の販売有無が公式情報から特定できない県
PREF_UNKNOWN = {
    "長野県": "長野県内の一部の駅で販売(販売駅の一覧は画像のみで駅を特定できないため要確認)",
}

_last_request = 0.0
_ca_bundle: str | None = None


def ca_bundle() -> str:
    global _ca_bundle
    if _ca_bundle is None:
        path = Path(tempfile.gettempdir()) / "landmark_map_ca_bundle.pem"
        path.write_text(
            Path(certifi.where()).read_text(encoding="utf-8") + "\n" + EXTRA_CA_PATH.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        _ca_bundle = str(path)
    return _ca_bundle


def get_html(url: str) -> str:
    global _last_request
    wait = REQUEST_INTERVAL_SEC - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30, verify=ca_bundle())
        resp.raise_for_status()
        return resp.content.decode("utf-8-sig")  # 文字コード宣言の無いページがあるためUTF-8決め打ち
    finally:
        _last_request = time.monotonic()


# ---- 地域別の販売駅一覧 ----
# いずれも [(県名のリスト, 駅名, 販売状況), ...] を返す。販売状況は "販売" または "完売"。
# 県名のリストは照合対象の県(関東の「神奈川県・山梨県ブロック」のように複数県をまとめた一覧があるため)。

def cards_tohoku() -> list[tuple[list[str], str, str]]:
    soup = BeautifulSoup(get_html("https://www.michinoeki-tohoku.com/card2"), "html.parser")
    entries = []
    for tr in soup.select("table tr"):
        th, td = tr.find("th"), tr.find("td")
        if th is None or td is None or th.get_text(strip=True) not in STAMP_AREAS["東北"]:
            continue
        for name in td.get_text(strip=True).split("、"):
            if name:
                entries.append(([th.get_text(strip=True)], name, "販売"))
    return entries


KANTO_BLOCKS = {
    "茨城県ブロック販売駅": ["茨城県"],
    "栃木県ブロック販売駅": ["栃木県"],
    "群馬県ブロック販売駅": ["群馬県"],
    "埼玉県ブロック販売駅": ["埼玉県"],
    "千葉県ブロック販売駅": ["千葉県"],
    "神奈川県・山梨県ブロック販売駅": ["神奈川県", "山梨県"],
}
_KANTO_NUM_RE = re.compile(r"^[★☆\s]*[①-⓿㉑-㉟㊱-㊿\d()（）]*[★☆\s]*")


def cards_kanto() -> list[tuple[list[str], str, str]]:
    entries = []
    for page, prefs in KANTO_BLOCKS.items():
        soup = BeautifulSoup(get_html(f"https://www.kanto-michinoeki.jp/{quote(page)}.html"), "html.parser")
        for div in soup.select("div.ekimei"):
            name = _KANTO_NUM_RE.sub("", div.get_text(strip=True))  # 例: "①かつら駅" "★⑮…駅"
            name = name.rstrip("★☆").removesuffix("駅")  # "やちよ駅★" のように★が後ろに付く駅もある
            if name:
                entries.append((prefs, name, "販売"))
    return entries


def cards_hokuriku() -> list[tuple[list[str], str, str]]:
    soup = BeautifulSoup(get_html("https://www.hokuriku-michinoeki.jp/contents/tradingcard/"), "html.parser")
    entries = []
    for h4 in soup.select("div.trcardBoxSubTtl h4"):
        pref = {"新潟": "新潟県", "富山": "富山県", "石川": "石川県"}.get(h4.get_text(strip=True))
        box = h4.find_parent("div").find_next_sibling("div", class_="trcardBox")
        if pref is None or box is None:
            continue
        for td in box.select("td"):
            text = td.get_text(strip=True)
            m = re.match(r"完売\s*-\s*(.+)", text)
            if m:
                entries.append(([pref], m.group(1), "完売"))
            elif text:
                entries.append(([pref], text, "販売"))
    return entries


_SHIZUOKA_RE = re.compile(r"静岡\d{2}\s*([^\s『』（(、]+)")


def cards_chubu_shizuoka() -> list[tuple[list[str], str, str]]:
    soup = BeautifulSoup(get_html("https://www.chubu-michinoeki.org/"), "html.parser")
    entries = []
    for line in soup.get_text("\n").splitlines():
        # 販売駅一覧の各行(例: "静岡01 富士")と、追加販売のお知らせ(例: "『静岡27 ゆとりえせとや』")
        if "未定" in line:  # "静岡21すばしり、は販売時期未定"
            continue
        for m in _SHIZUOKA_RE.finditer(line):
            entries.append((["静岡県"], m.group(1), "販売"))
    return entries


KINKI_PREF_CLASSES = {
    "fukui": "福井県", "shiga": "滋賀県", "kyoto": "京都府", "osaka": "大阪府",
    "hyogo": "兵庫県", "nara": "奈良県", "wakayama": "和歌山県",
}


def cards_kinki() -> list[tuple[list[str], str, str]]:
    soup = BeautifulSoup(get_html("https://www.kinki-michinoeki.com/card/"), "html.parser")
    entries = []
    for post in soup.select("div.station_card_info div.vk_post"):
        prefs = [p for cls, p in KINKI_PREF_CLASSES.items() if f"prefectures-{cls}" in post.get("class", [])]
        title = post.select_one(".vk_post_title")
        if prefs and title:
            entries.append((prefs, title.get_text(strip=True), "販売"))  # 在庫状況の表示は使わない
    return entries


_SHIKOKU_NOISE_RE = re.compile(r"[（(](在庫わずか|[^）)]*販売開始)[）)]|\d+月\d+日完売")


def cards_shikoku() -> list[tuple[list[str], str, str]]:
    html = get_html("https://www.sk-michinoeki.jp/archives/1695")
    start, end = html.find("カード取り扱い駅"), html.find("在庫は日々変動")
    soup = BeautifulSoup(html[start:end], "html.parser")
    for d in soup.find_all("del"):  # 取り消し線 = 完売
        d.replace_with(f"、完売:{d.get_text(strip=True)}、")
    entries = []
    for m in re.finditer(r"【(.+?)】([^【]*)", soup.get_text()):
        pref = m.group(1)
        body = _SHIKOKU_NOISE_RE.sub("、", m.group(2))
        for name in re.split(r"[、\s　]+", body):
            if not re.search(r"\w", name):  # 末尾の注記の "※" 等
                continue
            if name.startswith("完売:"):
                entries.append(([pref], name.removeprefix("完売:"), "完売"))
            else:
                entries.append(([pref], name, "販売"))
    return entries


CARD_SOURCES = [
    ("東北「道の駅」カード", STAMP_AREAS["東北"], cards_tohoku, "https://www.michinoeki-tohoku.com/card2"),
    ("関東「道の駅」カード", sum(KANTO_BLOCKS.values(), []), cards_kanto, "https://www.kanto-michinoeki.jp/道の駅カード.html"),
    ("北陸「道の駅」カード", STAMP_AREAS["北陸"], cards_hokuriku, "https://www.hokuriku-michinoeki.jp/contents/tradingcard/"),
    ("中部ブロック「道の駅」カード", ["静岡県"], cards_chubu_shizuoka, "https://www.chubu-michinoeki.org/"),
    ("近畿「道の駅」カード", STAMP_AREAS["近畿"], cards_kinki, "https://www.kinki-michinoeki.com/card/"),
    ("四国地区「道の駅」記念カード", STAMP_AREAS["四国"], cards_shikoku, "https://www.sk-michinoeki.jp/archives/1695"),
]


def kanto_nagano_names() -> set[str]:
    """関東「道の駅」の長野県駅一覧(=スタンプラリーの関東エリアに入る長野県の駅)。"""
    soup = BeautifulSoup(get_html("https://www.kanto-michinoeki.jp/map02.php?id_name=8"), "html.parser")
    return {match_key(h3.get_text(strip=True)) for h3 in soup.select("div.stationBox-single h3")}


# ---- 照合 ----

# 掲載元の誤記で照合できない駅名(掲載元の表記 -> 国交省一覧の表記)
NAME_ALIASES = {
    "釜石千人峠": "釜石仙人峠",
}
# "八ツ場"/"八ッ場"、"種山ケ原"/"種山ヶ原" のような大小の仮名の揺れを吸収する
_KANA_SIZE = str.maketrans({"ッ": "ツ", "ヶ": "ケ", "ヵ": "カ"})


def match_key(name: str) -> str:
    return normalize_name(name).translate(_KANA_SIZE)


class StationIndex:
    def __init__(self, features: list[dict]) -> None:
        self.by_pref: dict[str, list[tuple[str, dict]]] = {}
        for f in features:
            p = f["properties"]
            self.by_pref.setdefault(p["pref"], []).append((match_key(p["name"]), f))

    def find(self, prefs: list[str], name: str) -> dict | None:
        """正規化後の完全一致 → 一方が他方を含む候補がその県内で1件だけ、の順で照合する。"""
        name = NAME_ALIASES.get(name, name)
        norm = match_key(re.sub(r"[（(].*?[）)]", "", name))  # "宇津ノ谷峠（藤枝側）" 等
        for pref in prefs:
            exact = [f for n, f in self.by_pref.get(pref, []) if n == norm]
            if len(exact) == 1:
                return exact[0]
        partial = [f for pref in prefs for n, f in self.by_pref.get(pref, []) if norm in n or n in norm]
        return partial[0] if len(partial) == 1 else None


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    geojson = json.loads(MICHINOEKI_PATH.read_text(encoding="utf-8"))
    features = geojson["features"]
    index = StationIndex(features)
    unmatched: list[dict] = []

    for f in features:
        for k in ("card_available", "card_status", "stamp_area", "stamp_24h", "stamp_24h_confidence", "stamp_24h_source",
                  "stamp_24h_label"):
            f["properties"].pop(k, None)

    # ---- スタンプラリーのエリア ----
    nagano_kanto = kanto_nagano_names()
    nagano_index = StationIndex([f for f in features if f["properties"]["pref"] == "長野県"])
    kanto_features = set()
    for name in nagano_kanto:
        f = nagano_index.find(["長野県"], name)
        if f is None:
            unmatched.append({"program": "関東「道の駅」の長野県駅一覧(スタンプエリア)", "name": name})
        else:
            kanto_features.add(id(f))
    for f in features:
        p = f["properties"]
        if p["pref"] == "長野県":
            p["stamp_area"] = "関東" if id(f) in kanto_features else "中部"
        else:
            p["stamp_area"] = PREF_TO_AREA.get(p["pref"])
    print(
        f"長野県: 関東エリア {len(kanto_features)}駅 / 中部エリア "
        f"{sum(1 for f in features if f['properties'].get('stamp_area') == '中部' and f['properties']['pref'] == '長野県')}駅",
        file=sys.stderr,
    )

    # ---- 道の駅カード ----
    # 一覧のある地域: 一覧の駅は販売/完売、一覧に無い駅は「一覧に記載なし」
    for program, prefs, fetcher, url in CARD_SOURCES:
        entries = fetcher()
        print(f"{program}: {len(entries)}件", file=sys.stderr)
        for f in features:
            if f["properties"]["pref"] in prefs:
                f["properties"]["card_available"] = False
                f["properties"]["card_status"] = f"販売駅の一覧に記載なし({program})"
        for entry_prefs, name, status in entries:
            f = index.find(entry_prefs, name)
            if f is None:
                unmatched.append({"program": program, "prefs": entry_prefs, "name": name, "status": status, "source": url})
                continue
            f["properties"]["card_available"] = status == "販売"
            f["properties"]["card_status"] = f"{'販売' if status == '販売' else '完売'}({program})"

    for f in features:
        p = f["properties"]
        if p["pref"] in PREF_WIDE:
            program, _ = PREF_WIDE[p["pref"]]
            p["card_available"] = True
            p["card_status"] = f"販売({program}、県内全駅で販売との告知に基づく。新しい駅は要確認)"
        elif p["pref"] in PREF_UNKNOWN:
            p["card_status"] = PREF_UNKNOWN[p["pref"]]
        elif "card_available" not in p:
            # 北海道・九州沖縄・岐阜県・東京都(連絡会としてのカード発行を確認できなかった地域)
            p["card_available"] = False
            p["card_status"] = "この地域の連絡会による道の駅カードは確認できていません"

    # ---- 24時間スタンプ(手動記録) ----
    stamp24h = json.loads(STAMP24H_PATH.read_text(encoding="utf-8")) if STAMP24H_PATH.exists() else {}
    by_key = {f"{f['properties']['pref']}/{f['properties']['name']}": f for f in features}
    for key, rec in stamp24h.items():
        if key.startswith("_"):
            continue
        f = by_key.get(key)
        if f is None:
            pref, _, name = key.partition("/")
            f = index.find([pref], name)
        if f is None:
            unmatched.append({"program": "24時間スタンプ(手動記録)", "key": key})
            continue
        f["properties"]["stamp_24h"] = True
        f["properties"]["stamp_24h_confidence"] = rec["confidence"]
        f["properties"]["stamp_24h_source"] = rec["source"]
        f["properties"]["stamp_24h_label"] = (
            "押印可(公式の告知で確認)" if rec["confidence"] == "official" else "押印可との情報あり(未確認・要確認)"
        )

    if ATTRIBUTION_CARD not in geojson["attribution"]:
        geojson["attribution"] = geojson["attribution"] + "<br>" + ATTRIBUTION_CARD
    MICHINOEKI_PATH.write_text(json.dumps(geojson, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    UNMATCHED_PATH.write_text(json.dumps(unmatched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def count(pred):
        return sum(1 for f in features if pred(f["properties"]))
    print(
        f"カード販売 {count(lambda p: p.get('card_available') is True)}駅 / "
        f"販売なし・完売・カード未確認 {count(lambda p: p.get('card_available') is False)}駅 / "
        f"販売駅を特定できない {count(lambda p: 'card_available' not in p)}駅、"
        f"24時間スタンプ {count(lambda p: p.get('stamp_24h'))}駅。"
        f"照合できなかった{len(unmatched)}件は{UNMATCHED_PATH}へ保存。"
    )


if __name__ == "__main__":
    main()
