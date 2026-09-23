#!/usr/bin/env python3
"""Тягне військові та промислові обʼєкти з OSM через Overpass.

Не «все підряд» як Wikimapia, а курований набір категорій, кожна фільтрується
окремо. Джерело — OpenStreetMap (ODbL), машиночитне, з чіткими тегами.

Європейська частина РФ + ТОТ бʼється на плитки, бо один запит на всю область
Overpass відхиляє за таймаутом.

  python3 fetch_targets.py            # завантажити все
  python3 fetch_targets.py --stat     # що вже завантажено
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

OUT = Path("targets.json")
UA = {"User-Agent": "tgmine/1.0 (strike-monitor; contact via github)"}
ENDPOINTS = ["https://overpass-api.de/api/interpreter",
             "https://overpass.kumi.systems/api/interpreter"]

# категорія -> (колір, OSM-фільтри). Фільтр — рядок Overpass QL без обгортки.
CATEGORIES = {
    "airfield": ("#ff5066", [
        'nwr["military"="airfield"]', 'nwr["aeroway"="aerodrome"]["military"]',
        'nwr["aeroway"="aerodrome"]["aerodrome:type"="military"]']),
    "military_base": ("#ff8a1f", [
        'nwr["military"="base"]', 'nwr["landuse"="military"]',
        'nwr["military"="barracks"]']),
    "range": ("#c98a3a", [
        'nwr["military"="training_area"]', 'nwr["military"="range"]',
        'nwr["military"="danger_area"]']),
    "ammo_depot": ("#e0457a", [
        'nwr["military"="depot"]', 'nwr["military"="ammunition"]']),
    "naval": ("#4aa3ff", [
        'nwr["military"="naval_base"]', 'nwr["landuse"="port"]["military"]']),
    # Лише переробка, не видобуток. Самі запити живуть у IND_Q нижче (цей
    # перелік — колір і документація): свердловини `petroleum_well` там
    # стояли й до 9 вересня 2026 мовчки падали за таймаутом, тож у переліку
    # не було жодного OSM-НПЗ. Коли пройшли — принесли 13 468 обʼєктів, з
    # них 4126 без назви й тисячі свердловин «К2», «К13»: кущі нафтопромислів
    # ХМАО. Свердловина — не ціль класу «НПЗ»; НПЗ у РФ ведуться курованим
    # списком (`refineries.py`), OSM дає доповнення за назвою (`classify`).
    "refinery": ("#ffd23f", [
        'nwr["man_made"="works"]["name"~"НПЗ|нефтеперераб",i]',
        'nwr["industrial"="refinery"]']),
    "fuel_depot": ("#ffa03f", [
        'nwr["landuse"="industrial"]["name"~"нефтебаз|нефтехран|ГСМ|топлив",i]',
        'nwr["man_made"="storage_tank"]["content"~"oil|fuel|diesel",i]']),
    "chemical": ("#a78bfa", [
        'nwr["industry"="chemical"]',
        'nwr["man_made"="works"]["product"~"chemical|explosive",i]',
        'nwr["man_made"="works"]["name"~"химич|порох|взрывч|боеприпас",i]']),
    "defense_plant": ("#ff6b9d", [
        'nwr["man_made"="works"]["name"~"завод.*(оборон|авиа|ракет|танк|двигат|радиозавод)",i]',
        'nwr["industry"~"military|arms|defence",i]']),
}

# Плитки: європейська частина РФ + прикордоння + ТОТ. (S, W, N, E)
TILES = [
    (44.0, 32.0, 50.0, 40.0),   # південь: Крим, Краснодар, Ростов, ТОТ
    (50.0, 30.0, 56.0, 40.0),   # центр: Москва, Тула, Воронеж, Бєлгород
    (44.0, 40.0, 50.0, 48.0),   # південний схід: Волгоград, Астрахань
    (50.0, 40.0, 56.0, 48.0),   # схід: Саратов, Пенза, Самара
    (52.0, 48.0, 58.0, 60.0),   # Урал: Уфа, Оренбург, Іжевськ
    (56.0, 30.0, 61.0, 44.0),   # північ: Пітер, Ярославль, Нижній
    # Далі за Урал. До 9 вересня 2026 плитки закінчувались на 60° сходу, і
    # удар по Новоуренгойському ЗПКТ (76.6°) не мав до чого привʼязатись.
    # Плитки того самого розміру, що й вище; щільність обʼєктів у Сибіру
    # нижча, тож запити легші.
    (52.0, 60.0, 58.0, 70.0),   # Челябінськ, Курган, Тюмень
    (58.0, 48.0, 64.0, 60.0),   # Перм, північ Свердловської
    (58.0, 60.0, 64.0, 70.0),   # Тагіл, Тобольськ, Ханти-Мансійськ
    (52.0, 70.0, 58.0, 80.0),   # Омськ
    (58.0, 70.0, 64.0, 80.0),   # Сургут, Нижньовартовськ, Ноябрськ
    (64.0, 64.0, 70.0, 80.0),   # Салехард, Надим, Новий Уренгой
    # Діри, знайдені 23 вересня 2026, коли конфіг дізнався 17 нових
    # субʼєктів: у Чебоксарах, Пскові, Грозному, Моздоку, Мурманську й
    # Калінінграді не було жодного обʼєкта. Плитки вище сходились кутами й
    # лишали між собою смуги (56–61° пн. × 44–48° сх.), а північ, Кавказ
    # нижче 44° і захід за 30° сх. не покривались узагалі. Дозбирати лише
    # їх: `python3 fetch_targets.py --tiles 12-23`.
    (56.0, 44.0, 61.0, 48.0),   # Чувашія, Марій Ел, схід Костромської
    (61.0, 30.0, 64.0, 48.0),   # Карелія, південь Архангельської, Котлас
    (64.0, 30.0, 70.0, 48.0),   # Мурманськ, Сєвєроморськ, Оленья, Архангельськ
    (64.0, 48.0, 68.0, 64.0),   # Комі: Печора, Усинськ, Воркута
    (56.0, 27.0, 61.0, 30.0),   # Псков, захід Ленінградської, Усть-Луга
    (54.2, 19.5, 55.4, 23.0),   # Калінінград
    (41.1, 40.0, 44.0, 49.0),   # Північний Кавказ, Дагестан
    (43.3, 37.0, 44.0, 40.0),   # Сочі — Адлер
    # Решта дір — із сітки покриття (клітинка 0.5° у полігоні РФ, яку не
    # накриває жодна плитка), а не з пам'яті: рецензія знайшла Оренбург і
    # схід Астрахані, яких перелік вище теж не бачив.
    (50.0, 48.0, 52.0, 62.0),   # Оренбург, Орськ, схід Саратовської
    (45.5, 48.0, 48.0, 49.5),   # схід Астраханської
    (61.0, 28.0, 70.0, 30.0),   # західна смуга Карелії й Мурманської
    (68.0, 48.0, 70.0, 64.0),   # узбережжя Ненецького округу
]


def query(bbox, filters):
    s, w, n, e = bbox
    parts = "".join(f"{f}({s},{w},{n},{e});" for f in filters)
    return f"[out:json][timeout:150];({parts});out center tags;"

# Дешеві military-теги — один запит на плитку віддає все за секунди.
MIL_Q = ('nwr["military"~"airfield|base|depot|training_area|naval_base|'
         'barracks|range|ammunition|danger_area"];'
         'nwr["aeroway"="aerodrome"]["military"];'
         'nwr["landuse"="military"];')
# Промислові — regex по назві дорогий, тому вужчі й окремо.
# Свердловин (`petroleum_well`) тут більше нема: `classify` їх усе одно
# відкидає, а на плитках ХМАО це були тисячі вузлів на відповідь.
IND_Q = ('nwr["industry"~"oil|chemical|military|arms|defence"];'
         'nwr["man_made"="works"]["name"~"нефт|НПЗ|химич|порох|взрывч|'
         'боеприпас|авиазавод|радиозавод|ракет",i];'
         'nwr["landuse"="industrial"]["name"~"нефтебаз|нефтехран|ГСМ|топлив",i];')

def bbox_q(kind, bbox):
    s, w, n, e = bbox
    body = MIL_Q if kind == "mil" else IND_Q
    scoped = "".join(l + f"({s},{w},{n},{e});"
                     for l in body.rstrip(";").split(";") if l)
    return f"[out:json][timeout:150];({scoped});out center tags;"


def fetch(q, log):
    # Публічні дзеркала регулярно віддають 429. Кілька раундів по всіх
    # дзеркалах із наростаючою паузою — щоб перечекати throttle, а не здатись.
    for rnd in range(6):
        for ep in ENDPOINTS:
            try:
                r = requests.post(ep, data={"data": q}, headers=UA, timeout=240)
                if r.status_code == 200:
                    return r.json()
                log(f"    {ep.split('/')[2]}: {r.status_code}")
            except requests.RequestException as ex:
                log(f"    {ep.split('/')[2]}: {type(ex).__name__}")
            time.sleep(3)
        time.sleep(30 * (rnd + 1))
    return None


# «Пейнтбол» OSM тегує як military=range: у Махачкалі він забирав 27
# привʼязок подій (дозбір 23.09.2026).
NOT_A_TARGET = re.compile(r"мчс|пожарн|спасател|фсин|сизо|полиц|гибдд|"
                          r"пейнтбол|страйкбол|лазертаг|paintball|airsoft", re.I)


def classify(t):
    """Категорія обʼєкта за його тегами. Порядок = пріоритет."""
    # Служби, які OSM тегує як military/landuse=military, але які не є
    # ціллю: рятувальники, пожежні, пенітенціарна служба, поліція. Спіймано
    # 9 вересня 2026: «МЧС Росії» в Маріуполі забрав 1025 привʼязок подій
    # Донеччини, бо лежить ближче до центру міста, ніж радіотехнічний
    # батальйон. Росгвардія лишається — це війська.
    if NOT_A_TARGET.search(t.get("name", "")):
        return None
    mil = t.get("military", "")
    if mil == "airfield" or (t.get("aeroway") == "aerodrome"
                             and (mil or t.get("aerodrome:type") == "military")):
        return "airfield"
    if mil == "naval_base":
        return "naval"
    if mil in ("depot", "ammunition"):
        return "ammo_depot"
    if mil in ("training_area", "range", "danger_area"):
        return "range"
    if mil in ("base", "barracks") or t.get("landuse") == "military":
        return "military_base"
    ind = t.get("industry", ""); mm = t.get("man_made", "")
    name = (t.get("name", "") + t.get("product", "")).lower()
    if ind in ("military", "arms", "defence") or \
       any(w in name for w in ("оборон", "авиазавод", "ракет", "танк", "радиозавод")):
        return "defense_plant"
    if ind == "chemical" or any(w in name for w in ("химич", "порох", "взрывч", "боеприпас")):
        return "chemical"
    # Видобуток (свердловини, кущі, ДНС) не є переробкою — див. коментар
    # до запиту refinery вище. Слово «oil» у назві теж не годиться: ним
    # підписані нафтопромисли. Свердловина без «НПЗ» у назві проходить далі
    # до перевірки на нафтобазу і, не збігшись, випадає сама.
    if t.get("industrial") == "refinery" or \
       any(w in name for w in ("нефтеперераб", "нпз", "refinery")):
        return "refinery"
    if any(w in name for w in ("нефтебаз", "нефтехран", "гсм", "топлив")) or \
       (mm == "storage_tank" and any(w in t.get("content", "").lower()
                                     for w in ("oil", "fuel", "diesel"))):
        return "fuel_depot"
    return None


def elem_point(el):
    if el["type"] == "node":
        return el.get("lat"), el.get("lon")
    c = el.get("center") or {}
    return c.get("lat"), c.get("lon")


def main():
    ap = argparse.ArgumentParser("fetch_targets")
    ap.add_argument("--stat", action="store_true")
    ap.add_argument("--tiles", help="лише ці плитки (номери з 0, «12-19» чи «3,5»), "
                    "злиті з наявним targets.json")
    a = ap.parse_args()
    log = print

    if a.stat:
        if not OUT.exists():
            print("targets.json нема")
            return 0
        data = json.load(open(OUT, encoding="utf-8"))
        import collections
        c = collections.Counter(o["cat"] for o in data["objects"])
        print(f"обʼєктів: {len(data['objects'])}")
        for k, v in c.most_common():
            print(f"  {v:5}  {k}")
        return 0

    # Два легких запити на плитку: military окремо від industrial. Змішаний
    # запит із regex по назві на площі 6°×10° сервер рве за таймаутом.
    seen, todo = {}, list(enumerate(TILES))
    if a.tiles:
        # Дозбір, а не перезбір: наявні обʼєкти лишаються з усіма полями
        # (назви з name_targets, куровані НПЗ, ярус і жар). Повний перезбір 9
        # вересня 2026 змінив ціль 5905 подіям при тій самій координаті —
        # свіжий OSM переписує не лише діри, а й те, що вже було.
        want = set()
        for part in a.tiles.split(","):
            lo, _, hi = part.partition("-")
            want |= set(range(int(lo), int(hi or lo) + 1))
        todo = [(i, b) for i, b in todo if i in want]
        with open(OUT, encoding="utf-8") as f:
            for o in json.load(f)["objects"]:
                seen[_key(o["osm"], o["lat"], o["lon"], o["cat"])] = o
        log(f"дозбір плиток {sorted(want)} до {len(seen)} наявних обʼєктів")
    for i, bbox in todo:
        for kind in ("mil", "ind"):
            log(f"плитка {i+1}/{len(TILES)} [{kind}]…")
            res = fetch(bbox_q(kind, bbox), log)
            if not res:
                if a.tiles:
                    # дозбір із діркою записав би перелік, у якому плитка
                    # «покрита», а обʼєктів нема — рівно та вада, яку лагодимо
                    log("  недоступно — дозбір зупинено, targets.json не змінено")
                    return 1
                log("  пропуск (недоступно)")
                continue
            _absorb(res, seen, log)
            time.sleep(4)
    return _save(seen, log)


def _key(osm, lat, lon, cat):
    """Ключ обʼєкта: OSM-ідентифікатор, а для курованих (без osm) — місце.

    Раніше ключем було місце, округлене до 4 знаків. У targets.json
    координати вже округлені до 5, а свіжі з Overpass — сирі, і 46.5409457
    давало 46.5409, а збережене 46.54095 — 46.541: дозбір плитки, що
    перекривається з наявною, продублював би кожен десятий обʼєкт
    (рецензія 23.09.2026). Категорія в ключі лишається: один OSM-обʼєкт
    буває і аеродромом, і складом.
    """
    return (osm, cat) if osm else (round(lat, 4), round(lon, 4), cat)


def _absorb(res, seen, log):
        for el in res.get("elements", []):
            lat, lon = elem_point(el)
            if lat is None:
                continue
            tags = el.get("tags", {})
            cat = classify(tags)
            if not cat:
                continue
            name = (tags.get("name:uk") or tags.get("name:en")
                    or tags.get("name") or tags.get("official_name") or "")
            key = _key(f"{el['type'][0]}{el['id']}", lat, lon, cat)
            if key in seen:
                continue
            seen[key] = {"cat": cat, "lat": round(lat, 5), "lon": round(lon, 5),
                         "name": name[:80], "osm": f"{el['type'][0]}{el['id']}"}
        log(f"  зібрано загалом: {len(seen)}")


def _save(seen, log):
    import os, collections
    from tgmine.territory import filter_objects
    # Плитки Overpass прямокутні, кордон — ні, тому у вибірку падають українські
    # обʼєкти: аеродроми, полігони, військові частини. У публічному переліку
    # цілей їм не місце. Відсів саме тут, а не в site.py: інакше вони лишаються
    # у targets.json і повертаються на карту при кожній зміні шляху публікації.
    objects = filter_objects(list(seen.values()), log=log)
    colors = {k: v[0] for k, v in CATEGORIES.items()}
    json.dump({"colors": colors, "objects": objects},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    by = collections.Counter(o["cat"] for o in objects)
    log(f"\n{len(objects)} обʼєктів -> {OUT} ({os.path.getsize(OUT)/1024:.0f} КБ)")
    for k, v in by.most_common():
        log(f"  {v:5}  {k}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
