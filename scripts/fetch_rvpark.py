"""RVパークデータを「くるま旅」公式サイト(日本RV協会)から取得しGeoJSON化する。

一覧ページ(list.php)に全認定施設の名称・住所・電話番号が一括掲載されているため、
まずそこから基本情報とIDを取得する。座標は各施設の詳細ページに埋め込まれたJS変数
(var lat=/var lon=)から直接取得でき、ジオコーディングより高精度・低コストになる。
料金・利用可能期間・チェックイン アウト・駐車可能車両サイズ・設備アイコン(電源/水道/
トイレ/ダンプステーション/Wi-Fi/ペット等)も詳細ページから取得する。
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
from geocode import load_overrides, resolve

LIST_URL = "https://www.kurumatabi.com/rvpark/list.php"
DETAIL_URL_TMPL = "https://www.kurumatabi.com/park/rvpark/{id}.html"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "rvpark.geojson"
UNRESOLVED_PATH = Path(__file__).resolve().parent.parent / "data" / "rvpark-unresolved.json"
OVERRIDES_PATH = Path(__file__).resolve().parent / "manual_overrides" / "rvpark.json"
REQUEST_INTERVAL_SEC = 1.0

PREF_NAMES = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県", "茨城県", "栃木県", "群馬県",
    "埼玉県", "千葉県", "東京都", "神奈川県", "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県",
    "岐阜県", "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
    "鳥取県", "島根県", "岡山県", "広島県", "山口県", "徳島県", "香川県", "愛媛県", "高知県", "福岡県",
    "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
]

LAT_RE = re.compile(r"var lat\s*=\s*'([\-\d.]+)'")
LON_RE = re.compile(r"var lon\s*=\s*'([\-\d.]+)'")


def clean_text(tag: Tag | None) -> str | None:
    if tag is None:
        return None
    text = re.sub(r"\s+", " ", tag.get_text(separator=" ", strip=True)).strip()
    return text or None


def derive_pref(address: str | None) -> str | None:
    if not address:
        return None
    text = re.sub(r"^〒?\d{3}-?\d{4}\s*", "", address)
    for p in PREF_NAMES:
        if text.startswith(p):
            return p
    return None


def fetch_list() -> list[dict]:
    resp = requests.get(LIST_URL, timeout=30)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    soup = BeautifulSoup(resp.text, "html.parser")

    entries = []
    seen_ids = set()
    for dt in soup.select("div.areaBox dl dt"):
        link = dt.find("a")
        if not link or not link.has_attr("href"):
            continue
        m = re.search(r"/park/rvpark/(\d+)\.html", link["href"])
        if not m:
            continue
        park_id = m.group(1)
        if park_id in seen_ids:
            continue
        seen_ids.add(park_id)

        name = link.get_text(strip=True)
        dd = dt.find_next_sibling("dd")
        address = None
        phone = None
        if dd:
            for p in dd.find_all("p"):
                classes = p.get("class") or []
                if "telText" in classes:
                    a = p.find("a")
                    phone = clean_text(a) if a else clean_text(p)
                elif address is None:
                    text = clean_text(p)
                    if text:
                        address = text
        entries.append({"id": park_id, "name": name, "address": address, "phone": phone})
    return entries


def find_dd_by_label(soup: BeautifulSoup, label: str) -> Tag | None:
    for dt in soup.find_all("dt"):
        if dt.get_text(strip=True) == label:
            dd = dt.find_next_sibling("dd")
            if dd:
                return dd
    return None


def extract_fee(soup: BeautifulSoup) -> str | None:
    dd = find_dd_by_label(soup, "利用料金")
    if dd is None:
        return None
    items = dd.select("ul.fee li")
    if items:
        parts = []
        for li in items:
            spans = li.find_all("span")
            if len(spans) >= 2:
                parts.append(f"{clean_text(spans[0])}: {clean_text(spans[1])}")
            else:
                text = clean_text(li)
                if text:
                    parts.append(text)
        text = " / ".join(parts)
        if text:
            return text
    return clean_text(dd)


def extract_checkin_checkout(soup: BeautifulSoup) -> str | None:
    dd = find_dd_by_label(soup, "チェックイン・チェックアウト")
    if dd is None:
        return None
    items = dd.select("ul.inOut li")
    parts = []
    for li in items:
        spans = li.find_all("span")
        if len(spans) >= 2:
            parts.append(f"{clean_text(spans[0])}: {clean_text(spans[1])}")
    if parts:
        return " / ".join(parts)
    return clean_text(dd)


def extract_features(soup: BeautifulSoup) -> list[str]:
    return [img["alt"].strip() for img in soup.select("ul.icons img") if img.get("alt")]


def extract_coords(html: str) -> list[float] | None:
    lat_m = LAT_RE.search(html)
    lon_m = LON_RE.search(html)
    if not lat_m or not lon_m:
        return None
    try:
        lat, lon = float(lat_m.group(1)), float(lon_m.group(1))
    except ValueError:
        return None
    if lat == 0.0 and lon == 0.0:
        return None
    return [lon, lat]


def fetch_detail(park_id: str) -> dict:
    url = DETAIL_URL_TMPL.format(id=park_id)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    html = resp.text
    soup = BeautifulSoup(html, "html.parser")
    return {
        "coords": extract_coords(html),
        "fee": extract_fee(soup),
        "available_period": clean_text(find_dd_by_label(soup, "利用可能期間")),
        "checkin_checkout": extract_checkin_checkout(soup),
        "vehicle_size": clean_text(find_dd_by_label(soup, "駐車可能車両サイズ")),
        "features": extract_features(soup),
        "url": url,
    }


def main() -> None:
    overrides = load_overrides(OVERRIDES_PATH)
    list_entries = fetch_list()
    print(f"一覧から{len(list_entries)}件取得", file=sys.stderr)

    features = []
    unresolved = []
    for i, entry in enumerate(list_entries, 1):
        detail = fetch_detail(entry["id"])
        time.sleep(REQUEST_INTERVAL_SEC)

        pref = derive_pref(entry["address"])
        key = f"rvpark-{entry['id']}"
        override = overrides.get(key)
        if override and "lat" in override and "lon" in override:
            # 明示的な上書き指定は、サイト側の座標抽出に成功していても優先する
            # (例: サイト側データの緯度経度入力ミスを訂正するケース)
            coords = [override["lon"], override["lat"]]
            source = "manual"
            used_address = override.get("address", entry["address"])
        elif detail["coords"] is not None:
            coords, source, used_address = detail["coords"], "auto", entry["address"]
        else:
            coords, source, used_address = resolve(key, entry["address"], overrides)

        if coords is None:
            print(f"座標取得失敗: {entry['name']}", file=sys.stderr)
            unresolved.append({
                "key": key, "reason": "no_coords", "name": entry["name"], "pref": pref,
                "address": entry["address"], "phone": entry["phone"], "detail_url": detail["url"],
            })
            continue

        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": coords},
            "properties": {
                "name": entry["name"],
                "pref": pref,
                "address": used_address,
                "phone": entry["phone"],
                "fee": detail["fee"],
                "available_period": detail["available_period"],
                "checkin_checkout": detail["checkin_checkout"],
                "vehicle_size": detail["vehicle_size"],
                "features": detail["features"],
                "url": detail["url"],
                "geocode_source": source,
            },
        })
        if i % 50 == 0:
            print(f"{i}/{len(list_entries)}件処理済み", file=sys.stderr)

    features.sort(key=lambda f: (f["properties"]["pref"] or "", f["properties"]["name"]))

    geojson = {
        "type": "FeatureCollection",
        "attribution": (
            "出典: 一般社団法人日本RV協会「くるま旅」公式サイト RVパーク一覧を加工して作成 "
            f"({LIST_URL})"
        ),
        "features": features,
    }
    OUTPUT_PATH.write_text(json.dumps(geojson, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    UNRESOLVED_PATH.write_text(json.dumps(unresolved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(features)}件を{OUTPUT_PATH}に出力しました。(元データ{len(list_entries)}件、未解決{len(unresolved)}件)")


if __name__ == "__main__":
    main()
