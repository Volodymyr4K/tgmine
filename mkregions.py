#!/usr/bin/env python3
"""Витягує межі областей із Natural Earth і зіставляє з ключами конфіга.

Полігони спрощуються: у масштабі країни повна деталізація берегової лінії
непотрібна, а необроблений shapefile роздув би HTML на десятки мегабайт.

Запуск:  python3 mkregions.py
"""
import json
import math
import sys

sys.setrecursionlimit(20000)

import shapefile

SHP = "gazetteer/ne_10m_admin_1_states_provinces"
OUT = "regions.json"
#: Підконтрольна Україні територія — референс для «глибини» (store.depth,
#: raid, routes). Україна за Natural Earth МІНУС чотири окуповані області;
#: Крим NE і так відносить до RUS. Той самий список, що в territory.UA_CONTESTED,
#: тобто цілі й глибина міряються від однієї лінії. Точність — ширина області:
#: Запоріжжя-місто чи Херсон-місто підконтрольні, але вся область рахується як
#: ні. Лінію зіткнення НЕ апроксимуємо (див. CLAUDE.md).
OUT_UA = "ukraine_controlled.json"
UA_OCCUPIED = ("Донецкая область", "Луганская область",
               "Херсонская область", "Запорожская область")

# ключ конфіга -> підрядок у полі name_ru (Natural Earth)
MATCH = {
    "Крим":             ["Республика Крым", "Севастополь"],
    "Краснодарський":   ["Краснодарский край"],
    "Ростовська":       ["Ростовская область"],
    "Бєлгородська":     ["Белгородская область"],
    "Курська":          ["Курская область"],
    "Брянська":         ["Брянская область"],
    "Воронезька":       ["Воронежская область"],
    "Липецька":         ["Липецкая область"],
    "Тульська":         ["Тульская область"],
    "Калузька":         ["Калужская область"],
    "Московська":       ["Московская область", "Москва"],
    "Саратовська":      ["Саратовская область"],
    "Ярославська":      ["Ярославская область"],
    "Новгородська":     ["Новгородская область"],
    "Владимирська":     ["Владимирская область"],
    "Ивановська":       ["Ивановская область"],
    "Костромська":      ["Костромская область"],
    "Тверська":         ["Тверская область"],
    "Ленінградська":    ["Ленинградская область", "Санкт-Петербург"],
    "Волгоградська":    ["Волгоградская область"],
    "Орловська":        ["Орловская область"],
    "Ставропольський":  ["Ставропольский край"],
    "Рязанська":        ["Рязанская область"],
    "Тамбовська":       ["Тамбовская область"],
    "Смоленська":       ["Смоленская область"],
    "Мордовія":         ["Мордовия"],
    "Пензенська":       ["Пензенская область"],
    "Нижегородська":    ["Нижегородская область"],
    "Самарська":        ["Самарская область"],
    "Ульяновська":      ["Ульяновская область"],
    "Астраханська":     ["Астраханская область"],
    "Башкортостан":     ["Башкортостан"],
    "Удмуртія":         ["Удмуртская", "Удмуртия"],
    "Оренбурзька":      ["Оренбургская область"],
    "Татарстан":        ["Татарстан"],
    # ТОТ — це українські області під окупацією; беремо українські полігони
    "ТОТ_Донецьк":      ["Донецкая область"],
    "ТОТ_Луганськ":     ["Луганская область"],
    "ТОТ_Запоріжжя":    ["Запорожская область"],
    "ТОТ_Херсон":       ["Херсонская область"],
}


def rdp(pts, eps):
    """Спрощення Дугласа-Пекера. Без нього один регіон дає тисячі точок."""
    if len(pts) < 3:
        return pts
    x1, y1 = pts[0]
    x2, y2 = pts[-1]
    dmax, idx = 0.0, 0
    for i in range(1, len(pts) - 1):
        x0, y0 = pts[i]
        num = abs((y2 - y1) * x0 - (x2 - x1) * y0 + x2 * y1 - y2 * x1)
        den = math.hypot(y2 - y1, x2 - x1) or 1e-12
        d = num / den
        if d > dmax:
            dmax, idx = d, i
    if dmax > eps:
        a = rdp(pts[:idx + 1], eps)
        b = rdp(pts[idx:], eps)
        return a[:-1] + b
    return [pts[0], pts[-1]]


def simplify_ring(ring, eps):
    """Спрощення ЗАМКНЕНОГО контуру.

    Наївний Дуглас-Пекер тут не працює: у кільця перша й остання точка збігаються,
    базовий відрізок вироджується в точку, всі відстані стають нульовими і від
    області лишається 2 точки. Тому ріжемо кільце в найдальшій від початку точці
    й спрощуємо дві половини окремо.
    """
    if len(ring) < 8:
        return ring
    pts = ring[:-1] if ring[0] == ring[-1] else ring[:]
    x0, y0 = pts[0]
    far = max(range(len(pts)), key=lambda i: (pts[i][0] - x0) ** 2 + (pts[i][1] - y0) ** 2)
    a = rdp(pts[:far + 1], eps)
    b = rdp(pts[far:] + [pts[0]], eps)
    out = a[:-1] + b
    return out


def rings_of(shape, eps=0.04, min_pts=6):
    parts = list(shape.parts) + [len(shape.points)]
    out = []
    for i in range(len(parts) - 1):
        ring = shape.points[parts[i]:parts[i + 1]]
        if len(ring) < 4:
            continue
        simp = simplify_ring([(round(x, 4), round(y, 4)) for x, y in ring], eps)
        if len(simp) >= min_pts:
            # Leaflet чекає [lat, lon], shapefile дає (lon, lat)
            out.append([[round(y, 3), round(x, 3)] for x, y in simp])
    return out


def main(eps="0.04"):
    eps = float(eps)
    r = shapefile.Reader(SHP)
    recs = [s for s in r.iterShapeRecords()
            if s.record["admin"] in ("Russia", "Ukraine")]
    out, unmatched = {}, []
    for key, pats in MATCH.items():
        rings = []
        for s in recs:
            nr = s.record["name_ru"] or ""
            if any(p.lower() in nr.lower() for p in pats):
                rings.extend(rings_of(s.shape, eps))
        if rings:
            out[key] = rings
        else:
            unmatched.append(key)   # або назва не збіглась, або контур порожній

    pts = sum(len(ring) for rings in out.values() for ring in rings)
    json.dump(out, open(OUT, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))

    ua = []
    for s in recs:
        if s.record["admin"] != "Ukraine":
            continue
        nr = s.record["name_ru"] or ""
        if any(o.lower() in nr.lower() for o in UA_OCCUPIED):
            continue
        ua.extend(rings_of(s.shape, eps))
    json.dump(ua, open(OUT_UA, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    print(f"{OUT_UA}: контурів {len(ua)}, вершин {sum(len(r) for r in ua)}")
    import os
    print(f"регіонів: {len(out)}   контурів: {sum(len(v) for v in out.values())}"
          f"   точок: {pts}")
    print(f"-> {OUT}  ({os.path.getsize(OUT)/1024:.0f} КБ)")
    if unmatched:
        print("НЕ знайдено:", ", ".join(unmatched))


if __name__ == "__main__":
    main(*sys.argv[1:])
