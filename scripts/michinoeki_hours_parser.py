"""道の駅の営業時間(自由記述)から売店の開店・閉店時刻を取り出す。

全国「道の駅」連絡会ポータルの「営業時間」欄は駅ごとに書き方が違う。例:
  "9:00～18:00(4～9月) 9:00～17:00(10～3月)"                 季節別
  "5月～9月 9:00～18:00 10月～4月 9:00～17:00"                 季節が前置き
  "9:00～18:00(11月～2月は9:00～17:00)"                       基本+例外
  "9:30～19:00 (11～3月は17:00まで、…)"                         閉店時刻だけの例外
  "売店 9:00～17:00 レストラン 11:00～16:00 休館日 毎週水曜日"   施設別
きっぷ・カードの購入が主目的なので、施設別の記載があれば売店(物販)の時間を優先する。

戻り値は [{"o": "09:00", "c": "18:00", "m": [4, 5, ...]}, ...]。
m(該当月)が無い要素は「その他の月」の時間。曜日によって時間が違うなど、
旅程の判断に使える形に解釈できない場合は None を返す(原文はそのままポップアップに出す)。
"""
from __future__ import annotations

import re
import unicodedata

# 施設名の見出し。売店系は優先順に並べる
SHOP_LABELS = ["売店", "物販", "特産品販売所", "特産品", "物産館", "物産", "ショップ", "道の駅グッズ販売", "グッズ販売",
               "販売所", "直売", "産直"]
# 売店の記載も先頭の時間も無い場合に、代わりに採ってよくない(売店とは時間が大きく違いがちな)施設
NON_SHOP_LABELS = {"レストラン", "食堂", "フードコート", "テイクアウト", "カフェ", "温泉", "浴場", "トイレ", "駐車場",
                   "ドッグラン", "ラストオーダー", "LO", "テナント"}
OTHER_LABELS = ["レストラン", "食堂", "フードコート", "テイクアウト", "情報プラザ", "情報コーナー", "観光案内所", "案内所",
                "本館", "トイレ", "駐車場", "ドッグラン", "温泉", "浴場", "テナント", "カフェ", "ラストオーダー", "LO",
                "休館日", "定休日", "休:", "休 :", "一部店舗", "館内各店舗", "施設・時期"]
_LABEL_RE = re.compile("|".join(re.escape(l) for l in sorted(SHOP_LABELS + OTHER_LABELS, key=len, reverse=True)))

_TIME = r"(\d{1,2}):(\d{2})"
_DASH = r"\s*[～~〜\-−–‐ー]\s*"
_RANGE_RE = re.compile(_TIME + _DASH + _TIME)
_UNTIL_RE = re.compile(_TIME + r"\s*(?:[(（〔][^)）〕]*[)）〕])?\s*まで")  # "19:00(夏季)まで" も含む
# 曜日別の記載(平日と土日祝で時間が違う等)
_WEEKDAY_RE = re.compile(r"[月火水木金土日][～~〜\-]\s*[月火水木金土日]|(?<!翌)平日|土日|土・日|(?<![祝定])休日")


def _normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", text)
    t = t.replace("::", ":")  # "9::00" のような誤記
    t = re.sub(r"午後\s*(\d{1,2})時", lambda m: f"{int(m.group(1)) % 12 + 12}時", t)
    t = t.replace("午前", "")
    t = re.sub(r"(\d{1,2})時半", r"\1:30", t)
    t = re.sub(r"(\d{1,2})時(\d{1,2})分", lambda m: f"{m.group(1)}:{int(m.group(2)):02d}", t)
    t = re.sub(r"(\d{1,2})時", r"\1:00", t)
    t = re.sub(r"(\d{1,2}:\d{2})\s*から\s*(\d{1,2}:\d{2})", r"\1～\2", t)  # "9:00から17:00"
    t = re.sub(r"(?<![\d:/])(\d{1,2})(?=\s*[～~〜]\s*\d{1,2}:\d{2})", r"\1:00", t)  # "9~17時" -> "9:00~17:00"
    t = re.sub(r"([～~〜\-]\s*\d{1,2})\.(\d{2})", r"\1:\2", t)  # "9:00～18.00"
    return t


def _hm(h: str, m: str) -> str:
    return f"{int(h):02d}:{m}"


def _point_month(month: str, part: str | None, day: str | None, is_start: bool) -> int:
    """上旬・中旬・下旬や日付付きの指定を月単位に丸める(その月の大半が含まれるかで判断)。"""
    m = int(month)
    if day is not None:
        d = int(day)
        part = "上旬" if d <= 10 else "中旬" if d <= 20 else "下旬"
    if is_start and part == "下旬":
        return m % 12 + 1
    if not is_start and part == "上旬":
        return (m - 2) % 12 + 1
    return m


def _months_from_range(m1: int, m2: int) -> list[int]:
    months = [m1]
    while months[-1] != m2 and len(months) < 12:
        months.append(months[-1] % 12 + 1)
    return months


def parse_months(spec: str) -> list[int] | None:
    """"4～9月" "3～5月、9～11月" "11/1-3/31" "4月下旬～10/31" "4～6,10月" 等を月のリストにする。"""
    spec = spec.replace("・", ",").replace("、", ",")
    months: list[int] = []
    for part in re.split(r"[,]", spec):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d{1,2})(?:月(上旬|中旬|下旬)?|/(\d{1,2}))?" + _DASH + r"(\d{1,2})(?:月(上旬|中旬|下旬)?|/(\d{1,2}))?月?", part)
        if m:
            a = _point_month(m.group(1), m.group(2), m.group(3), True)
            b = _point_month(m.group(4), m.group(5), m.group(6), False)
            months += _months_from_range(a, b)
            continue
        m = re.fullmatch(r"(\d{1,2})月?(上旬|中旬|下旬)?", part)
        if m:
            months.append(int(m.group(1)))
            continue
        return None
    months = [m for m in months if 1 <= m <= 12]
    return sorted(set(months)) or None


_PAREN_MONTHS_RE = re.compile(r"^\s*[(（〔【]([^)）〕】]*?)(?:は|のみ)?[)）〕】]")
_PREFIX_MONTHS_RE = re.compile(r"[【\[]?([\d月/上中下旬～~〜\-−–,、・\s]+?月?[上中下]?旬?)[】\]]?\s*[:：]?\s*$")
# 括弧内の例外。"11月～2月は9:00～17:00" "11～3月は17:00まで" "11月〜2月 閉店17:00"
_INNER_EXCEPTION_RE = re.compile(
    r"([\d月/上中下旬～~〜\-−–,、・]+?月?)(?:は|\s*閉店)\s*" + _TIME + r"(?:" + _DASH + _TIME + r"|\s*まで)?"
)
_BRACKET_RE = re.compile(r"[(（〔『\[]([^)）〕』\]]*)[)）〕』\]]?")


def _segment_for_shop(text: str) -> str:
    """施設別の記載があれば売店の部分、無ければ先頭(施設名より前)の部分を返す。"""
    labels = list(_LABEL_RE.finditer(text))
    if not labels:
        return text
    segments = [("", text[: labels[0].start()])]
    for i, m in enumerate(labels):
        end = labels[i + 1].start() if i + 1 < len(labels) else len(text)
        segments.append((m.group(0), text[m.end():end]))
    for label in SHOP_LABELS:
        for name, seg in segments:
            if name == label and (_RANGE_RE.search(seg) or _UNTIL_RE.search(seg)):
                if not _RANGE_RE.search(seg):
                    # "売店は19:00まで" のような閉店時刻だけの記載: 先頭の開店時刻と組み合わせる
                    head = _RANGE_RE.search(segments[0][1])
                    until = _UNTIL_RE.search(seg)
                    if head is None:
                        return ""
                    return f"{head.group(1)}:{head.group(2)}～{until.group(1)}:{until.group(2)}"
                return seg
    if _RANGE_RE.search(segments[0][1]):
        return segments[0][1]
    # 例: "情報プラザ棟:9:00-18:00 …" のように先頭から施設別で、売店の記載が無い
    for name, seg in segments[1:]:
        if name not in NON_SHOP_LABELS and _RANGE_RE.search(seg):
            return seg
    return ""


def parse_hours(text: str) -> list[dict] | None:
    t = _normalize(text)
    seg = _segment_for_shop(t)
    by_weekday = bool(_WEEKDAY_RE.search(seg))
    ranges = list(_RANGE_RE.finditer(seg))
    if not ranges:
        return None

    result: list[dict] = []
    prev_end = 0
    consumed_until = -1  # 括弧内の例外として処理済みの範囲
    for r in ranges:
        if r.start() < consumed_until:
            continue
        entry = {"o": _hm(r.group(1), r.group(2)), "c": _hm(r.group(3), r.group(4))}
        after = seg[r.end():]
        before = seg[prev_end:r.start()]
        months = None
        pm = _PAREN_MONTHS_RE.match(after)
        if pm and re.search(r"\d", pm.group(1)) and "は" not in pm.group(1):
            months = parse_months(pm.group(1))
        if months is None:
            bm = _PREFIX_MONTHS_RE.search(before)
            if bm and re.search(r"\d", bm.group(1)):
                months = parse_months(bm.group(1).strip())
        if months is not None:
            entry["m"] = months
        result.append(entry)
        prev_end = r.end()

        # 直後の括弧内の例外(次の時刻範囲が括弧の外に現れるまで)
        # "9:00～18:00(11月～2月は9:00～17:00)" "9:30～19:00(11～3月は17:00まで)"
        # "9:00～19:00(施設により異なる)〔10月～3月は18:00まで〕"
        pos = 0
        for b in _BRACKET_RE.finditer(after):
            if _RANGE_RE.search(after[pos:b.start()]):
                break
            pos = b.end()
            for ex in _INNER_EXCEPTION_RE.finditer(b.group(1)):
                ex_months = parse_months(ex.group(1))
                if ex_months is None:
                    continue
                if ex.group(4):
                    result.append({"o": _hm(ex.group(2), ex.group(3)), "c": _hm(ex.group(4), ex.group(5)), "m": ex_months})
                else:
                    result.append({"o": entry["o"], "c": _hm(ex.group(2), ex.group(3)), "m": ex_months})
                consumed_until = r.end() + pos  # 例外で使った時刻範囲を二重に拾わない
                prev_end = consumed_until

    defaults = [e for e in result if "m" not in e]
    if by_weekday:
        # 平日と土日祝で時間が違う等: 月別の指定も絡むものは解釈しない。そうでなければ
        # どの曜日でも営業している時間帯(最も遅い開店~最も早い閉店)を採る(旅程の判断で安全側)
        if len(defaults) != len(result):
            return None
        o, c = max(e["o"] for e in result), min(e["c"] for e in result)
        return [{"o": o, "c": c}] if o < c else None

    # 月指定の無い要素は「その他の月」。月指定付きの要素だけの場合はそのまま
    if len(defaults) > 1:
        # 月の指定の無い時間帯が複数(解釈できない書き方)なら先頭だけを採る
        result = [e for e in result if "m" in e] + defaults[:1]
    return result
