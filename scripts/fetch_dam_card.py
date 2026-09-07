"""ダムカードデータを国土交通省水管理・国土保全局の配布場所一覧から取得しGeoJSON化する。

一覧ページから最新のXLSXへのリンクを動的に取得するため、掲載ファイル名が
更新されても本スクリプトの変更は不要。配布場所住所には①②③...で複数拠点が
併記されている行があり、それぞれ別地点としてジオコーディングする。
"""
from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

import openpyxl
import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from geocode import load_overrides, resolve

LIST_PAGE_URL = "https://www.mlit.go.jp/river/kankyo/campaign/shunnkan/damcard.html"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "dam-card.geojson"
UNRESOLVED_PATH = Path(__file__).resolve().parent.parent / "data" / "dam-card-unresolved.json"
OVERRIDES_PATH = Path(__file__).resolve().parent / "manual_overrides" / "dam_card.json"
CIRCLED_DIGITS = "①②③④⑤⑥⑦⑧⑨⑩"
MARKER_RE = re.compile(f"[{CIRCLED_DIGITS}]")
PREF_NAMES = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県", "茨城県", "栃木県", "群馬県",
    "埼玉県", "千葉県", "東京都", "神奈川県", "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県",
    "岐阜県", "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
    "鳥取県", "島根県", "岡山県", "広島県", "山口県", "徳島県", "香川県", "愛媛県", "高知県", "福岡県",
    "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
]


def find_latest_xlsx_url() -> str:
    resp = requests.get(LIST_PAGE_URL, timeout=30)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    soup = BeautifulSoup(resp.text, "html.parser")
    for a in soup.find_all("a", href=re.compile(r"\.xlsx$")):
        if "最新情報" in a.parent.get_text():
            return requests.compat.urljoin(LIST_PAGE_URL, a["href"])
    raise RuntimeError("最新のXLSXリンクが見つかりませんでした")


def split_by_marker(text: str | None) -> dict[str | None, str]:
    """①②③...で区切られたテキストを {マーカー: 本文} に分割する。マーカーがなければ {None: text}。"""
    if not text or text.strip() in ("", "－", "-"):
        return {}
    text = text.strip()
    if not MARKER_RE.search(text):
        return {None: text}
    markers = MARKER_RE.findall(text)
    chunks = MARKER_RE.split(text)[1:]
    return {m: c.strip() for m, c in zip(markers, chunks) if c.strip()}


def clean_pref(pref_raw: str, marker: str | None) -> str:
    """ダム所在県名を整形する。①②...で複数県が併記されている行は該当マーカーの県名のみを返す。"""
    marker_map = split_by_marker(pref_raw)
    if marker and marker in marker_map:
        return marker_map[marker].strip()
    if list(marker_map.keys()) == [None]:
        # マーカーはないが改行で複数県が並記されているケース(例: "広島県\n山口県")
        parts = [p.strip() for p in marker_map[None].split("\n") if p.strip()]
        return "/".join(parts)
    if marker_map:
        return "/".join(v.strip() for v in marker_map.values())
    return pref_raw.strip()


def fetch_rows() -> list[tuple]:
    xlsx_url = find_latest_xlsx_url()
    resp = requests.get(xlsx_url, timeout=60)
    resp.raise_for_status()
    wb = openpyxl.load_workbook(io.BytesIO(resp.content), data_only=True)
    ws = wb.worksheets[0]
    return [row for row in ws.iter_rows(values_only=True) if isinstance(row[0], int)]


def rows_to_features(rows: list[tuple], overrides: dict) -> tuple[list[dict], list[dict]]:
    features = []
    unresolved = []
    for row in rows:
        _, river_system, river, dam_name, ver, place, hours, pref, address_raw, url, _ = row
        addresses = split_by_marker(address_raw) or {None: None}

        for marker, address in addresses.items():
            row_pref = clean_pref(pref, marker)
            # 配布場所がダム所在県と異なる県にある場合、住所側に別の都道府県名が
            # 既に含まれていることがあるため、その場合はダム所在県を重複付与しない
            if address is None:
                full_address = None
            else:
                has_pref_prefix = any(address.startswith(p) for p in PREF_NAMES)
                full_address = address if has_pref_prefix else f"{row_pref}{address}"

            key = f"{dam_name}#{marker}" if marker else dam_name
            coords, source, used_address = resolve(key, full_address, overrides)

            if coords is None:
                reason = "no_address" if not full_address else "geocode_failed"
                if reason == "no_address":
                    print(f"住所なしのためスキップ: {dam_name}", file=sys.stderr)
                else:
                    print(f"ジオコーディング失敗: {dam_name} / {used_address}", file=sys.stderr)
                unresolved.append({
                    "key": key, "reason": reason, "name": dam_name, "location_marker": marker,
                    "pref": row_pref, "river_system": river_system, "river": river, "card_ver": str(ver),
                    "facility": place, "hours": hours, "raw_address": full_address, "url": url,
                })
                continue

            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": coords},
                "properties": {
                    "name": dam_name,
                    "location_marker": marker,
                    "pref": row_pref,
                    "river_system": river_system,
                    "river": river,
                    "card_ver": str(ver),
                    "facility": place,
                    "hours": hours,
                    "address": used_address,
                    "url": url,
                    "geocode_source": source,
                },
            })
    return features, unresolved


def main() -> None:
    overrides = load_overrides(OVERRIDES_PATH)
    rows = fetch_rows()
    features, unresolved = rows_to_features(rows, overrides)
    features.sort(key=lambda f: (f["properties"]["pref"], f["properties"]["name"]))

    geojson = {
        "type": "FeatureCollection",
        "attribution": (
            "出典: 国土交通省 水管理・国土保全局 ダムカード配布場所一覧を加工して作成 "
            f"({LIST_PAGE_URL})"
        ),
        "features": features,
    }
    OUTPUT_PATH.write_text(json.dumps(geojson, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    UNRESOLVED_PATH.write_text(json.dumps(unresolved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(features)}件を{OUTPUT_PATH}に出力しました。(元データ{len(rows)}ダム、未解決{len(unresolved)}件は{UNRESOLVED_PATH}へ)")


if __name__ == "__main__":
    main()
