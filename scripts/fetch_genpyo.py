"""道路元標データを手動入力(scripts/manual_overrides/genpyo.json)からGeoJSON化する。

道路元標は全国横断的な公式データが存在しないため、他の要素のような自動取得は行わない。
訪問の都度 scripts/manual_overrides/genpyo.json にエントリを追記していく「個人ログ型」
レイヤーとして運用する。各エントリは {"lat":.., "lon":..} で直接座標を指定するか、
{"address": "住所"} で国土地理院ジオコーディングAPIに解決させる。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from geocode import geocode

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "genpyo.geojson"
SOURCE_PATH = Path(__file__).resolve().parent / "manual_overrides" / "genpyo.json"


def load_entries() -> dict:
    if not SOURCE_PATH.exists():
        return {}
    return json.loads(SOURCE_PATH.read_text(encoding="utf-8"))


def entry_to_feature(name: str, entry: dict) -> dict | None:
    if "lat" in entry and "lon" in entry:
        coords = [entry["lon"], entry["lat"]]
    elif entry.get("address"):
        coords = geocode(entry["address"])
        if coords is None:
            print(f"ジオコーディング失敗: {name} / {entry['address']}", file=sys.stderr)
            return None
    else:
        print(f"座標も住所もありません: {name}", file=sys.stderr)
        return None

    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": coords},
        "properties": {
            "name": name,
            "pref": entry.get("pref"),
            "address": entry.get("address"),
            "note": entry.get("note"),
            "source_url": entry.get("source_url"),
            "visited_date": entry.get("visited_date"),
        },
    }


def main() -> None:
    entries = load_entries()
    features = []
    for name, entry in entries.items():
        feature = entry_to_feature(name, entry)
        if feature:
            features.append(feature)
    features.sort(key=lambda f: (f["properties"].get("pref") or "", f["properties"]["name"]))

    geojson = {
        "type": "FeatureCollection",
        "attribution": "出典: 個人で確認・入力した道路元標情報(scripts/manual_overrides/genpyo.json)",
        "features": features,
    }
    OUTPUT_PATH.write_text(json.dumps(geojson, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(features)}件を{OUTPUT_PATH}に出力しました。")


if __name__ == "__main__":
    main()
