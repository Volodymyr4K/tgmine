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
        "примерно", "также", "повторно", "продолжается",
        # заміряно на 15 добах: саме ці два з великої літери на початку
        # речення найчастіше ставали «джерелом» вектора (по 6 разів кожне)
        "продолжаются", "противник", "противника", "следующая",
        "многочисленная", "волна", "предположительно", "вероятнее"}
# Прийменник з великої на початку речення склеюється з назвою в одну «назву»:
# «Над Белгородской» — і такого місця в газетирі нема. Відкидаємо перше слово,
# якщо це прийменник, і лишаємо саму назву. Той самий клас, що lookahead у
# freeform-шаблоні конфіга («От Белой Березки»).
PREP = {"над", "от", "из", "через", "по", "на", "в", "у", "до", "за", "под",
        "возле", "около", "севернее", "южнее", "западнее", "восточнее"}


def _places(chunk: str) -> list[str]:
    out = []
    for m in PLACE.finditer(chunk or ""):
        v = m.group(0)
        head, _, tail = v.partition(" ")
        if tail and head.lower() in PREP:
            v = tail
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
                    max_km: float = 400.0, region_a1: dict | None = None,
                    region_rx: dict | None = None) -> list[dict]:
    """Вектори з координатами обох кінців.

    `region_a1` — коди admin1 на регіон (як у `store.build`), потрібні, щоб
    район брався лише зі своєї області; `region_rx` — патерни регіонів із
    конфіга, щоб «от Брянской области» давало центроїд області. Без них
    фолбеки мовчать, і поведінка та сама, що була.

    Заміряно до правки на 15 добах: із 1676 розібраних векторів джерело
    губили 242, і всі 242 — саме src, жодного dst. 59 — район («Ливенский»,
    «Хомутовский»), який лежить у газетирі як «<назва> район»; 11 — область
    прикметником; ще частина — артефакти розбору («Продолжаются»,
    «Над Белгородской»). Кожен відновлений вектор — це ланка маршруту
    `declared` замість `inferred`.
    """
    out = []
    for p in posts:
        vs = parse(p["text"])
        if not vs:
            continue
        regions = [e["value"] for e in p.get("entities", [])
                   if e["type"] == "регіон" and e["value"] in region_geo]
        near = region_geo[regions[0]] if regions else None
        a1 = (region_a1 or {}).get(regions[0]) if regions else None
        for v in vs:
            a = _first_hit(v["src"], gaz, near, max_km, a1, region_rx, region_geo)
            b = _first_hit(v["dst"], gaz, near, max_km, a1, region_rx, region_geo)
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


_ADJ = re.compile(r"(?:ский|ская|цкий|цкая|ской|цкой)$", re.I)


def _first_hit(names, gaz, near, max_km, a1=None, region_rx=None, region_geo=None):
    # Спершу звичайний пошук по ВСІХ іменах, і лише коли не розвʼязалось
    # жодне — фолбеки. Не навпаки: перша версія застосовувала фолбек до
    # першого ж нерозвʼязаного імені й перебивала наступне, яке розвʼязалось
    # би саме. Заміряно: «Керченский полуостров, Керчь» давало центроїд Криму
    # замість Керчі, «Курская область, Обоянь» — центроїд Курської замість
    # Обояні; таких погіршень було 47 на 15 діб. Правило «не грубіше, ніж
    # було» — обовʼязкове, бо вектор іде в маршрут як свідчення.
    for n in names:
        hit = gaz.lookup(n, near, max_km)
        if hit:
            return hit
    for n in names:
        # «от Брянской области» — джерело це область; для dst газетир і так
        # віддає ADM1, для src через прикметникову форму — ні.
        if region_rx and region_geo:
            for reg, rx in region_rx.items():
                if reg in region_geo and rx.search(n):
                    lat, lon = region_geo[reg]
                    return {"name": reg, "lat": lat, "lon": lon, "pop": 0,
                            "fclass": "A", "conf": "region-centroid"}
        # «Ливенский» без слова «район» — той самий випадок, що в geocode:
        # район у газетирі є, але під двослівним ключем. Беремо його ТІЛЬКИ
        # зі своєї області, інакше це інший здогад.
        if a1 and _ADJ.search(n):
            d = gaz.lookup(f"{n} район", near, max_km, near_a1=a1)
            if d and (d.get("cc"), d.get("a1")) in a1:
                return d
    return None
