#!/usr/bin/env python3
"""Підказки з даних для редактора: маршрути ночі у night.js.

Редактор — інструмент оператора, а не генератор. Але оператор не має
згадувати з голови, де що літало: цей файл кладе на карту напівпрозорий шар
зі шляхами, зшитими з наших повідомлень (tgmine/routes.py). Клік по шляху
переводить його в редагований маршрут, далі оператор веде лінію сам.

Запуск:  python3 mapper/mknight.py raid_2026-08-01.json
         (raid-файл робиться командою `python3 raid.py <дата>`)
"""
import collections
import json
import math
import os
import re
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from tgmine import routes as RT
import uknames as UN                    # українські назви місць (див. там)


def _namer(raid):
    """Українські назви місць ночі — один прохід газетира на ніч, спільний
    для збиттів, курсів і фіксацій (`mapper/uknames.py`)."""
    nm = raid.get("_uk")
    if nm is None:
        # Разом з іншими місцями поста (`also`): без них їхні підписи йшли
        # запасними правилами, а не з Wikidata — перевірка 22.09.2026: 59 з
        # 268 назв ночі гірші («Можаиський район», «Гулькевічи»).
        nm = raid["_uk"] = UN.Names(
            {(e["place"], e["lat"], e["lon"]) for e in raid["events"]
             if e.get("place") and e.get("lat")}
            | {(a[0], a[1], a[2]) for e in raid["events"] for a in (e.get("also") or []) if a[0]}
            | {(g[0], g[1], g[2]) for e in raid["events"] for g in (e.get("legs") or []) if g[0]}
            | {(g[4], g[5], g[6]) for e in raid["events"] for g in (e.get("legs") or []) if g[4]})
    return nm


def strikes(raid):
    """Збиття й робота ППО за ніч — як заготовки обʼєктів для оператора.

    Це НЕ влучання: канали моніторять підліт, а не наслідки. Тому в редактор
    вони йдуть із власним підписом «збиття» і датою, а не як вогники на
    цілях. Оператор вирішує, що з них лишити.

    Події, геокодовані в центр області, не беремо: 30 тисяч кв. км не є
    місцем, і ставити туди позначку означає вигадати точність.
    """
    by = {}
    for e in raid["events"]:
        if e.get("kind") not in ("збиття", "ППО"):
            continue
        if e.get("scope") != "точка" or not e.get("lat"):
            continue
        if e.get("geo_conf") in ("centroid", "region-snap"):
            continue
        key = (round(e["lat"], 2), round(e["lon"], 2))
        b = by.setdefault(key, {"la": key[0], "lo": key[1], "n": 0,
                                "place": e.get("place") or "", "t": e.get("hhmm", ""),
                                "lat": e["lat"], "lon": e["lon"],
                                "kinds": collections.Counter(),
                                "types": collections.Counter(), "src": []})
        b["n"] += 1
        b["kinds"][e["kind"]] += 1
        # Тип засобу (store.utype_of): «Фламінго», «ракета», «Хорнет»… Без
        # нього збиття ракети на карті виглядало як збиття дрона.
        if e.get("utype"):
            b["types"][e["utype"]] += 1
        # Джерело позначки: адреса повідомлення, час і канал. Без цього
        # оператор бачив кружок на карті й не мав чим його перевірити, а
        # позначка без джерела — це твердження без підстави.
        if e.get("url"):
            b["src"].append({"u": e["url"], "t": e.get("hhmm", ""),
                             "k": e.get("kind", ""), "ty": e.get("utype")})
    out, nm = [], _namer(raid)
    for b in by.values():
        name = nm.place(b["place"], b["lat"], b["lon"])
        kind = b["kinds"].most_common(1)[0][0]
        # Більше восьми посилань на одну позначку читати ніхто не буде, а
        # вага файла росте на кожну ніч. Скільки їх насправді — каже `n`.
        out.append({"la": b["la"], "lo": b["lo"], "n": b["n"], "place": name,
                    "kind": kind, "types": dict(b["types"]),
                    "t": b["t"], "src": b["src"][:8]})
    out.sort(key=lambda s: -s["n"])
    return out


def bearings(raid):
    """Курси словами за ніч — заготовки стрілок для оператора.

    «Пролёт БПЛА на северо-восток» — це не гіпотеза зшивання, а те, що
    канал написав. У ніч ідуть лише фіксації з координатою в місці (не
    центр області) і з курсом у тексті: 5.6% точкових подій, приблизно
    16 на добу. Одне місце з одним курсом за ніч згортається в одну стрілку
    з лічильником, як і позначки збиття.
    """
    by = {}
    for e in raid["events"]:
        if e.get("bearing") is None or e.get("scope") != "точка" or not e.get("lat"):
            continue
        if e.get("geo_conf") in ("centroid", "region-snap"):
            continue
        key = (round(e["lat"], 2), round(e["lon"], 2), int(e["bearing"]))
        b = by.setdefault(key, {"la": key[0], "lo": key[1], "deg": key[2], "n": 0,
                                "place": e.get("place") or "", "t": e.get("hhmm", ""),
                                "lat": e["lat"], "lon": e["lon"],
                                "src": []})
        b["n"] += 1
        if e.get("url"):
            b["src"].append({"u": e["url"], "t": e.get("hhmm", ""),
                             "k": e.get("kind", ""), "ty": e.get("utype")})
    out, nm = [], _namer(raid)
    for b in by.values():
        name = nm.place(b["place"], b["lat"], b["lon"])
        out.append({"la": b["la"], "lo": b["lo"], "deg": b["deg"], "n": b["n"],
                    "place": name, "t": b["t"], "src": b["src"][:8]})
    out += toward_regions(raid)
    out.sort(key=lambda s: (s["t"], -s["n"]))
    return out


#: Довжина стрілки «на область» — символ напрямку, не дальність, як і
#: 35 км курсу словами; але не довша за половину шляху до якоря області,
#: щоб вістря не лягало в саму область (інакше крізь сусідню ліг би шлях,
#: якого ніхто не бачив — BACKLOG §16.10).
TOWARD_KM = 60.0
#: Ближче до якоря області — стрілка на область беззмістовна.
TOWARD_MIN_KM = 40.0
#: Хвости ближче за це й одна область за ніч — один конус. 30 км давало
#: два десятки конусів на ніч, і вони зливались у суцільну пляму (знімок
#: 22.09.2026); 100 км лишає по одному на напрямок заходу.
TOWARD_MERGE_KM = 100.0


#: Конус «кудись у цю область»: розхил — кутовий розмір самої області з
#: місця спостереження, не менший і не більший за ці межі (щоб вузький
#: язик не читався як «точно туди», а широкий не накривав пів театру).
CONE_MIN_DEG, CONE_MAX_DEG = 4.0, 30.0
#: Санітарна межа довжини: далі театру не буває.
CONE_MAX_KM = 700.0
#: Площа конуса, км². Обмежувати треба саме ПЛОЩУ, а не довжину: межа
#: довжини 260 км лишала конус, який до своєї області не доходив узагалі —
#: замір 22.09.2026 на 122 конусах пʼяти ночей знайшов 12 таких («→ Калузька»
#: з Брянщини лежав у Брянській на 84% і в Калузькій на 0%). Далека область
#: тепер дістає довгу ВУЗЬКУ стрілку, а не широкий віяловий обрубок.
CONE_AREA_KM2 = 26000.0


def _cone(la, lo, rings, anc):
    """[[широта, довгота], …] — многокутник конуса від (la, lo) в бік
    області: вершина в місці, далі дуга кутовим розміром області.

    Рішення оператора 22.09.2026: невідомий напрямок — не лінія в центр
    області (це читається як «точно туди»), а конус, що входить в область
    і накриває її.
    """
    if rings:
        pts = [p for r in rings for p in r]
    else:
        pts = [anc]
    brs = [RT.bearing((la, lo), (p[0], p[1])) for p in pts]
    c0 = RT.bearing((la, lo), tuple(anc))
    devs = [((b - c0 + 540) % 360) - 180 for b in brs]
    mid = c0 + (max(devs) + min(devs)) / 2
    # Довжина: ДІЙТИ до області й увійти в неї приблизно до середини.
    far = max(RT.hav((la, lo), (p[0], p[1])) for p in pts) if rings else RT.hav((la, lo), tuple(anc))
    near = min(RT.hav((la, lo), (p[0], p[1])) for p in pts) if rings else far
    rad = min(CONE_MAX_KM, max(near * 1.02, near + (far - near) * 0.45))
    # Розхил: кутовий розмір області, але площа під стелею. Далекий конус
    # звужується сам — довжину різати не можна, інакше стрілка вказує в
    # порожнє місце.
    half = max(CONE_MIN_DEG, min(CONE_MAX_DEG, (max(devs) - min(devs)) / 2))
    half = max(CONE_MIN_DEG, min(half, CONE_AREA_KM2 * 180.0 / (math.pi * rad * rad)))
    out = [[round(la, 3), round(lo, 3)]]
    n = 9
    for i in range(n + 1):
        b = math.radians(mid - half + 2 * half * i / n)
        dla = rad * math.cos(b) / 111.0
        dlo = rad * math.sin(b) / (111.0 * math.cos(math.radians(la)))
        out.append([round(la + dla, 3), round(lo + dlo, 3)])
    return out


def toward_regions(raid):
    """Жирні стрілки «звідси — на область» з ланок руху (`legs`, v26).

    Рішення оператора 22.09.2026: невідомий шлях — жирна стрілка напрямку,
    а не лінія. Ланка «Юдановка … далее на Тамбовскую область» знає місце й
    ОБЛАСТЬ, але не шлях: стрілка стоїть хвостом на місці з того самого
    поста, дивиться на якір області (полюс недосяжності, як у чіпів
    тривог) і до неї не дотягується. Хвіст уже в цій області — стрілки
    нема. Джерело ланки — ціла область — теж ні: хвіст має бути місцем.
    """
    import mkreglabels as RL
    root = os.path.dirname(HERE)
    if "regions" not in _CACHE:
        _CACHE["regions"] = json.load(open(os.path.join(root, "regions.json"), encoding="utf-8"))
    regions = _CACHE["regions"]
    from tgmine.labels import region_label
    by = {}
    for e in raid["events"]:
        legs = e.get("legs") or []
        dst_of = {(round(g[5], 4), round(g[6], 4)): g for g in legs}
        for sn, sla, slo, sar, dn, dla, dlo, dar in legs:
            if not dar:
                continue
            # Хвіст — місце, де бачили, а не ціль попередньої ланки: у
            # ланцюзі «X … на Анна, далее на Тамбовскую область» ланка до
            # області починається з Анни, де нікого не бачили. Ідемо ланцюгом
            # назад до кореня (X); корінь — ціла область — стрілки нема.
            # Перевірка 22.09.2026: так стояло 39 з 373 стрілок.
            # Назад — лише доки попередній старт є МІСЦЕМ: «Тамбовская
            # область … через Токарёвский район … на Рязанскую» — перше
            # місце тут Токарьовський район, і дійти до області означало б
            # прибрати правильну стрілку.
            seen = set()
            while (round(sla, 4), round(slo, 4)) in dst_of and (sla, slo) not in seen:
                seen.add((sla, slo))
                g = dst_of[(round(sla, 4), round(slo, 4))]
                if g[3]:
                    break
                sn, sla, slo, sar = g[0], g[1], g[2], g[3]
            if sar:
                continue
            rings = regions.get(dn)
            if rings:
                if any(RL.inside(sla, slo, r) for r in rings):
                    continue
                if ("anchor", dn) not in _CACHE:
                    _CACHE[("anchor", dn)] = RL.anchor(max(rings, key=RL.area))
                anc = _CACHE[("anchor", dn)] or (dla, dlo)
            else:
                anc = (dla, dlo)
            dist = RT.hav((sla, slo), tuple(anc))
            if dist < TOWARD_MIN_KM:
                continue
            cone = _cone(sla, slo, rings, anc)
            # Один хвіст (у межах TOWARD_MERGE_KM) і одна область — одна
            # стрілка з лічильником. Сітка тут не годиться: сусідні села по
            # різні боки межі клітинки давали три паралельні стрілки «→
            # Воронезька» (перевірка на ночі 28.07.2026).
            key = next((k for k, v in by.items() if v["to"] == dn and
                        RT.hav((v["la"], v["lo"]), (sla, slo)) <= TOWARD_MERGE_KM), None)
            if key is None:
                key = (len(by), dn)
            b = by.setdefault(key, {"la": round(sla, 3), "lo": round(slo, 3), "to": dn,
                                    "dla": dla, "dlo": dlo,
                                    "deg": round(RT.bearing((sla, slo), tuple(anc))),
                                    "km": round(min(TOWARD_KM, dist / 2)),
                                    "cone": cone, "n": 0,
                                    "place": sn, "t": e.get("hhmm", ""), "ts": [], "src": []})
            b["n"] += 1
            if e.get("hhmm"):
                b["ts"].append(e["hhmm"])
            if e.get("url"):
                b["src"].append({"u": e["url"], "t": e.get("hhmm", ""),
                                 "k": e.get("kind", ""), "ty": e.get("utype")})

    def night_key(hhmm):
        h = int(hhmm[:2])
        return (h + 24 if h < 12 else h, hhmm)
    out, nm = [], _namer(raid)
    for b in by.values():
        # Злита стрілка живе від першого до останнього повідомлення: фільтр
        # годин у редакторі дивиться на t0..t1, і з одним часом стрілка
        # ховалась у пізніші години (48 з 81 злитих охоплювали кілька годин).
        ts = sorted(b.pop("ts"), key=night_key)
        if ts:
            b["t"], b["t1"] = ts[0], ts[-1]
        # Ключ конфігу («Тамбовська») — таблицею областей; назва GeoNames
        # («Pskov Oblast», «Kharkiv Oblast») — словником українських назв.
        to = b["to"]
        to = region_label(to) if re.search(r"[а-яіїєґ]", to, re.I) else nm.place(to, b["dla"], b["dlo"])
        out.append({k: v for k, v in b.items() if k not in ("dla", "dlo")}
                   | {"place": nm.place(b["place"], b["la"], b["lo"]), "to": to,
                      "src": b["src"][:8]})
    return out


# Латинські «Okrug», «Oblast», «Miskrada», «Hromada» — теж площа: назви
# GeoNames англійські, і «Gorodskoy Okrug Chekhov», «Mikhaylovka Urban Okrug»
# (46 подій) малювались крапкою (рецензія 21 вересня 2026).
AREA_NAME = re.compile(r"\b(?:rayon|raion|district|okrug|oblast|miskrada|hromada)\b|"
                       r"округ|район|\bГО\b", re.I)


#: Тривога в названому місці — свідчення, коли вона звʼязана з рухом.
#: Заміряно на 61 добі (18 214 тривог із місцем, не центр області):
#: справжня фіксація в межах 20 км і ±30 хв є у 23%, а при зсуві часу на
#: 6 год — у 3.9%, тобто ~17% таких звʼязків випадкові. Ширші пороги
#: (30 км/45 хв — 23% випадкових, 40/60 — 29%) тягнуть шум.
ALERT_LINK_KM, ALERT_LINK_MIN = 20.0, 30.0
_MOVE = re.compile(r"направлени|в\s+сторону|далее|курсом|\bна\s+(?:север|юг|запад|восток)", re.I)


def _linked_alerts(events):
    """id() тривог, що йдуть у шар свідчень: місце — НП чи район (не центр
    області), і або сам пост каже, куди летить («Выгоничский район в
    направлении Брянск опасность»), або поруч у часі й просторі є справжнє
    спостереження. Рішення оператора 22.09.2026: небезпеку не виносити
    окремою позначкою, а звʼязувати з картиною дронів — у редакторі вона
    стає тією ж «фіксацією», тип за замовчуванням БпЛА."""
    obs = [e for e in events if e.get("scope") == "точка" and e.get("lat") and e.get("t")
           and e.get("kind") in ("фіксація", "ППО", "збиття", "вибух")
           and e.get("geo_conf") not in ("centroid", "region-snap")]
    for o in obs:
        o["_dt"] = datetime.fromisoformat(o["t"])
    out = set()
    for e in events:
        if e.get("kind") != "тривога" or not e.get("lat") or e.get("aim"):
            continue
        if e.get("geo_conf") in ("centroid", "region-snap", None):
            continue
        if _MOVE.search(e.get("text") or ""):
            out.add(id(e))
            continue
        if not e.get("t"):
            continue
        t = datetime.fromisoformat(e["t"])
        k = math.cos(math.radians(e["lat"]))
        for o in obs:
            if abs((o["_dt"] - t).total_seconds()) <= ALERT_LINK_MIN * 60 and \
                    111.2 * math.hypot(o["lat"] - e["lat"], (o["lon"] - e["lon"]) * k) <= ALERT_LINK_KM:
                out.add(id(e))
                break
    for o in obs:
        o.pop("_dt", None)
    return out


def sightings(raid):
    """Усі фіксації ночі, згорнуті по місцю — шар свідчень для оператора.

    Навіщо. Досі в ніч ішли лише точки, які алгоритм зшив у маршрути, і
    оператор бачив нашу інтерпретацію замість даних: заміряно, 60–75% місць
    ночі не торкався жоден маршрут-підказка. Тут — кожне місце, де тієї
    ночі щось бачили: скільки повідомлень, коли (усі часи, бо фільтр годин
    у редакторі рахує саме їх), чого саме (фіксація, ППО, збиття), і
    посилання.

    Третина точок стоїть не на селі, а на центрі району («Рыльский район»)
    — 33% на 7 ночах. Крапка там бреше так само, як на центрі області,
    тому такі місця несуть `area`: «район», або «здогад» для збігу за
    населенням без області (conf global). Редактор малює їх порожнім
    кільцем, а не крапкою.
    """
    by = {}
    linked = _linked_alerts(raid["events"])
    for e in raid["events"]:
        if not e.get("lat"):
            continue
        if id(e) not in linked and (e.get("scope") != "точка" or e.get("kind") not in (
                "фіксація", "пуск", "ППО", "збиття", "вибух")):
            continue
        # Центр області крапкою бреше, тож такі місця сюди не йдуть — КРІМ
        # пуску. Пуск стоїть на джерелі, і найчастіше джерело — ціла область:
        # «Пуски БПЛА от Одесской области». Без винятку найчастіший вид пуску
        # зник би з редактора зовсім. Малюється він як площа — порожнім
        # кільцем із позначкою «область», як центр району.
        launch_area = e.get("kind") == "пуск" and e.get("geo_conf") == "centroid"
        if e.get("geo_conf") in ("centroid", "region-snap") and not launch_area:
            continue
        # Крапка події і решта місць «тут» того ж поста (`also`, конвеєр
        # v24): «Курск / Курчатов / Дмитриев / Тревога» — три місця, а не
        # одне. Кожне — окреме свідчення з тими самими видом, часом і
        # посиланням.
        # Тривога привʼязана до руху своєю крапкою (`_linked_alerts`), а решта
        # міст її переліку окремо не перевірені — тож для тривоги лише крапка.
        also = [] if id(e) in linked else list(e.get("also") or [])
        for pt in [None] + also:
            _add_sighting(by, e, pt, launch_area)
    return _finish_sightings(raid, by)


def _add_sighting(by, e, pt, launch_area):
    if pt is None:
        la, lo, place, area = e["lat"], e["lon"], e.get("place") or "", None
    else:
        place, la, lo, area = pt[0] or "", pt[1], pt[2], ("район" if pt[3] else None)
    if True:
        key = (round(la, 2), round(lo, 2))
        b = by.setdefault(key, {"la": key[0], "lo": key[1], "n": 0,
                                "place": place, "lat": la, "lon": lo,
                                "kinds": collections.Counter(), "ts": [],
                                "types": collections.Counter(),
                                "degs": collections.Counter(), "src": [],
                                "area": ""})
        b["n"] += 1
        # Місце — ЦІЛЬ руху, лише якщо так про нього сказано в усіх
        # повідомленнях: хоч одне «тут бачили» робить його місцем.
        b["aim"] = b.get("aim", True) and bool(e.get("aim")) and pt is None
        b["kinds"][e["kind"]] += 1
        if e.get("utype"):
            b["types"][e["utype"]] += 1
        if e.get("hhmm"):
            b["ts"].append(e["hhmm"])
        if e.get("bearing") is not None:
            b["degs"][int(e["bearing"])] += 1
        if e.get("url"):
            b["src"].append({"u": e["url"], "t": e.get("hhmm", ""),
                             "k": e.get("kind", ""), "ty": e.get("utype")})
        if pt is not None:
            if area or AREA_NAME.search(place):
                b["area"] = "район"
        elif launch_area:
            b["area"] = "область"
        # `area` із сховища (конвеєр v20) — район, зокрема розвʼязаний своїм
        # містом; назва — для сховищ, зібраних раніше.
        elif e.get("area") or AREA_NAME.search(e.get("place") or ""):
            b["area"] = "район"
        elif e.get("geo_conf") == "global" and not b["area"]:
            b["area"] = "здогад"


def _finish_sightings(raid, by):
    # Ніч іде через північ: 23:45 стоїть ПЕРЕД 00:10. Рядкове сортування
    # ставило їх навпаки, і картка казала «00:01–23:45» про одну ніч.
    # Доба тут — від 12:00 до 12:00, як скрізь у проєкті.
    def night_key(hhmm):
        h = int(hhmm[:2])
        return (h + 24 if h < 12 else h, hhmm)

    out, nm = [], _namer(raid)
    for b in by.values():
        name = nm.place(b["place"], b["lat"], b["lon"])
        ts = sorted(b["ts"], key=night_key)
        out.append({"la": b["la"], "lo": b["lo"], "n": b["n"], "place": name,
                    "kinds": dict(b["kinds"]), "types": dict(b["types"]), "ts": ts,
                    "t0": ts[0] if ts else "", "t1": ts[-1] if ts else "",
                    "deg": b["degs"].most_common(1)[0][0] if b["degs"] else None,
                    "area": b["area"], "aim": b.get("aim", False),
                    "src": b["src"][:8]})
    out.sort(key=lambda s: -s["n"])
    return out


#: Тривога, що покриває стільки годин ночі, неінформативна: це фронт і ТОТ,
#: де вона висить з полудня до ранку. Заміряно на 8 ночах: ≥12 год у ≥5 з 8
#: ночей мають рівно 11 областей (фронт, чотири ТОТ, Орловська); тил — 0–8.
ALERT_MUTED_HOURS = 12.0
#: Старт тривоги — перша тривога після такої тиші. Відбій перед ним є лише
#: у чверті випадків (56 із 223 проміжків ≥3 год), тож відбій — позначка
#: «після відбою», а не умова. Нагадування «действует тревога» йдуть
#: щогодини й при меншому порозі давали б хибні старти.
ALERT_GAP_HOURS = 3.0
#: Тривога без відбою вважається чинною стільки хвилин — для покриття.
ALERT_HOLD_MIN = 90
#: Нагадування про чинну тривогу — не старт.
ALERT_REMINDER = re.compile(r"напоминаем|сохраняется|продолжается|действует|"
                            r"остаётся|остается|повторно", re.I)


_CACHE: dict = {}


def alerts(raid):
    """Хронологія стартів тривог у тилу — «куди пішли далі» для оператора.

    Навіщо. Крапки й підказки відповідають, звідки зайшли; у глибокому тилу
    фіксацій майже нема, а стрілку треба довести. Заміряно на ночі 8 вересня
    2026: у тилу 47 стартів тривоги, у 20 областях з них — жодної фіксації;
    послідовність стартів (Мордовія 00:04 → Волгоградська 00:14 → …
    → Башкортостан 04:37 → Перм 06:39 → ХМАО 09:32) і є маршрут нальоту.

    Що рахується. Область — КОЖНА, названа в тексті тривоги, а не лише перша
    (13% тривог називають 2–6 областей). Старт — перша тривога після
    ALERT_GAP_HOURS тиші; «після відбою» — якщо між нею й попередньою був
    відбій. Область із покриттям ≥ ALERT_MUTED_HOURS за ніч іде в `muted`:
    редактор її не показує, бо там тривога не несе нічого. `silent` — за ніч
    у області не було жодної фіксації в точці: саме там оператор інакше має
    порожнє місце. Якір — той самий полюс недосяжності, що в підписів
    областей, тож чіп стане поруч із назвою.
    """
    from datetime import datetime, timedelta
    sys.path.insert(0, os.path.dirname(HERE))
    from tgmine import extract as E
    import mkreglabels as RL
    root = os.path.dirname(HERE)
    # Конфіг, полігони й якорі однакові для всіх ночей; на повній перебудові
    # архіву (158 ночей) якорі самі коштували ~2 с на ніч.
    if "cfg" not in _CACHE:
        _CACHE["cfg"] = E.Config.load(os.path.join(root, "configs", "ru-monitor.yaml"))
        _CACHE["regions"] = json.load(open(os.path.join(root, "regions.json"), encoding="utf-8"))
    cfg, regions = _CACHE["cfg"], _CACHE["regions"]

    def night_key(hhmm):
        h = int(hhmm[:2])
        return (h + 24 if h < 12 else h, hhmm)

    from tgmine import store as ST
    msgs = collections.defaultdict(list)          # регіон -> [(t, kind, url, hhmm, reminder)]
    for e in raid["events"]:
        if e.get("scope") != "область" or e.get("kind") not in ("тривога", "відбій"):
            continue
        t = datetime.fromisoformat(e["t"])
        text = e.get("text", "")
        # Лише перший збіг кожної області, як до BACKLOG §7: повторний після
        # «от» ставив відріз і зрізав області тривоги до кінця речення.
        ents = [x for x in E.entities_of(text, cfg)
                if x["type"] == "регіон" and not x.get("extra")]
        # «Татарстан — опасность по БПЛА от Ульяновской и Самарской областей»:
        # область після «от», яка не перша в пості, — джерело, а не місце
        # тривоги. Те саме правило, що для крапки (store.SRC_BEFORE);
        # спіймано перевіркою: 145 із 4113 тривог за 10 діб.
        first = min((x["pos"] for x in ents if x.get("pos") is not None), default=None)
        # Знайти перше джерело («от Ульяновской») і відрізати все до кінця
        # речення: «и Самарской областей» — продовження переліку джерел.
        cut = None
        for x in ents:
            pos = x.get("pos") or 0
            if pos != first and ST.SRC_BEFORE.search(text[max(0, pos - 24):pos]):
                cut = pos
                break
        end = len(text)
        if cut is not None:
            for sep in (".", "\n", "/", "📡"):
                i = text.find(sep, cut)
                if i != -1:
                    end = min(end, i)
        regs = []
        for x in ents:
            pos = x.get("pos") or 0
            if cut is not None and cut <= pos < end:
                continue
            if x["value"] not in regs:
                regs.append(x["value"])
        reminder = bool(ALERT_REMINDER.search(text))
        for r in regs:
            msgs[r].append((t, e["kind"], e.get("url", ""), e.get("hhmm", ""),
                            reminder, e.get("utype")))
    fixes = collections.Counter(
        e.get("region") for e in raid["events"]
        if e.get("scope") == "точка" and e.get("lat") and e.get("region")
        and e.get("geo_conf") not in ("centroid", "region-snap"))
    onsets, cover, muted, anchors = [], {}, [], {}
    hold, gap = timedelta(minutes=ALERT_HOLD_MIN), timedelta(hours=ALERT_GAP_HOURS)
    for reg, lst in msgs.items():
        lst.sort()
        # покриття: обʼєднання вікон [тривога, відбій або +hold]
        cov, start, last = timedelta(0), None, None
        for t, k, _, _, _, _ in lst:
            if k == "тривога":
                if start is None:
                    start = t
                last = t
            elif start is not None:
                cov += max(timedelta(0), min(t, last + hold) - start)
                start = None
        if start is not None:
            cov += (last + hold) - start
        hours = round(cov.total_seconds() / 3600, 1)
        cover[reg] = hours
        if hours >= ALERT_MUTED_HOURS:
            muted.append(reg)
        prev, seen_otboy = None, False
        for t, k, url, hhmm, reminder, ty in lst:
            if k == "відбій":
                seen_otboy = prev is not None
                continue
            # Нагадування («тревога сохраняется», «напоминаем») — не старт,
            # а свідчення, що тривога триває: воно лише продовжує її.
            # 397 із 4113 тривог за 10 діб; як перше повідомлення області
            # воно означає, що старт був ще до початку доби.
            if reminder:
                if prev is not None:
                    prev, seen_otboy = t, False
                continue
            if prev is None or (t - prev) >= gap:
                onsets.append({"t": hhmm, "reg": reg,
                               "name": (RL.NAMES.get(reg) or (reg, reg))[0],
                               "otboy": bool(seen_otboy and prev is not None),
                               "fix": fixes.get(reg, 0), "silent": not fixes.get(reg),
                               # тип із тексту тривоги: «ракета», «Фламінго»,
                               # «БпЛА» — саме він каже, ЩО пішло далі в тил
                               "ty": ty,
                               "src": [{"u": url, "t": hhmm, "k": k, "ty": ty}]
                                      if url else []})
            prev, seen_otboy = t, False
        rings = regions.get(reg)
        if rings:
            if ("anchor", reg) not in _CACHE:
                _CACHE[("anchor", reg)] = RL.anchor(max(rings, key=RL.area))
            pt = _CACHE[("anchor", reg)]
            if pt:
                anchors[reg] = [round(pt[0], 3), round(pt[1], 3)]
    onsets.sort(key=lambda o: (night_key(o["t"]), o["reg"]))
    return {"onsets": onsets, "muted": sorted(muted), "cover": cover, "anchors": anchors}


def with_bridges(raid, rs):
    """Маршрути ночі, зведені містками «звичний коридор» (`linker`).

    Рішення оператора 22.09.2026: невідома частина шляху — жирним
    напівпрозорим відрізком у ТІЙ САМІЙ лінії, щоб ніч читалась однією
    картиною. Місток — ланка `bridge` між кінцем одного фрагмента й
    початком наступного; `bridges[k] = {"at": i, "nights": n}` — ланка i і
    у скількох попередніх ночах коридор траплявся. Твердження — «потік ішов
    звичним коридором», а не «та сама група» (див. `linker`).
    """
    from tgmine import linker as LK
    links = LK.link_corridors(rs, LK.Prior(raid.get("date") or "9999"))
    if not links:
        return rs
    nights = {(i, j): n for i, j, n in links}
    out = []
    for ch in LK.chains(len(rs), links):
        if len(ch) == 1:
            out.append(rs[ch[0]])
            continue
        first, last = rs[ch[0]], rs[ch[-1]]
        m = dict(first)
        pts, legs, bridges = list(first["pts"]), list(first.get("legs") or []), []
        for a, b in zip(ch, ch[1:]):
            bridges.append({"at": len(pts) - 1, "nights": nights[(a, b)]})
            legs.append("bridge")
            pts += rs[b]["pts"]
            legs += list(rs[b].get("legs") or [])
        # Поля цілого маршруту — з УСІХ фрагментів, а не з першого: перша
        # версія брала `conf` і тип першого, і в 22 із 65 ланцюгів пʼяти ночей
        # сильний фрагмент ховався фільтром «без слабких», бо першим стояв
        # слабкий. Упевненість — найсильніша (підказку не ховаємо, якщо в ній
        # є сильна частина; ланки зберігають свій вигляд), тип — перша
        # названа модель, бо `LK.compatible` не пускає двох різних.
        parts = [rs[k] for k in ch]
        typed = next((r for r in parts if r.get("u") not in LK.GENERIC_U),
                     next((r for r in parts if r.get("u")), first))
        m.update(pts=pts, legs=legs, bridges=bridges, t1=last.get("t1"), n=len(pts),
                 km=sum(r.get("km") or 0 for r in parts),
                 claims=max(r.get("claims") or 1 for r in parts),
                 conf=max((r.get("conf") or "ok" for r in parts),
                          key={"weak": 0, "ok": 1, "strong": 2}.get),
                 u=typed.get("u"), k=typed.get("k", first.get("k")),
                 extended=any(r.get("extended") for r in parts),
                 hours=round(sum(r.get("hours") or 0 for r in parts), 1), kmh=None)
        out.append(m)
    return out


def main(src, out=None):
    out = out or os.path.join(os.path.dirname(os.path.abspath(__file__)), "night.js")
    raid = json.load(open(src, encoding="utf-8"))
    rs, meta = RT.build(raid)
    rs = with_bridges(raid, rs)
    st = strikes(raid)
    br = bearings(raid)
    sg = sightings(raid)
    al = alerts(raid)
    dec = sum(l == "declared" for r in rs for l in r["legs"])
    open(out, "w", encoding="utf-8").write(
        "window.NIGHT=" + json.dumps({"date": raid.get("date"), "routes": rs,
                                      "strikes": st, "bearings": br,
                                      "sightings": sg, "alerts": al},
                                     ensure_ascii=False, separators=(",", ":")) + ";\n")
    rear = [o for o in al["onsets"] if o["reg"] not in al["muted"]]
    print(f"{raid.get('date')}: маршрутів {len(rs)}, ланок {meta['in_routes']}, "
          f"з них заявлено текстом {dec}, збиття/ППО у точці {len(st)}, "
          f"курсів словами {len(br)}, місць із фіксаціями {len(sg)}, "
          f"стартів тривоги в тилу {len(rear)} (німих {sum(o['silent'] for o in rear)})")
    print("->", out)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    main(*sys.argv[1:])
