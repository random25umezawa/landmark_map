"""道の駅の営業時間を全国「道の駅」連絡会の公式ポータル(michi-no-eki.jp)の駅ページから取得し、
data/michinoeki.geojson の各地点に付与する。

駅ページの「営業時間」欄は自由記述のため、原文を hours_text として保持したうえで、
旅程の絞り込みに使えるよう売店(物販)の開店・閉店時刻を hours として構造化する(parse_hours)。
きっぷ・カードの購入が主目的なので、レストラン等ではなく売店の時間を優先する。

ポータルはrobots.txtでCrawl-delay: 10が指定されているので、それに従う(全駅で初回3〜4時間)。
取得した駅ページは scripts/michinoeki_portal_cache.json にキャッシュされ、2回目以降は
未取得の駅だけを取りに行く。--no-fetch を付けるとキャッシュにある駅だけで反映する
(営業時間の解釈を調整したときの再反映用)。

fetch_michinoeki.py の実行後に走らせること。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from fetch_michinoeki import PORTAL_BASE, Portal, normalize_name
from michinoeki_hours_parser import parse_hours

ROOT = Path(__file__).resolve().parent.parent
MICHINOEKI_PATH = ROOT / "data" / "michinoeki.geojson"
UNMATCHED_PATH = ROOT / "data" / "michinoeki-hours-unmatched.json"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    fetch = "--no-fetch" not in sys.argv

    geojson = json.loads(MICHINOEKI_PATH.read_text(encoding="utf-8"))
    portal = Portal()
    ids_path = Path(__file__).resolve().parent / "michinoeki_portal_ids.json"
    # 駅名 -> ポータル駅ID の対応もキャッシュし、--no-fetch 時は一覧ページも取りに行かない
    ids: dict[str, str | None] = json.loads(ids_path.read_text(encoding="utf-8")) if ids_path.exists() else {}

    unmatched, counts = [], {"parsed": 0, "text_only": 0, "no_page": 0}
    for i, f in enumerate(geojson["features"]):
        p = f["properties"]
        key = f"{p['pref']}/{p['name']}"
        for k in ("portal_url", "hours_text", "hours", "hours_fetched"):
            p.pop(k, None)

        if key not in ids and fetch:
            station = portal.find_station(p["pref"], p["name"])
            if station is None:
                # 上り・下りで別ページになっている駅(例: "かつらぎ西(上り)" "かつらぎ西(下り)")は
                # 営業時間が同じなので先頭のページを使う
                norm = normalize_name(p["name"])
                sides = [sid for n, sid, _ in portal.listing(p["pref"]) if n.startswith(norm) and re.search(r"[上下]り|側", n)]
                station = (sides[0], "") if sides else None
            ids[key] = station[0] if station else None
            ids_path.write_text(json.dumps(ids, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        sid = ids.get(key)
        if sid is None:
            if key in ids:
                unmatched.append({"key": key, "reason": "ポータルの一覧に該当駅なし"})
            counts["no_page"] += 1
            continue

        cached = portal.cache.get(sid)
        if not (isinstance(cached, dict) and "info" in cached):
            if not fetch:
                counts["no_page"] += 1
                continue
            print(f"  [{i + 1}/{len(geojson['features'])}] {key}", file=sys.stderr)
        page = portal.page(sid)
        p["portal_url"] = f"{PORTAL_BASE}/stations/views/{sid}"
        text = page["info"].get("営業時間", "").strip()
        if not text:
            unmatched.append({"key": key, "reason": "営業時間欄なし", "portal_url": p["portal_url"]})
            continue
        p["hours_text"] = text
        p["hours_fetched"] = page["fetched"]
        hours = parse_hours(text)
        if hours:
            p["hours"] = hours
            counts["parsed"] += 1
        else:
            counts["text_only"] += 1

    MICHINOEKI_PATH.write_text(json.dumps(geojson, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    UNMATCHED_PATH.write_text(json.dumps(unmatched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"営業時間を反映: 時刻まで解釈 {counts['parsed']}駅 / 原文のみ {counts['text_only']}駅 / "
        f"ポータル未取得・照合不能 {counts['no_page']}駅。照合できなかった駅等は{UNMATCHED_PATH}へ保存。"
    )


if __name__ == "__main__":
    main()
