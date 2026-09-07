"""到達証明書データを手動入力(scripts/manual_overrides/tochoshomeisho.json)からGeoJSON化する。

到達証明書(地理的極点・岬・離島・峠・低山などで訪問記念に発行される証明書)を
全国横断的に一覧化した公式データベースは存在しないため、他の要素のような自動取得は
行わない。scripts/manual_overrides/tochoshomeisho.json に見つけた分を随時追記していく
運用とする。各エントリは {"lat":.., "lon":..} で直接座標を指定するか、
{"address": "住所"} で国土地理院ジオコーディングAPIに解決させる。

自治体・観光協会等の一次情報で確認できたものは confidence: "official"、
まとめブログ等の二次情報のみで一次情報未確認のものは confidence: "unconfirmed" とする。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from geocode import geocode

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "tochoshomeisho.geojson"
SOURCE_PATH = Path(__file__).resolve().parent / "manual_overrides" / "tochoshomeisho.json"


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
            "issuer": entry.get("issuer"),
            "confidence": entry.get("confidence", "unconfirmed"),
            "note": entry.get("note"),
            "url": entry.get("source_url"),
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
        "attribution": "出典: 各発行元(自治体・観光協会等)公式情報および有志まとめサイトを参考に個人で確認・入力(scripts/manual_overrides/tochoshomeisho.json)。confidence=unconfirmedは一次情報未確認",
        "features": features,
    }
    OUTPUT_PATH.write_text(json.dumps(geojson, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    official = sum(1 for f in features if f["properties"]["confidence"] == "official")
    unconfirmed = len(features) - official
    print(f"{len(features)}件を{OUTPUT_PATH}に出力しました(official: {official} / unconfirmed: {unconfirmed})。")


if __name__ == "__main__":
    main()
