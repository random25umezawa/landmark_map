"""国土地理院 地名検索APIによる住所→緯度経度のジオコーディングラッパー。

結果はJSONファイルにキャッシュし、同じ住所への再問い合わせを避ける。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

API_URL = "https://msearch.gsi.go.jp/address-search/AddressSearch"
CACHE_PATH = Path(__file__).resolve().parent / "geocode_cache.json"
REQUEST_INTERVAL_SEC = 0.5

_cache: dict[str, list[float] | None] = {}
_cache_loaded = False


def _load_cache() -> None:
    global _cache, _cache_loaded
    if _cache_loaded:
        return
    if CACHE_PATH.exists():
        _cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    _cache_loaded = True


def _save_cache() -> None:
    CACHE_PATH.write_text(json.dumps(_cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def geocode(address: str) -> list[float] | None:
    """住所文字列を [経度, 緯度] に変換する。見つからない場合はNone。"""
    _load_cache()
    address = address.strip()
    if not address:
        return None
    if address in _cache:
        return _cache[address]

    resp = requests.get(API_URL, params={"q": address}, timeout=20)
    resp.raise_for_status()
    results = resp.json()
    coords = results[0]["geometry"]["coordinates"] if results else None

    _cache[address] = coords
    _save_cache()
    time.sleep(REQUEST_INTERVAL_SEC)
    return coords


def load_overrides(path: Path) -> dict:
    """手動上書きファイル(JSON)を読み込む。存在しなければ空辞書。"""
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def resolve(key: str, address: str | None, overrides: dict) -> tuple[list[float] | None, str, str | None]:
    """手動上書き優先で座標を解決する。

    戻り値: (座標 or None, "manual"/"auto", 実際に使った住所)
    overrides[key] は {"lat":.., "lon":..} または {"address": "..."} の形式。
    """
    override = overrides.get(key)
    if override:
        if "lat" in override and "lon" in override:
            return [override["lon"], override["lat"]], "manual", override.get("address", address)
        if override.get("address"):
            coords = geocode(override["address"])
            if coords is not None:
                return coords, "manual", override["address"]

    if address:
        coords = geocode(address)
        if coords is not None:
            return coords, "auto", address

    return None, "auto", address
