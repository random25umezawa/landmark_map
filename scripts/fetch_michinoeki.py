"""道の駅データを国土数値情報(KSJ) P35から取得しGeoJSON化する。"""
import io
import json
import zipfile
from pathlib import Path

import requests

SOURCE_URL = "https://nlftp.mlit.go.jp/ksj/gml/data/P35/P35-18/P35-18_GML.zip"
GEOJSON_MEMBER = "P35-18_GML/P35-18_Roadside_Station.geojson"
ATTRIBUTION = (
    "出典: 国土交通省 国土数値情報 道の駅データ(P35, 2018年度)を加工して作成 "
    "(https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-P35.html)"
)
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "michinoeki.geojson"


def fetch_raw_features() -> list[dict]:
    resp = requests.get(SOURCE_URL, timeout=60)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        with zf.open(GEOJSON_MEMBER) as f:
            return json.load(f)["features"]


def to_feature(raw: dict) -> dict:
    props = raw["properties"]
    urls = [props.get(f"P35_{i:03d}") for i in range(7, 11)]
    return {
        "type": "Feature",
        "geometry": raw["geometry"],
        "properties": {
            "name": props["P35_006"],
            "pref": props["P35_003"],
            "municipality": props["P35_004"],
            "municipality_code": props["P35_005"],
            "urls": [u for u in urls if u],
        },
    }


def main() -> None:
    raw_features = fetch_raw_features()
    features = [to_feature(r) for r in raw_features]
    features.sort(key=lambda f: (f["properties"]["municipality_code"], f["properties"]["name"]))

    geojson = {
        "type": "FeatureCollection",
        "attribution": ATTRIBUTION,
        "features": features,
    }
    OUTPUT_PATH.write_text(json.dumps(geojson, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(features)}件を{OUTPUT_PATH}に出力しました。")


if __name__ == "__main__":
    main()
