#!/usr/bin/env python3
"""Підписи областей: місце під назву й сама назва двома мовами.

ЧОМУ ЦЕЙ ФАЙЛ ВЗАГАЛІ Є. `drawRegionLabels` у редакторі виходить першим же
рядком, якщо в підкладці нема ключа `regionLabels`. Такого ключа не писав
жоден генератор, тож шар «назви областей» стояв увімкненим і не малював
нічого. Тут він з'являється.

ЗВІДКИ ГЕОМЕТРІЯ. Контури областей уже лежать у basemap (`regions`) — ті
самі вершини, якими малюється заливка. Нових джерел не додається: якір
рахується з наявного контура.

ЯКИЙ САМЕ ЯКІР. Не центр ваги: у Криму, Ленінградської та Ростовської
центр ваги лягає у воду або поза контуром. Береться полюс недосяжності —
найглибша точка області, — двопрохідним пошуком по сітці.

НАЗВИ. Ключі `MATCH` — це маркер області, а не її підпис («Ивановська»,
«ТОТ_Донецьк»). Тому назва для карти виписана словником: українська й
англійська. Англійська береться не з name_en Natural Earth — там голий
«Bryansk» без роду об'єкта, а на карті потрібне «Bryansk Oblast».

Запуск: python3 mkreglabels.py   (дописує ключ "regionLabels" у basemap.js
                                  і basemap.json)
"""
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# ключ у basemap -> (підпис українською, підпис англійською)
NAMES = {
    "Крим": ("Крим", "Crimea"),
    "Краснодарський": ("Краснодарський край", "Krasnodar Krai"),
    "Ставропольський": ("Ставропольський край", "Stavropol Krai"),
    "Ростовська": ("Ростовська обл.", "Rostov Oblast"),
    "Бєлгородська": ("Бєлгородська обл.", "Belgorod Oblast"),
    "Курська": ("Курська обл.", "Kursk Oblast"),
    "Брянська": ("Брянська обл.", "Bryansk Oblast"),
    "Воронезька": ("Воронезька обл.", "Voronezh Oblast"),
    "Липецька": ("Липецька обл.", "Lipetsk Oblast"),
    "Тульська": ("Тульська обл.", "Tula Oblast"),
    "Калузька": ("Калузька обл.", "Kaluga Oblast"),
    "Московська": ("Московська обл.", "Moscow Oblast"),
    "Саратовська": ("Саратовська обл.", "Saratov Oblast"),
    "Ярославська": ("Ярославська обл.", "Yaroslavl Oblast"),
    "Новгородська": ("Новгородська обл.", "Novgorod Oblast"),
    "Владимирська": ("Владимирська обл.", "Vladimir Oblast"),
    "Ивановська": ("Івановська обл.", "Ivanovo Oblast"),
    "Костромська": ("Костромська обл.", "Kostroma Oblast"),
    "Тверська": ("Тверська обл.", "Tver Oblast"),
    "Ленінградська": ("Ленінградська обл.", "Leningrad Oblast"),
    "Волгоградська": ("Волгоградська обл.", "Volgograd Oblast"),
    "Орловська": ("Орловська обл.", "Oryol Oblast"),
    "Рязанська": ("Рязанська обл.", "Ryazan Oblast"),
    "Тамбовська": ("Тамбовська обл.", "Tambov Oblast"),
    "Смоленська": ("Смоленська обл.", "Smolensk Oblast"),
    "Мордовія": ("Мордовія", "Mordovia"),
    "Пензенська": ("Пензенська обл.", "Penza Oblast"),
    "Нижегородська": ("Нижньогородська обл.", "Nizhny Novgorod Oblast"),
    "Самарська": ("Самарська обл.", "Samara Oblast"),
    "Ульяновська": ("Ульяновська обл.", "Ulyanovsk Oblast"),
    "Астраханська": ("Астраханська обл.", "Astrakhan Oblast"),
    "Башкортостан": ("Башкортостан", "Bashkortostan"),
    "Удмуртія": ("Удмуртія", "Udmurtia"),
    "Оренбурзька": ("Оренбурзька обл.", "Orenburg Oblast"),
    "Татарстан": ("Татарстан", "Tatarstan"),
    "Свердловська": ("Свердловська обл.", "Sverdlovsk Oblast"),
    "Пермський": ("Пермський край", "Perm Krai"),
    "Тюменська": ("Тюменська обл.", "Tyumen Oblast"),
    "Челябінська": ("Челябінська обл.", "Chelyabinsk Oblast"),
    "Курганська": ("Курганська обл.", "Kurgan Oblast"),
    "Омська": ("Омська обл.", "Omsk Oblast"),
    "ХМАО": ("ХМАО — Югра", "Khanty-Mansi AO"),
    "ЯНАО": ("ЯНАО", "Yamalo-Nenets AO"),
    "Дагестан": ("Дагестан", "Dagestan"),
    "ТОТ_Донецьк": ("Донецька обл.", "Donetsk Oblast"),
    "ТОТ_Луганськ": ("Луганська обл.", "Luhansk Oblast"),
    "ТОТ_Запоріжжя": ("Запорізька обл.", "Zaporizhzhia Oblast"),
    "ТОТ_Херсон": ("Херсонська обл.", "Kherson Oblast"),
}


def area(ring):
    """Площа контура в градусах², з поправкою на звуження меридіанів."""
    s = 0.0
    for i in range(len(ring)):
        a, b = ring[i - 1], ring[i]
        s += a[1] * b[0] - b[1] * a[0]
    la = sum(p[0] for p in ring) / len(ring)
    return abs(s) / 2 * math.cos(math.radians(la))


def inside(la, lo, ring):
    ins = False
    for i in range(len(ring)):
        a, b = ring[i - 1], ring[i]
        if (b[0] > la) != (a[0] > la):
            x = (a[1] - b[1]) * (la - b[0]) / ((a[0] - b[0]) or 1e-12) + b[1]
            if lo < x:
                ins = not ins
    return ins


def edge_dist(la, lo, ring, k):
    """Відстань до найближчого ребра контура. Довгота стискається на cos —
    інакше на 55° північної широти «глибина» рахується розтягнутою вдвічі."""
    best = 1e9
    for i in range(len(ring)):
        ay, ax = ring[i - 1][0], ring[i - 1][1] * k
        by, bx = ring[i][0], ring[i][1] * k
        dy, dx = by - ay, bx - ax
        t = 0.0
        d2 = dy * dy + dx * dx
        if d2:
            t = max(0.0, min(1.0, ((la - ay) * dy + (lo * k - ax) * dx) / d2))
        py, px = ay + dy * t, ax + dx * t
        d = (la - py) ** 2 + (lo * k - px) ** 2
        if d < best:
            best = d
    return math.sqrt(best)


def anchor(ring):
    """Полюс недосяжності: найглибша точка контура.

    Два проходи. Грубий по всьому bbox, тонкий — навколо переможця. Один
    дрібний прохід коштував би вдесятеро й дав би те саме місце.
    """
    la0 = min(p[0] for p in ring); la1 = max(p[0] for p in ring)
    lo0 = min(p[1] for p in ring); lo1 = max(p[1] for p in ring)
    k = math.cos(math.radians((la0 + la1) / 2))
    best, bd = None, -1
    box, n = (la0, la1, lo0, lo1), 26
    for step in (0, 1):
        if step:
            if best is None:      # контур тонший за крок сітки
                break
            dla, dlo = (la1 - la0) / 26, (lo1 - lo0) / 26
            box = (best[0] - dla, best[0] + dla, best[1] - dlo, best[1] + dlo)
            n = 14
        a0, a1, b0, b1 = box
        for i in range(n + 1):
            la = a0 + (a1 - a0) * i / n
            for j in range(n + 1):
                lo = b0 + (b1 - b0) * j / n
                if not inside(la, lo, ring):
                    continue
                d = edge_dist(la, lo, ring, k)
                if d > bd:
                    bd, best = d, (la, lo)
    return best


def labels(regions):
    out = []
    for key, rings in regions.items():
        name = NAMES.get(key)
        if not name:
            print(f"! нема підпису для {key} — пропущено")
            continue
        big = max(rings, key=area)
        pt = anchor(big)
        if not pt:
            print(f"! якір не знайдено: {key}")
            continue
        out.append({"n": name[0], "e": name[1],
                    "la": round(pt[0], 3), "lo": round(pt[1], 3),
                    "a": round(sum(area(r) for r in rings), 2)})
    out.sort(key=lambda r: -r["a"])
    return out


def payload(path):
    s = open(path, encoding="utf-8").read()
    i = s.index("=") + 1
    d, end = json.JSONDecoder().raw_decode(s[i:].lstrip())
    return d, s[i:].lstrip()[end:]


def main():
    js = os.path.join(HERE, "basemap.js")
    data, tail = payload(js)
    data["regionLabels"] = labels(data.get("regions") or {})
    with open(js, "w", encoding="utf-8") as f:
        f.write("window.BASE=")
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        f.write(tail)
    print(f"basemap.js: підписів областей {len(data['regionLabels'])}")

    bm = os.path.join(HERE, "basemap.json")
    if os.path.exists(bm):
        d2 = json.load(open(bm, encoding="utf-8"))
        d2["regionLabels"] = labels(d2.get("regions") or {})
        json.dump(d2, open(bm, "w", encoding="utf-8"),
                  ensure_ascii=False, separators=(",", ":"))
        print(f"basemap.json: підписів областей {len(d2['regionLabels'])}")


if __name__ == "__main__":
    main()
