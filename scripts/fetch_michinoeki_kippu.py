"""道の駅記念きっぷの販売状況を株式会社アプト(製造・発行元)の公式サイトから取得し、
data/michinoeki.geojson の各地点に kippu_available / kippu_status を付与する。

株式会社アプトの都道府県別ページ(例: https://www.a-pt.co.jp/ご注文-注文用紙/北海道/)には
その都道府県の道の駅が(記念きっぷを扱っていない駅も含め)ほぼ網羅的に一覧化されており、
各駅の「販売状況」(販売中/認定登録抹消/販売休止など)が記載されている。
robots.txtでこのパス配下は許可されている(Crawl-Delay: 5)。

michinoeki.geojsonの生成(fetch_michinoeki.py)を先に実行しておくこと。
"""
from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.a-pt.co.jp/ご注文-注文用紙/{slug}/"
MICHINOEKI_PATH = Path(__file__).resolve().parent.parent / "data" / "michinoeki.geojson"
UNMATCHED_PATH = Path(__file__).resolve().parent.parent / "data" / "michinoeki-kippu-unmatched.json"
REQUEST_INTERVAL_SEC = 5.0  # robots.txt の Crawl-Delay に合わせる
ATTRIBUTION_KIPPU = (
    "出典: 株式会社アプト「道の駅記念きっぷ」販売駅名一覧を加工して作成 "
    "(https://www.a-pt.co.jp/ご注文-注文用紙/)"
)

# スラッグ(URLパス) -> そのページが対象とする都道府県名のリスト
# 東京都・神奈川県のみ1ページに合算されている
PAGE_GROUPS: dict[str, list[str]] = {
    "北海道": ["北海道"],
    "青森県": ["青森県"], "秋田県": ["秋田県"], "岩手県": ["岩手県"],
    "山形県": ["山形県"], "宮城県": ["宮城県"], "福島県": ["福島県"],
    "茨城県": ["茨城県"], "千葉県": ["千葉県"], "栃木県": ["栃木県"],
    "東京都-神奈川県": ["東京都", "神奈川県"],
    "群馬県": ["群馬県"], "埼玉県": ["埼玉県"], "山梨県": ["山梨県"],
    "新潟県": ["新潟県"], "富山県": ["富山県"], "石川県": ["石川県"],
    "長野県": ["長野県"], "愛知県": ["愛知県"], "岐阜県": ["岐阜県"],
    "三重県": ["三重県"], "静岡県": ["静岡県"],
    "福井県": ["福井県"], "兵庫県": ["兵庫県"], "滋賀県": ["滋賀県"],
    "奈良県": ["奈良県"], "京都府": ["京都府"], "和歌山県": ["和歌山県"],
    "大阪府": ["大阪府"],
    "鳥取県": ["鳥取県"], "広島県": ["広島県"], "島根県": ["島根県"],
    "山口県": ["山口県"], "岡山県": ["岡山県"],
    "徳島県": ["徳島県"], "愛媛県": ["愛媛県"], "香川県": ["香川県"], "高知県": ["高知県"],
    "福岡県": ["福岡県"], "大分県": ["大分県"], "佐賀県": ["佐賀県"],
    "宮崎県": ["宮崎県"], "長崎県": ["長崎県"], "鹿児島県": ["鹿児島県"],
    "熊本県": ["熊本県"], "沖縄県": ["沖縄県"],
}

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; landmark-map-research/1.0)"}

# 表記ゆれ吸収用: 全半角統一(NFKC)に加え、波ダッシュ系の異体字("〜"/"~"等)を統一し、
# 区切り記号(中黒・空白等)を除去してから突き合わせる
_WAVE_DASH_RE = re.compile(r"[〜～⁓~]")
_STRIP_CHARS_RE = re.compile(r"[\s・･,、，]")


def normalize_name(name: str) -> str:
    n = unicodedata.normalize("NFKC", name)
    n = _WAVE_DASH_RE.sub("〜", n)
    n = _STRIP_CHARS_RE.sub("", n)
    return n


def fetch_page(slug: str) -> str:
    resp = requests.get(BASE_URL.format(slug=slug), headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_page(html: str) -> list[tuple[str, str]]:
    """[(駅名, 販売状況テキスト), ...] を返す(先頭のヘッダ行は除く)。"""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        return []
    rows = table.find_all("tr")[1:]  # 先頭は見出し行(No/駅名/販売状況)
    entries = []
    for tr in rows:
        cells = tr.find_all("td")
        if len(cells) < 3:
            continue
        name = cells[1].get_text(strip=True)
        status = cells[2].get_text(strip=True)
        if name:
            entries.append((name, status))
    return entries


def fetch_all_entries() -> dict[str, list[tuple[str, str]]]:
    """スラッグ -> [(駅名, 販売状況), ...] のページ単位の結果。"""
    results = {}
    for slug in PAGE_GROUPS:
        html = fetch_page(slug)
        entries = parse_page(html)
        print(f"{slug}: {len(entries)}件", file=sys.stderr)
        results[slug] = entries
        time.sleep(REQUEST_INTERVAL_SEC)
    return results


def is_available(status_text: str) -> bool:
    return "販売中" in status_text


def find_candidates(name: str, prefs: list[str], by_pref_norm: dict[tuple[str, str], list[dict]],
                     by_pref_all: dict[str, list[tuple[str, dict]]]) -> list[dict]:
    """完全一致(表記ゆれ正規化後)→ 片方が他方の接頭辞になっている一意なケース、の順で照合する。"""
    norm_name = normalize_name(name)
    for pref in prefs:
        exact = by_pref_norm.get((pref, norm_name))
        if exact:
            return exact
    for pref in prefs:
        prefix_matches = [
            f for norm, f in by_pref_all.get(pref, [])
            if norm.startswith(norm_name) or norm_name.startswith(norm)
        ]
        if len(prefix_matches) == 1:
            return prefix_matches
    return []


def apply_to_geojson(page_results: dict[str, list[tuple[str, str]]]) -> tuple[int, list[dict]]:
    geojson = json.loads(MICHINOEKI_PATH.read_text(encoding="utf-8"))
    features = geojson["features"]

    # (pref,正規化名) -> features / pref -> [(正規化名, feature), ...] の2種のインデックスを用意
    by_pref_norm: dict[tuple[str, str], list[dict]] = {}
    by_pref_all: dict[str, list[tuple[str, dict]]] = {}
    for f in features:
        pref = f["properties"]["pref"]
        norm = normalize_name(f["properties"]["name"])
        by_pref_norm.setdefault((pref, norm), []).append(f)
        by_pref_all.setdefault(pref, []).append((norm, f))

    matched = 0
    unmatched = []
    for slug, prefs in PAGE_GROUPS.items():
        for name, status in page_results.get(slug, []):
            candidates = find_candidates(name, prefs, by_pref_norm, by_pref_all)
            if not candidates:
                unmatched.append({"slug": slug, "prefs": prefs, "name": name, "status": status})
                continue
            for f in candidates:
                f["properties"]["kippu_available"] = is_available(status)
                f["properties"]["kippu_status"] = status
                matched += 1

    if ATTRIBUTION_KIPPU not in geojson["attribution"]:
        geojson["attribution"] = geojson["attribution"] + "<br>" + ATTRIBUTION_KIPPU
    MICHINOEKI_PATH.write_text(json.dumps(geojson, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return matched, unmatched


def main() -> None:
    page_results = fetch_all_entries()
    matched, unmatched = apply_to_geojson(page_results)
    UNMATCHED_PATH.write_text(json.dumps(unmatched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    total_listed = sum(len(v) for v in page_results.values())
    print(
        f"アプト側一覧{total_listed}件中{matched}件をmichinoeki.geojsonに反映しました。"
        f"未マッチ{len(unmatched)}件は{UNMATCHED_PATH}へ保存。"
    )


if __name__ == "__main__":
    main()
