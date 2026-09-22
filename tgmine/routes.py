#!/usr/bin/env python3
"""Маршрути ночі: суцільні шляхи замість розсипу обрізків.

ЩО БУЛО НЕ ТАК. Канали пишуть рух шматками: «від Бірюча в напрямку
Олексіївки», через 20 хвилин «від Олексіївки на Троїцьке». Кожен шматок сам
собою — обрізок на 40 км, який нікуди не веде. Намальовані окремо, вони й
виглядають як розсип обрізків: карта є, маршрутів на ній нема. Насправді це
ОДИН шлях на 1121 км, і малювати треба його.

ДВА ДЖЕРЕЛА, ОДИН ГРАФ. Ніч описують два різні шари, і кожен сам собою
дірявий:

  * ЗАЯВЛЕНІ ВЕКТОРИ — канал прямо пише напрямок. Свідчення сильне (це не
    здогад), але рідке: 147 ланок за ніч, і 45 із них ні з чим не стикуються.
  * ТОЧКОВІ ФІКСАЦІЇ — «о 02:14 над Х». Їх утричі більше, але напрямку в них
    нема: рух доводиться припускати з фізики (це робить tgmine/tracker.py).

Разом вони дають те, чого не дає жоден окремо: кістяк маршруту з фіксацій і
підтверджений напрямок із векторів. Тому ланка маршруту несе позначку, ЧИМ
вона тримається — `declared` (канал написав напрямок) чи `inferred`
(асоціація за швидкістю й курсом). На карті це різні лінії, і читач бачить,
де доказ, а де гіпотеза. Змішати їх в одну лінію означало б видати здогад за
свідчення.

ЩО СВІДОМО НЕ РОБИМО. Не добудовуємо маршрут до кордону й не тягнемо його до
найближчої цілі: ані пуску, ані влучання в даних нема, і домальовувати кінці
означає малювати те, чого ніхто не спостерігав.
"""
from __future__ import annotations

import math
import re
from datetime import datetime

from tgmine import associate as AS
from tgmine import territory as T

# Клас засобу з тексту повідомлення. Регулярки дзеркалять `tags` у
# configs/ru-monitor.yaml: у сховищі клас не зберігається (там лише `utype`,
# і той у 3.4% подій), тому для маршруту його доводиться визначати наново.
CLASSES = [
    ("ракета", r"ракет(?!но[ -]бомбов)(?!ная бомбов)(?!но бомбов)\w*|"
               r"Нептун|Фламинго|Гром|Точка-У|баллистик\w*"),
    ("УАБ", r"\bУАБ\b|\bКАБ\b|авиабомб\w*|авиационн\w* ракетно бомбов\w*"),
    ("РСЗО", r"РСЗО|Хаймарс|HIMARS|Ольха|Вампир"),
    ("БПЛА", r"БПЛА|БпЛА|дрон\w*|б/?п\b"),
]
CLASSES = [(k, re.compile(p, re.I)) for k, p in CLASSES]


def klass(text: str) -> str:
    for name, rx in CLASSES:
        if rx.search(text or ""):
            return name
    return "невідомо"

R_LINK_KM = 100.0        # стик: кінець ланки -> початок наступної
DT_MAX_MIN = 120.0       # вікно продовження ланцюга
TURN_MAX = 60.0          # поворот між сусідніми ланками, градусів
SAME_PLACE_KM = 15.0     # ланка «на місці» — повтор того самого повідомлення
V_MIN, V_MAX = 60.0, 350.0   # км/год між повідомленнями сусідніх ланок

# Кінець ланки, геокодований в ОБЛАСТЬ, — це не місце, а 30 тисяч кв. км.
# Через такі кінці ланцюг стрибав Бєлгородська -> Тамбовська за 402 км і
# видавав 688 км/год, тобто зшивав РІЗНІ групи через центри областей.
# Район лишаємо: це 40 км, з ним ланцюги ще мають сенс.
AREA_SUFFIX = (" oblast", " kray", " krai", " republic", " okrug", " federal")

# Кінець ланки має лежати в межах області, про яку сам пост. 95% кінців
# укладаються в 286 км від центру своєї області, 99% — у 369 км. Ті, що далі,
# майже завжди омоніми: «Херсонес» (Севастополь) їхав на Херсонщину за 363 км,
# «Саратовська» з Волгоградщини виявлялась станицею на Кубані. Поріг 300 км
# лишає сусідні області (там рух справді буває) і зрізає перельоти через
# півкраїни.
REGION_SANITY_KM = 300.0

# Ланка треку вважається підтвердженою вектором, якщо обидва кінці збігаються
# в межах цього радіуса й години. Радіус не менший за похибку самих точок.
MATCH_KM, MATCH_MIN = 45.0, 60.0

MIN_ROUTE_KM = 25.0

# Межа правдоподібності ОДНІЄЇ заявленої ланки. Мірка не з голови: ланка
# всередині зшитого ланцюга (тобто рух, підтверджений кількома
# повідомленнями) має медіану 84 км, 95-й перцентиль 169 км і максимум 298 км
# на трьох ночах. Одноланкове твердження на 480 км нічим із цього не
# підтримане — це або далекий прогноз каналу, або промах геокодера. Такі
# маршрути не викидаються, а позначаються слабкими: рішення за оператором.
PLAUSIBLE_HOP_KM = 200.0

# Один і той самий коридор часто заявляють кілька каналів (kupolrussia
# дзеркалить lpr1) або той самий канал повторює повідомлення. Три однакові
# «Киришський район -> Кириші» — це один рух і три згадки, а не три маршрути.
SAME_ROUTE_KM, SAME_ROUTE_MIN = 25.0, 45.0

# --- добудова маршруту НАЗАД ------------------------------------------------
# Апарат не зʼявляється в глибині країни нізвідки: до першої фіксації він
# кудись летів. Пороги підібрані НУЛЬ-ТЕСТОМ, як і в трекері: перемішуємо
# часові мітки точкових подій і дивимось, скільки «попередників» знайдеться в
# шумі. По трьох ночах:
#
#   180 хв / 500 км / 40°  ->  9, 22, 24 проти 5.0, 21.3, 22.7   z = +0.4
#    90 хв / 300 км / 30°  ->  4, 12, 18 проти 2.2,  7.0,  8.0   z = +2.7
#    60 хв / 200 км / 25°  ->  2,  2, 10 проти 1.0,  2.0,  2.8   z = +1.0
#
# Широкі пороги — артефакт щільності: позаду завжди щось знайдеться. Робоча
# зона середня, і навіть у ній близько половини знахідок очікувані випадково,
# тому кожна добудована ланка позначається `inferred` і впевненості не додає.
#
# Лінію до кордону не тягнемо взагалі: перевірка «сховай першу точку й вгадай
# її з решти» дає кутову похибку 23° (медіана) і 43° на 90-му перцентилі — на
# 300 км це сектор ±280 км.
BACK_MAX_MIN = 90.0
BACK_MIN_KM, BACK_MAX_KM = 20.0, 300.0
BACK_TURN_MAX = 30.0
BACK_V_MIN, BACK_V_MAX = 110.0, 260.0

# Опорні точки кордону — ті самі, що в raid.py. Глибина потрібна, щоб
# розрізняти «до кордону» і «вглиб»: без неї добудова однаково охоче тягла б
# маршрут у неправильний бік.
def depth_of(la, lo):
    # підконтрольна Україні територія — territory.depth_km (одна на весь конвеєр)
    return T.depth_km(la, lo)


# Район і його ж центр — це те саме місце, названо двічі: «Киришський район ->
# Кириші». Відстань тут не показник: у помилкових збігах («Ярославський
# район» у Москві -> Ярославль) вона доходить до 237 км, і саме тому фільтр
# по назві, а не по кілометрах.
def _same_toponym(a, b):
    """Чи це одна назва, сказана двічі.

    Порівнюємо не рядки, а спільний початок: «Kirishskiy Rayon» і «Kirishi»
    дають «kirish» (6 літер), «Yaroslavsky District» і «Yaroslavl» — «yaroslav»
    (8). Прикметникові й службові хвости («-skiy», «rayon», «район») знімаємо
    заздалегідь. Поріг у 5 літер лишає «Klintsy»/«Surazh» різними, а
    «Novosil»/«Novomoskovsk» не злипаються (спільних лише 4).
    """
    import re as _re

    def norm(n):
        n = (n or "").lower()
        n = _re.sub(r"[^a-zа-яёіїєґ ]+", " ", n)
        n = _re.sub(r"\b(rayon|raion|district|urban|oblast|city|"
                    r"район|міський|городской|город)\b", " ", n)
        n = _re.sub(r"(sk(iy|y|aya|oye|oe)|ский|ская|ское|ская)\b", "", n)
        return " ".join(n.split()).replace(" ", "")

    x, y = norm(a), norm(b)
    if len(x) < 4 or len(y) < 4:
        return False
    common = 0
    for ca, cb in zip(x, y):
        if ca != cb:
            break
        common += 1
    return common >= 5 and common >= 0.6 * min(len(x), len(y))


def hav(a, b):
    R = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = (math.sin((la2 - la1) / 2) ** 2 +
         math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(h))


def bearing(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    dl = lo2 - lo1
    y = math.sin(dl) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def turn(b1, b2):
    d = abs(b1 - b2) % 360
    return min(d, 360 - d)


# --------------------------------------------------------------------------
# 1. ланцюги із ЗАЯВЛЕНИХ векторів
# --------------------------------------------------------------------------
def _hops(vecs, region_of=None, region_geo=None):
    """Ланки з векторів. Відсіюємо те, що рухом не є.

    `region_of` — область поста за його url, `region_geo` — центри областей.
    Разом вони дають перевірку на омонім: кінець, що опинився за 300 км від
    області, про яку пост, майже завжди не той обʼєкт.
    """
    out = []
    dropped = {"area": 0, "same": 0, "homonym": 0, "place": 0}
    for v in vecs:
        if not v.get("src"):
            continue
        src, dst = tuple(v["src"]), tuple(v["dst"])
        if hav(src, dst) < SAME_PLACE_KM:
            dropped["place"] += 1
            continue                      # ланка «на місці», не рух
        names = f"{v['src_name'] or ''}|{v['dst_name']}".lower()
        if any(sfx in names for sfx in AREA_SUFFIX):
            dropped["area"] += 1
            continue                      # кінець — область, а не місце
        if _same_toponym(v.get("src_name"), v.get("dst_name")):
            dropped["same"] += 1
            continue                      # район і його ж центр — не рух
        if region_of and region_geo:
            reg = region_of.get(v.get("url"))
            c = region_geo.get(reg) if reg else None
            if c and (hav(src, tuple(c)) > REGION_SANITY_KM
                      or hav(dst, tuple(c)) > REGION_SANITY_KM):
                dropped["homonym"] += 1
                continue                  # кінець поїхав в іншу область
        out.append({"src": src, "dst": dst, "sn": v["src_name"], "dn": v["dst_name"],
                    "dt": datetime.fromisoformat(v["t"]), "hhmm": v["hhmm"],
                    "k": klass(v["text"]), "brg": bearing(src, dst), "url": v["url"]})
    out.sort(key=lambda h: h["dt"])
    return out, dropped


def declared_chains(hops):
    used = [False] * len(hops)
    chains = []
    for i, h in enumerate(hops):
        if used[i]:
            continue
        used[i] = True
        chain = [h]
        while True:
            cur = chain[-1]
            best, best_d = None, None
            for j, c in enumerate(hops):
                if used[j]:
                    continue
                dtm = (c["dt"] - cur["dt"]).total_seconds() / 60.0
                if dtm <= 0 or dtm > DT_MAX_MIN:
                    continue
                d = hav(cur["dst"], c["src"])
                if d > R_LINK_KM or turn(cur["brg"], c["brg"]) > TURN_MAX:
                    continue
                v_kmh = hav(cur["dst"], c["dst"]) / (dtm / 60.0)
                if not (V_MIN <= v_kmh <= V_MAX):
                    continue              # так ударний БпЛА не літає
                # найщільніший стик, а не найраніший: ранній може бути іншою
                # групою, що перетинає ту саму точку
                if best_d is None or d < best_d:
                    best, best_d = j, d
            if best is None:
                break
            used[best] = True
            chain.append(hops[best])
        chains.append(chain)
    return chains


# --------------------------------------------------------------------------
# 2. треки з ТОЧКОВИХ фіксацій — фізика з tgmine/tracker.py, не своя
# --------------------------------------------------------------------------
def point_tracks(events):
    """Треки з точкових фіксацій.

    Асоціація — `tgmine/associate.py` (Калман + угорський алгоритм), а не
    жадібний `tracker.py`. Різниця виміряна незалежною мірою — збігом ланок
    із напрямком, який канал заявив словами:

        жадібний:      1-3 треки, 2-6 ланок за ніч, збіг 0-17%
        Калман+ГНН:  9-25 треків, 32-97 ланок,      збіг 14-60%

    Нуль-тест на перемішаних часових мітках дає медіану z = +5.0. `tracker.py`
    лишається на місці: на ньому стоять карта нальоту й нуль-тест у raid.py,
    і його поведінку тут міняти не треба.
    """
    dets = []
    for e in events:
        if e.get("scope") != "точка" or not e.get("lat"):
            continue
        if e.get("geo_conf") in ("centroid", "region-snap"):
            continue
        dets.append({"dt": datetime.fromisoformat(e["t"]),
                     "lat": e["lat"], "lon": e["lon"],
                     "place": e.get("place", ""), "kind": e.get("kind", ""),
                     "url": e.get("url", ""), "depth": e.get("depth"),
                     "hhmm": e.get("hhmm", ""), "utype": e.get("utype")})
    out = []
    for t in AS.build(dets):
        out.append({
            "km": t["km"], "hours": t["hours"], "kmh": t["kmh"],
            "points": [{"lat": p["lat"], "lon": p["lon"], "hhmm": p["hhmm"],
                        "place": p["place"], "status": p["kind"],
                        "t": p["dt"].isoformat(), "depth": p.get("depth"),
                        "url": p.get("url", ""), "utype": p.get("utype")}
                       for p in t["pts"]],
        })
    return out


# --------------------------------------------------------------------------
# 3. збірка: маршрут = послідовність точок + позначка, чим тримається ланка
# --------------------------------------------------------------------------
def _leg_declared(a, b, ta, tb, hops):
    """Чи є заявлений вектор, який описує саме цю ланку."""
    for h in hops:
        if hav(h["src"], a) > MATCH_KM or hav(h["dst"], b) > MATCH_KM:
            continue
        if abs((h["dt"] - ta).total_seconds()) / 60.0 <= MATCH_MIN:
            return True
    return False


def _inland_backwards(r):
    a, b = r["pts"][0], r["pts"][-1]
    da = depth_of(a["la"], a["lo"])
    db = depth_of(b["la"], b["lo"])
    return min(da, db) > 150 and db < da - 20


def _merge_same(routes):
    """Однакові маршрути в один, із лічильником згадок."""
    out = []
    for r in sorted(routes, key=lambda r: r["t0"]):
        a0 = (r["pts"][0]["la"], r["pts"][0]["lo"])
        a1 = (r["pts"][-1]["la"], r["pts"][-1]["lo"])
        for q in out:
            b0 = (q["pts"][0]["la"], q["pts"][0]["lo"])
            b1 = (q["pts"][-1]["la"], q["pts"][-1]["lo"])
            if (hav(a0, b0) <= SAME_ROUTE_KM and hav(a1, b1) <= SAME_ROUTE_KM
                    and abs(_mins(r["t0"]) - _mins(q["t0"])) <= SAME_ROUTE_MIN):
                q["claims"] += 1
                # довший опис того самого руху інформативніший
                if r["n"] > q["n"]:
                    q["pts"], q["legs"], q["n"] = r["pts"], r["legs"], r["n"]
                    q["km"], q["conf"] = r["km"], r["conf"]
                break
        else:
            out.append(r)
    return out


def _mins(hhmm):
    try:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return 0


def extend_back(route, events):
    """Продовжити маршрут назад РЕАЛЬНИМИ спостереженнями.

    Кандидат має бути: раніший, позаду за курсом, ближчий до кордону,
    на правдоподібній швидкості. Кожен доданий крок — асоціація, тому ланка
    позначається `inferred`: на карті це видно як припущення, а не як
    заявлений напрямок.
    """
    added = 0
    while True:
        head = route["pts"][0]
        nxt = route["pts"][1]
        hp = (head["la"], head["lo"])
        back = bearing((nxt["la"], nxt["lo"]), hp)
        t_head = head.get("dt")
        if t_head is None:
            break
        best = None
        for e in events:
            dtm = (t_head - e["dt"]).total_seconds() / 60.0
            if dtm <= 0 or dtm > BACK_MAX_MIN:
                continue
            d = hav((e["la"], e["lo"]), hp)
            if not (BACK_MIN_KM <= d <= BACK_MAX_KM):
                continue
            if turn(bearing(hp, (e["la"], e["lo"])), back) > BACK_TURN_MAX:
                continue
            v = d / (dtm / 60.0)
            if not (BACK_V_MIN <= v <= BACK_V_MAX):
                continue
            # Глибина є лише у фіксацій зі сховища; у вузлів, що прийшли з
            # заявленого вектора, її нема. Без глибини вимогу «ближче до
            # кордону» перевірити нічим, тому такий крок не робимо взагалі:
            # інакше добудова піде «вглиб», тобто в неправильний бік.
            hd, ed = head.get("depth"), e.get("depth")
            if hd is None or ed is None or ed >= hd:
                continue
            if best is None or d < best[0]:
                best = (d, e)
        if best is None:
            break
        _, e = best
        route["pts"].insert(0, {"la": round(e["la"], 3), "lo": round(e["lo"], 3),
                                "hhmm": e["hhmm"], "place": e["place"],
                                "kind": e["kind"], "depth": e.get("depth"),
                                "url": e.get("url", ""), "u": e.get("u"),
                                "dt": e["dt"], "back": True})
        route["legs"].insert(0, "inferred")
        route["km"] += round(best[0])
        route["t0"] = e["hhmm"]
        route["n"] = len(route["pts"])
        added += 1
        if added >= 4:                        # довше ланцюжка вже не тримається
            break
    return added


def _mode(xs):
    """Найчастіше значення; при нічиїй — те, що трапилось раніше.

    Було `max(set(xs), key=xs.count)`: нічию вирішував порядок множини, а
    він залежить від хеш-сіду процесу. Та сама ніч давала різний тип
    засобу маршруту від запуску до запуску (перевірено 22.09.2026: 6
    запусків — 3 різні файли ночі), і карта перезбиралась без змін у даних.
    """
    return max(dict.fromkeys(xs), key=xs.count) if xs else None


def build(raid):
    region_of = {e.get("url"): e.get("region") for e in raid.get("events", [])
                 if e.get("url")}
    # Тип засобу вузла заявленого ланцюга — з події, що дала вектор.
    utype_by_url = {e.get("url"): e.get("utype") for e in raid.get("events", [])
                    if e.get("url")}
    hops, dropped = _hops(raid["vectors"], region_of, raid.get("region_geo"))
    events = raid["events"]
    routes = []
    # точкові спостереження як кандидати на добудову назад
    back_pool = []
    for e in events:
        if e.get("scope") != "точка" or not e.get("lat"):
            continue
        if e.get("geo_conf") in ("centroid", "region-snap"):
            continue
        back_pool.append({"la": e["lat"], "lo": e["lon"],
                          "depth": e.get("depth") or depth_of(e["lat"], e["lon"]),
                          "hhmm": e.get("hhmm", ""), "place": e.get("place", ""),
                          "kind": e.get("kind", ""), "url": e.get("url", ""),
                          "u": e.get("utype"),
                          "dt": datetime.fromisoformat(e["t"])})

    # 3.1 треки з фіксацій, ланки позначені declared там, де є вектор
    for t in point_tracks(events):
        pts, legs = [], []
        prev = None
        for p in t["points"]:
            xy = (p["lat"], p["lon"])
            pts.append({"la": round(xy[0], 3), "lo": round(xy[1], 3),
                        "hhmm": p["hhmm"], "place": p["place"],
                        "kind": p["status"], "url": p.get("url", ""),
                        "u": p.get("utype"),
                        "depth": p.get("depth") or depth_of(xy[0], xy[1]),
                        "dt": datetime.fromisoformat(p["t"])})
            if prev:
                legs.append("declared" if _leg_declared(
                    prev[0], xy, prev[1], datetime.fromisoformat(p["t"]), hops)
                    else "inferred")
            prev = (xy, datetime.fromisoformat(p["t"]))
        routes.append({"src": "трек", "pts": pts, "legs": legs,
                       "km": t["km"], "hours": t["hours"], "kmh": t["kmh"],
                       "t0": t["points"][0]["hhmm"], "t1": t["points"][-1]["hhmm"],
                       "k": "БПЛА", "n": len(pts)})

    # 3.2 заявлені ланцюги, які треки не покрили
    covered = [(p["la"], p["lo"]) for r in routes for p in r["pts"]]
    for chain in declared_chains(hops):
        raw = [chain[0]["src"]] + [c["dst"] for c in chain]
        clean, times, names = [raw[0]], [chain[0]["dt"]], [chain[0]["sn"]]
        # Адреса повідомлення, яке заявило цей рух: у ланки вона вже є,
        # лишалось донести її до вузла, щоб оператор міг перевірити джерело.
        urls = [chain[0]["url"]]
        for c in chain:
            if hav(clean[-1], c["dst"]) >= SAME_PLACE_KM:
                clean.append(c["dst"])
                times.append(c["dt"])
                names.append(c["dn"])
                urls.append(c["url"])
        if len(clean) < 2 or hav(clean[0], clean[-1]) < MIN_ROUTE_KM:
            continue
        # ланцюг, що лежить на вже намальованому треку, не дублюємо
        if sum(1 for p in clean if any(hav(p, q) < 30 for q in covered)) >= len(clean) - 1:
            continue
        km = sum(hav(clean[i], clean[i + 1]) for i in range(len(clean) - 1))
        span = (times[-1] - times[0]).total_seconds() / 3600.0
        cls = [c["k"] for c in chain if c["k"] != "невідомо"]
        routes.append({
            "src": "заявлений",
            "pts": [{"la": round(p[0], 3), "lo": round(p[1], 3),
                     "hhmm": t.strftime("%H:%M"), "place": n, "kind": "вектор",
                     "url": u, "dt": t, "depth": depth_of(p[0], p[1]),
                     "u": utype_by_url.get(u)}
                    for p, t, n, u in zip(clean, times, names, urls)],
            "legs": ["declared"] * (len(clean) - 1),
            "km": round(km), "hours": round(span, 1),
            "kmh": round(km / span) if span > 0.3 else None,
            "t0": times[0].strftime("%H:%M"), "t1": times[-1].strftime("%H:%M"),
            "k": _mode(cls) or "БПЛА", "n": len(clean)})

    # --- добудова назад: звідки група прийшла, якщо це спостерігали ---------
    extended = 0
    for r in routes:
        if extend_back(r, back_pool):
            extended += 1
            r["extended"] = True

    # --- тип засобу маршруту -----------------------------------------------
    # `k` — клас (БПЛА/ракета/УАБ/РСЗО) і лишається для сумісності; `u` —
    # найточніша назва зі сховища (store.utype_of): «Фламінго», «крилата
    # ракета», «Хорнет»… Береться найчастіша по вузлах; вузли без типу не
    # голосують. Редактор за нею ставить маршруту тип, а не «як у поточного».
    for r in routes:
        us = [p.get("u") for p in r["pts"] if p.get("u")]
        r["u"] = _mode(us)

    # --- впевненість -------------------------------------------------------
    for r in routes:
        legs = len(r["legs"])
        # добудовані назад ланки не рахуються за підтвердження: вони
        # асоціація, і нуль-тест каже, що половина з них випадкова
        if legs >= 2 and all(l == "declared" for l in r["legs"]):
            r["conf"] = "strong"          # ланцюг із кількох заявлених ланок
        elif legs >= 2:
            r["conf"] = "ok"              # ланцюг, частина ланок — асоціація
        elif (legs == 1 and r["km"] <= PLAUSIBLE_HOP_KM
              and _inland_backwards(r)):
            # Ланка, що в глибині країни веде НАЗАД до кордону. Буває
            # справжня (біля фронту й над морем рух іде в різні боки), але в
            # глибині це майже завжди наслідок омоніма: «Калуга -> Калінінський»
            # чи «Волгоград -> Саратовська». Не викидаємо — знижуємо оцінку.
            r["conf"] = "weak"
        elif r["km"] <= PLAUSIBLE_HOP_KM:
            r["conf"] = "ok"              # одна ланка в межах спостережуваного
        else:
            r["conf"] = "weak"            # одна ланка довша за все, що бачили
        r["claims"] = 1

    routes = _merge_same(routes)
    for r in routes:
        for p in r["pts"]:
            p.pop("dt", None)
    routes.sort(key=lambda r: -r["km"])
    # скільки ланок лишилось поза маршрутами — це число має бути на очах,
    # інакше карта виглядає повнішою за дані
    in_routes = sum(len(r["legs"]) for r in routes)
    return routes, {"hops": len(hops), "in_routes": in_routes,
                    "tracks": len(point_tracks(events)), "extended": extended,
                    "dropped": dropped}


if __name__ == "__main__":
    import json
    import sys
    import collections

    raid = json.load(open(sys.argv[1], encoding="utf-8"))
    rs, meta = build(raid)
    dec = sum(l == "declared" for r in rs for l in r["legs"])
    print(f"маршрутів: {len(rs)}   ланок: {meta['in_routes']}   "
          f"заявлених ланок усього: {meta['hops']}   підтверджено: {dec}")
    print("точок у маршруті:", sorted(collections.Counter(r["n"] for r in rs).items()))
    for r in rs[:10]:
        v = f"{r['kmh']} км/год" if r["kmh"] else "—"
        print(f"  {r['src']:10} {r['n']:2} точок {r['km']:5} км "
              f"{r['t0']}-{r['t1']} {v:>10}")
