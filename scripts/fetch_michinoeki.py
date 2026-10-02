"""道の駅データを取得しGeoJSON化する。

駅の一覧(どの駅が現在登録されているか)は国交省公式の登録駅一覧(list.xlsx)を正とし、
座標は次の優先順で決める。
  1. scripts/manual_overrides/michinoeki.json の手動指定(キーは "県名/駅名")
  2. 国土数値情報(KSJ) P35(2018年度版)の同名駅の座標
  3. 全国「道の駅」連絡会の公式ポータル(michi-no-eki.jp)の駅ページに埋め込まれた座標

KSJ P35は2018年度で更新が止まっており、それ以降の新駅・改称駅が含まれないため
3でそれを補う。ポータルはrobots.txtでCrawl-delay: 10が指定されているので、それに従い、
取得した駅ページの座標は scripts/michinoeki_portal_cache.json にキャッシュする。
KSJにしか存在しない駅(登録抹消済み)は出力しない。
座標が決まらなかった駅は data/michinoeki-unresolved.json に保存する。
"""
from __future__ import annotations

import io
import json
import re
import sys
import time
import unicodedata
import zipfile
from pathlib import Path

import openpyxl
import requests
from bs4 import BeautifulSoup

from geocode import load_overrides

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = ROOT / "data" / "michinoeki.geojson"
UNRESOLVED_PATH = ROOT / "data" / "michinoeki-unresolved.json"
OVERRIDES_PATH = Path(__file__).resolve().parent / "manual_overrides" / "michinoeki.json"
PORTAL_CACHE_PATH = Path(__file__).resolve().parent / "michinoeki_portal_cache.json"

LIST_URL = "https://www.mlit.go.jp/road/Michi-no-Eki/file/list.xlsx"
KSJ_URL = "https://nlftp.mlit.go.jp/ksj/gml/data/P35/P35-18/P35-18_GML.zip"
KSJ_MEMBER = "P35-18_GML/P35-18_Roadside_Station.geojson"
PORTAL_BASE = "https://www.michi-no-eki.jp"
PORTAL_INTERVAL_SEC = 10.0  # robots.txt の Crawl-delay に合わせる
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; landmark-map-research/1.0)"}

ATTRIBUTION = (
    "出典: 国土交通省「道の駅」登録駅一覧(https://www.mlit.go.jp/road/Michi-no-Eki/list.html)、"
    "国土交通省 国土数値情報 道の駅データ(P35, 2018年度)"
    "(https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-P35.html)、"
    "全国「道の駅」連絡会 公式ホームページ(https://www.michi-no-eki.jp/)を加工して作成"
)

# 都道府県名 -> 全国道の駅連絡会ポータルの一覧ページ番号(/stations/search/{番号}/all/all)
PORTAL_PREF_CODES = {
    "北海道": 10, "青森県": 11, "秋田県": 12, "岩手県": 13, "宮城県": 14, "山形県": 15,
    "福島県": 16, "茨城県": 17, "栃木県": 18, "群馬県": 19, "埼玉県": 20, "千葉県": 21,
    "東京都": 22, "神奈川県": 23, "新潟県": 24, "富山県": 25, "石川県": 26, "福井県": 27,
    "山梨県": 28, "長野県": 29, "岐阜県": 30, "静岡県": 31, "愛知県": 32, "三重県": 33,
    "滋賀県": 34, "京都府": 35, "大阪府": 36, "兵庫県": 37, "奈良県": 38, "和歌山県": 39,
    "鳥取県": 40, "島根県": 41, "岡山県": 42, "広島県": 43, "山口県": 44, "徳島県": 45,
    "香川県": 46, "愛媛県": 47, "高知県": 48, "福岡県": 49, "佐賀県": 50, "長崎県": 51,
    "熊本県": 52, "大分県": 53, "宮崎県": 54, "鹿児島県": 55, "沖縄県": 56,
}
PREF_ORDER = list(PORTAL_PREF_CODES)

# 表記ゆれ吸収用(fetch_michinoeki_kippu.py と同じ方針): 全半角統一(NFKC)、
# 波ダッシュ系の異体字統一、区切り記号・括弧類の除去
_WAVE_DASH_RE = re.compile(r"[〜～⁓~]")
_STRIP_CHARS_RE = re.compile(r"[\s・･,、，「」『』]")
_PORTAL_COORD_RE = re.compile(r"maps/embed/v1/place\?q=(-?[\d.]+),(-?[\d.]+)")


def normalize_name(name: str) -> str:
    n = unicodedata.normalize("NFKC", name)
    n = _WAVE_DASH_RE.sub("〜", n)
    n = _STRIP_CHARS_RE.sub("", n)
    return n.removeprefix("道の駅")  # ポータルには「道の駅きたごう」のように冠付きの表記がある


def http_get(url: str, timeout: int = 60) -> requests.Response:
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp


def fetch_official_list() -> list[dict]:
    """国交省の登録駅一覧(list.xlsx)を [{pref, name, round, registered, municipality, url}, ...] で返す。"""
    wb = openpyxl.load_workbook(io.BytesIO(http_get(LIST_URL).content), read_only=True)
    entries = []
    for row in list(wb.worksheets[0].iter_rows(values_only=True))[1:]:
        pref, name, round_, registered, municipality, url = (list(row) + [None] * 6)[:6]
        if not pref or not name:
            continue
        entries.append({
            "pref": str(pref).strip(),
            "name": str(name).strip().replace("　", " "),
            "round": str(round_ or "").strip(),
            "registered": str(registered or "").strip(),
            "municipality": str(municipality or "").strip(),
            "url": str(url).strip() if url else None,
        })
    return entries


def fetch_ksj_features() -> list[dict]:
    with zipfile.ZipFile(io.BytesIO(http_get(KSJ_URL).content)) as zf:
        with zf.open(KSJ_MEMBER) as f:
            return json.load(f)["features"]


def build_ksj_index(raw_features: list[dict]) -> dict[str, list[dict]]:
    """県名 -> [{norm, props, geometry}, ...]"""
    index: dict[str, list[dict]] = {}
    for raw in raw_features:
        p = raw["properties"]
        index.setdefault(p["P35_003"], []).append({
            "norm": normalize_name(p["P35_006"]),
            "municipality": p["P35_004"],
            "municipality_code": p["P35_005"],
            "urls": [u for u in (p.get(f"P35_{i:03d}") for i in range(7, 11)) if u],
            "geometry": raw["geometry"],
            "used": False,
        })
    return index


def match_ksj(entry: dict, ksj_index: dict[str, list[dict]]) -> tuple[dict | None, bool]:
    """同名(正規化後)→ 同一市区町村内で一方が他方を含む候補が1件だけ、の順で照合する。

    戻り値: (KSJ側の駅 or None, 完全一致か)
    後者は「しらぬか恋問」→「しらぬか恋問館」のような改称を拾うためのもの。改称は移転を
    伴うこともあるため、部分一致の座標はポータルで取れなかった場合の予備としてのみ使う。
    名称が全く変わった駅は照合しない。
    """
    candidates = [c for c in ksj_index.get(entry["pref"], []) if not c["used"]]
    norm = normalize_name(entry["name"])
    exact = [c for c in candidates if c["norm"] == norm]
    if len(exact) == 1:
        return exact[0], True
    muni = entry["municipality"]
    partial = [
        c for c in candidates
        if (c["norm"] in norm or norm in c["norm"])
        and muni and (c["municipality"].endswith(muni) or muni.endswith(c["municipality"]))
    ]
    if len(partial) == 1:
        return partial[0], False
    return None, False


class Portal:
    """全国「道の駅」連絡会ポータルから駅IDと座標を引く(Crawl-delay遵守・キャッシュ付き)。"""

    def __init__(self) -> None:
        self.cache: dict[str, list[float]] = (
            json.loads(PORTAL_CACHE_PATH.read_text(encoding="utf-8")) if PORTAL_CACHE_PATH.exists() else {}
        )
        self.listings: dict[str, list[tuple[str, str, str]]] = {}
        self._last_request = 0.0

    def _get(self, url: str) -> str:
        wait = PORTAL_INTERVAL_SEC - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        try:
            return http_get(url, timeout=30).text
        finally:
            self._last_request = time.monotonic()

    def listing(self, pref: str) -> list[tuple[str, str, str]]:
        """県の駅一覧 [(正規化名, 駅ID, 市区町村), ...](ページ送りを辿って全件)。"""
        if pref in self.listings:
            return self.listings[pref]
        code = PORTAL_PREF_CODES[pref]
        stations: list[tuple[str, str, str]] = []
        page = 0
        while True:
            html = self._get(f"{PORTAL_BASE}/stations/search/{code}/all/all?page={page}")
            soup = BeautifulSoup(html, "html.parser")
            found = 0
            for a in soup.select('a[href^="/stations/views/"]'):
                h3 = a.find("h3")
                if h3 is None:
                    continue
                txt = a.find("div", class_="txt")  # 例: "奈良県 奈良市"
                municipality = txt.get_text(strip=True).removeprefix(pref).strip() if txt else ""
                stations.append((normalize_name(h3.get_text(strip=True)), a["href"].rsplit("/", 1)[-1], municipality))
                found += 1
            if found == 0 or soup.select_one(f'a[href$="?page={page + 1}"]') is None:
                break
            page += 1
        print(f"  ポータル一覧 {pref}: {len(stations)}駅", file=sys.stderr)
        self.listings[pref] = stations
        return stations

    def find_station(self, pref: str, name: str) -> tuple[str, str] | None:
        """(駅ID, 市区町村) を返す。"""
        stations = self.listing(pref)
        norm = normalize_name(name)
        exact = [(sid, muni) for n, sid, muni in stations if n == norm]
        if len(exact) == 1:
            return exact[0]
        partial = [(sid, muni) for n, sid, muni in stations if n.startswith(norm) or norm.startswith(n)]
        return partial[0] if len(partial) == 1 else None

    def coords(self, station_id: str) -> list[float] | None:
        if station_id not in self.cache:
            html = self._get(f"{PORTAL_BASE}/stations/views/{station_id}")
            m = _PORTAL_COORD_RE.search(html)
            if m is None:
                return None
            lat, lon = float(m.group(1)), float(m.group(2))
            self.cache[station_id] = [lon, lat]
            PORTAL_CACHE_PATH.write_text(json.dumps(self.cache, indent=2) + "\n", encoding="utf-8")
        return self.cache[station_id]


def in_japan(coords: list[float]) -> bool:
    lon, lat = coords
    return 122 <= lon <= 154 and 20 <= lat <= 46


def main() -> None:
    # Windowsのコンソール(cp932)では駅名中の文字(�等)を出力できず落ちるため
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    entries = fetch_official_list()
    ksj_index = build_ksj_index(fetch_ksj_features())
    overrides = load_overrides(OVERRIDES_PATH)
    portal = Portal()
    print(f"国交省一覧: {len(entries)}駅", file=sys.stderr)

    features, unresolved = [], []
    counts = {"manual": 0, "ksj": 0, "portal": 0}
    for e in entries:
        key = f"{e['pref']}/{e['name']}"
        props = {
            "name": e["name"],
            "pref": e["pref"],
            "municipality": e["municipality"],
            "registered": f"{e['round']}({e['registered']})" if e["round"] else e["registered"],
            "urls": [],
        }
        geometry = None
        ksj, ksj_exact = match_ksj(e, ksj_index)
        if ksj is not None:
            ksj["used"] = True
            props["municipality"] = ksj["municipality"]
            props["municipality_code"] = ksj["municipality_code"]
            props["urls"] = ksj["urls"]

        override = overrides.get(key)
        if override and "lat" in override and "lon" in override:
            geometry = {"type": "Point", "coordinates": [override["lon"], override["lat"]]}
            props["coord_source"] = "manual"
            props["geocode_source"] = "manual"  # 地図上で金色の縁取り(他レイヤーと共通の仕組み)
            counts["manual"] += 1
        elif ksj is not None and ksj_exact:
            geometry = ksj["geometry"]
            props["coord_source"] = "ksj"
            counts["ksj"] += 1
        else:
            station = portal.find_station(e["pref"], e["name"])
            coords = portal.coords(station[0]) if station else None
            if coords is not None and in_japan(coords):
                geometry = {"type": "Point", "coordinates": coords}
                props["coord_source"] = "portal"
                props["urls"] = [f"{PORTAL_BASE}/stations/views/{station[0]}"]
                # 国交省一覧の所在地が県名だけの駅がある(例: クロスウェイなかまち)
                if props["municipality"] in ("", e["pref"]) and station[1]:
                    props["municipality"] = station[1]
                counts["portal"] += 1
            elif ksj is not None:
                geometry = ksj["geometry"]
                props["coord_source"] = "ksj"
                counts["ksj"] += 1

        if e["url"] and e["url"] not in props["urls"]:
            props["urls"].append(e["url"])
        if geometry is None:
            unresolved.append({"key": key, **e})
            continue
        features.append({"type": "Feature", "geometry": geometry, "properties": props})

    features.sort(key=lambda f: (
        PREF_ORDER.index(f["properties"]["pref"]) if f["properties"]["pref"] in PREF_ORDER else 99,
        f["properties"].get("municipality_code") or "99999",
        f["properties"]["name"],
    ))
    dropped = [c["norm"] for cs in ksj_index.values() for c in cs if not c["used"]]

    geojson = {"type": "FeatureCollection", "attribution": ATTRIBUTION, "features": features}
    OUTPUT_PATH.write_text(json.dumps(geojson, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    UNRESOLVED_PATH.write_text(json.dumps(unresolved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"{len(features)}駅を{OUTPUT_PATH}に出力しました"
        f"(KSJ座標 {counts['ksj']} / ポータル座標 {counts['portal']} / 手動 {counts['manual']})。"
        f"座標未解決{len(unresolved)}駅は{UNRESOLVED_PATH}へ保存。"
        f"KSJにのみ存在し一覧に無い(登録抹消・改称で照合不能){len(dropped)}件は除外: {dropped}"
    )


if __name__ == "__main__":
    main()
