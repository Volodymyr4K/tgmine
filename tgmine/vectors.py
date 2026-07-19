"""Витяг векторів руху з тексту: звідки -> куди.

Монітори прямо пишуть напрямок: «Группа БПЛА от Белгородской области далее в
направлении Курская область». Це готові ребра маршруту — набагато надійніше,
ніж здогадуватись про рух із того, що дві області згадані поруч у часі.

Розбір: знаходимо маркер напрямку, місця ЛІВОРУЧ від нього = звідки,
ПРАВОРУЧ = куди. Обидва кінці геокодуються окремо.
"""
from __future__ import annotations

import re

# маркер, після якого йде ціль руху
TO_MARK = re.compile(
    r"\b(?:в\s+направлени\w+|в\s+сторону|далее\s+на|курс\w*\s+на|"
    r"далее\s+в\s+направлени\w+|направление\s+на)\b", re.I)
# явне джерело
FROM_MARK = re.compile(r"\b(?:от|из)\s+(?=[А-ЯЁ])", re.I)
# «X и далее Y» — межа без слова «направление»
DALEE = re.compile(r"\b(?:и\s+)?далее\b", re.I)

PLACE = re.compile(r"\b[А-ЯЁ][а-яё]+(?:[- ][А-ЯЁ][а-яё]+)?")
STOP = {"группа", "группы", "много", "еще", "ещё", "опасность", "тревога",
        "отбой", "фиксация", "фиксации", "бпла", "внимание", "работа",
        "меры", "безопасности", "предосторожности", "область", "районе",
        "примерно", "также", "повторно", "продолжается"}


def _places(chunk: str) -> list[str]:
    out = []
    for m in PLACE.finditer(chunk or ""):
        v = m.group(0)
        if v.lower() not in STOP and len(v) >= 4:
            out.append(v)
    return out


def parse(text: str) -> list[dict]:
    """[{src: [назви], dst: [назви], marker: str}] для кожного вектора в тексті."""
    flat = " ".join(l.strip() for l in text.split("\n"))
    out = []
    m = TO_MARK.search(flat)
    if m:
        left, right = flat[:m.start()], flat[m.end():]
        fm = FROM_MARK.search(left)
        src_chunk = left[fm.end():] if fm else left
        # «X и далее в направлении Y» — джерело це X, а не все ліворуч
        d = DALEE.search(src_chunk)
        if d:
            src_chunk = src_chunk[:d.start()]
        src, dst = _places(src_chunk), _places(right)
        if dst:
            out.append({"src": src[-2:], "dst": dst[:2], "marker": m.group(0)})
        return out
    # «А и далее Б» без слова «направление»
    d = DALEE.search(flat)
    if d:
        src, dst = _places(flat[:d.start()]), _places(flat[d.end():])
        if src and dst:
            out.append({"src": src[-2:], "dst": dst[:2], "marker": "далее"})
    return out


def geocode_vectors(posts: list[dict], gaz, region_geo: dict,
                    max_km: float = 400.0) -> list[dict]:
    """Вектори з координатами обох кінців."""
    out = []
    for p in posts:
        vs = parse(p["text"])
        if not vs:
            continue
        regions = [e["value"] for e in p.get("entities", [])
                   if e["type"] == "регіон" and e["value"] in region_geo]
        near = region_geo[regions[0]] if regions else None
        for v in vs:
            a = _first_hit(v["src"], gaz, near, max_km)
            b = _first_hit(v["dst"], gaz, near, max_km)
            if not b:
                continue
            out.append({
                "t": p["date"], "url": p["url"],
                "src_name": a["name"] if a else None,
                "src": [a["lat"], a["lon"]] if a else None,
                "dst_name": b["name"], "dst": [b["lat"], b["lon"]],
                "marker": v["marker"],
                "text": p["text"].replace("\n", " / "),
            })
    return out


def _first_hit(names, gaz, near, max_km):
    for n in names:
        hit = gaz.lookup(n, near, max_km)
        if hit:
            return hit
    return None
