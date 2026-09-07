"""マンホールカードデータを下水道広報プラットホーム(GKP)の検索ページから取得しGeoJSON化する。

都道府県ごとに配布実績の一覧表がサーバーサイドレンダリングされるため、
47都道府県分のページを順に取得してテーブルをパースする。
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup, Tag

sys.path.insert(0, str(Path(__file__).resolve().parent))
from geocode import geocode

SEARCH_URL = "https://www.gk-p.jp/mhcard/"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "manhole-card.geojson"
REQUEST_INTERVAL_SEC = 1.0

PREFECTURES = {
    "01": "北海道", "02": "青森県", "03": "岩手県", "04": "宮城県", "05": "秋田県",
    "06": "山形県", "07": "福島県", "08": "茨城県", "09": "栃木県", "10": "群馬県",
    "11": "埼玉県", "12": "千葉県", "13": "東京都", "14": "神奈川県", "15": "新潟県",
    "16": "富山県", "17": "石川県", "18": "福井県", "19": "山梨県", "20": "長野県",
    "21": "岐阜県", "22": "静岡県", "23": "愛知県", "24": "三重県", "25": "滋賀県",
    "26": "京都府", "27": "大阪府", "28": "兵庫県", "29": "奈良県", "30": "和歌山県",
    "31": "鳥取県", "32": "島根県", "33": "岡山県", "34": "広島県", "35": "山口県",
    "36": "徳島県", "37": "香川県", "38": "愛媛県", "39": "高知県", "40": "福岡県",
    "41": "佐賀県", "42": "長崎県", "43": "熊本県", "44": "大分県", "45": "宮崎県",
    "46": "鹿児島県", "47": "沖縄県",
}

NOISE_LINE_RE = re.compile(r"^(電話|ＴＥＬ|TEL|Tel|FAX|※|\(問合せ|（問合せ|問合せ先)")
PREF_NAMES = list(PREFECTURES.values())
MUNI_SUFFIX_RE = re.compile(r"[市区町村郡]")
# 「2階」のような階数表記だけの数字は住所の決め手にならないため、階数に直結しない数字を要求する
QUALIFYING_DIGIT_RE = re.compile(r"\d(?!\s*階)")


def _has_pref_name(line: str) -> bool:
    return any(p in line for p in PREF_NAMES)


def _looks_like_address(line: str) -> bool:
    return bool(MUNI_SUFFIX_RE.search(line)) and bool(QUALIFYING_DIGIT_RE.search(line))


def fetch_prefecture_html(pref_code: str) -> str:
    resp = requests.get(SEARCH_URL, params={"pref": pref_code}, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_distribution_cell(cell: Tag, pref_name: str) -> tuple[str | None, str | None, str | None]:
    """配布場所セルから (施設名, 住所, 施設URL) を抽出する。"""
    link = cell.find("a")
    facility_url = link["href"] if link and link.has_attr("href") else None

    lines = [line.strip() for line in cell.get_text(separator="\n").split("\n") if line.strip()]
    lines = [line for line in lines if not NOISE_LINE_RE.match(line)]
    if not lines:
        return None, None, facility_url

    facility_name = link.get_text(strip=True) if link else lines[0]
    other_lines = [line for line in lines if line != facility_name]

    # 都道府県の正式名称を含み、かつ番地らしい数字を伴う行を最優先で住所とみなす
    address = next((line for line in lines if _has_pref_name(line) and _looks_like_address(line)), None)
    if address is None:
        # 都道府県名が省略されている場合のフォールバック(ページの都道府県名を補う)
        address = next((line for line in other_lines if _looks_like_address(line)), None)
        if address and not _has_pref_name(address):
            address = f"{pref_name}{address}"

    if facility_name == address:
        facility_name = other_lines[0] if other_lines else None
    return facility_name, address, facility_url


def parse_table(html: str, pref_name: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    result_div = soup.find("div", id="mhcard_result")
    table = result_div.find_next("table") if result_div else None
    if table is None:
        return []

    rows = table.find("tbody").find_all("tr")[1:]  # 先頭はヘッダ行
    entries = []
    for tr in rows:
        cells = tr.find_all(["th", "td"])
        data_cells = cells[1:] if len(cells) == 8 else cells
        if len(data_cells) < 7:
            continue
        issuer_cell, _img_cell, round_cell, issued_cell, place_cell, _hours_cell, _stock_cell = data_cells[:7]

        issuer_lines = [line.strip() for line in issuer_cell.get_text(separator="\n").split("\n") if line.strip()]
        issuer = issuer_lines[0] if issuer_lines else None
        card_code = issuer_lines[1].strip("()（）") if len(issuer_lines) > 1 else None

        facility, address, facility_url = parse_distribution_cell(place_cell, pref_name)

        entries.append({
            "pref": pref_name,
            "issuer": issuer,
            "card_code": card_code,
            "round": round_cell.get_text(strip=True),
            "issued_date": issued_cell.get_text(strip=True),
            "facility": facility,
            "address": address,
            "facility_url": facility_url,
        })
    return entries


def fetch_all_entries() -> list[dict]:
    entries = []
    for code, name in PREFECTURES.items():
        html = fetch_prefecture_html(code)
        pref_entries = parse_table(html, name)
        print(f"{name}: {len(pref_entries)}件", file=sys.stderr)
        entries.extend(pref_entries)
        time.sleep(REQUEST_INTERVAL_SEC)
    return entries


def entries_to_features(entries: list[dict]) -> list[dict]:
    features = []
    for entry in entries:
        address = entry["address"]
        if not address:
            print(f"住所なしのためスキップ: {entry['pref']} {entry['issuer']}", file=sys.stderr)
            continue
        coords = geocode(address)
        if coords is None:
            print(f"ジオコーディング失敗: {entry['pref']} {entry['issuer']} / {address}", file=sys.stderr)
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": coords},
            "properties": {
                "issuer": entry["issuer"],
                "card_code": entry["card_code"],
                "pref": entry["pref"],
                "round": entry["round"],
                "issued_date": entry["issued_date"],
                "facility": entry["facility"],
                "address": address,
                "facility_url": entry["facility_url"],
            },
        })
    return features


def main() -> None:
    entries = fetch_all_entries()
    features = entries_to_features(entries)
    features.sort(key=lambda f: (f["properties"]["pref"], f["properties"]["issuer"] or ""))

    geojson = {
        "type": "FeatureCollection",
        "attribution": (
            "出典: 下水道広報プラットホーム(GKP) マンホールカード検索を加工して作成 "
            f"({SEARCH_URL})"
        ),
        "features": features,
    }
    OUTPUT_PATH.write_text(json.dumps(geojson, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(features)}件を{OUTPUT_PATH}に出力しました。(元データ{len(entries)}件)")


if __name__ == "__main__":
    main()
