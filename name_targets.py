#!/usr/bin/env python3
"""Дає адекватні назви безіменним / generic обʼєктам через reverse-geocode.

OSM часто тегує обʼєкт лише родовою назвою: «Нефтебаза», «ГСМ», «КПП» — без
топоніма. На карті й у рейтингу такі рядки зливаються («Нефтебаза 116» ×4).
Тут до кожного generic-обʼєкта дописуємо найближчий населений пункт із газетира
GeoNames: «Нефтебаза» → «Нефтебаза (Клин)».

  python3 name_targets.py
"""
import json
import re
from pathlib import Path

from tgmine import geocode as GC

OUT = Path("targets.json")

# Назва для безіменного обʼєкта — за типом, а не безлике «Обʼєкт».
CAT_NAME = {"ammo_depot": "Склад БК", "fuel_depot": "Нафтобаза",
            "airfield": "Аеродром", "military_base": "Військовий обʼєкт",
            "range": "Полігон", "refinery": "НПЗ", "chemical": "Хімобʼєкт",
            "defense_plant": "Завод", "naval": "ВМБ"}

# Родові назви без власного топоніма — саме їх треба уточнити населеним пунктом.
GENERIC = re.compile(
    r"^(нефтебаза|нафтобаза|нефтехранилищ\w*|нефтесклад|гсм|азс|склад|"
    r"горюче[- ]смазочн\w*|бывшая\s+нефтебаза|колишня\s+нафтобаза|"
    r"нефтепродукт\w*|топливн\w*\s+склад)\.?$", re.I)


def is_generic(name):
    return not name or bool(GENERIC.match(name.strip()))


def main():
    data = json.load(open(OUT, encoding="utf-8"))
    print("завантаження газетира…")
    gaz = GC.Gazetteer.load("gazetteer/RU.txt", "gazetteer/UA.txt")

    # Ідемпотентність: тримаємо оригінальну generic-назву в raw_name, щоб
    # повторний запуск не переназивав уже уточнене й не плодив «Обʼєкт (Обʼєкт)».
    named, missed = 0, 0
    for o in data["objects"]:
        raw = o.get("raw_name", o.get("name"))
        if not is_generic(raw):
            continue
        o["raw_name"] = raw
        near = nearest_place(gaz, o["lat"], o["lon"])
        # безіменний → назва типу («Склад БК»); generic → як є («Нефтебаза»)
        base = (raw.strip().capitalize() if raw else "") or CAT_NAME.get(o["cat"], "Обʼєкт")
        o["name"] = f"{base} ({near})" if near else base
        named += 1 if near else 0
        missed += 0 if near else 1

    json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"уточнено назв: {named}, без сусіда: {missed}")
    # приклад
    ex = [o for o in data["objects"]
          if o["cat"] == "fuel_depot" and "(" in (o.get("name") or "")][:8]
    for o in ex:
        print(f"  {o['name']}")


def nearest_place(gaz, lat, lon, max_km=25.0):
    """Найближчий населений пункт із максимальним населенням у радіусі."""
    best = None
    # газетир індексований по назвах, не по координатах, тому шукаємо серед усіх
    # записів у грубому боксі. Обʼєктів, що доходять сюди, ~2900.
    box = 0.35  # ~ 25-35 км
    for recs in gaz.by_name.values():
        for r in recs:
            if r["fclass"] != "P" or r["pop"] < 2000:
                continue
            if abs(r["lat"] - lat) > box or abs(r["lon"] - lon) > box:
                continue
            d = GC.haversine((lat, lon), (r["lat"], r["lon"]))
            if d > max_km:
                continue
            score = (r["pop"], -d)
            if best is None or score > best[0]:
                best = (score, r["name"])
    return best[1] if best else None


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    main()
