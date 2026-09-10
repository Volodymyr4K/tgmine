#!/usr/bin/env python3
"""Супутникова підкладка театру: збірка тайлів у один растр.

ЧОМУ НЕ ХІЛШЕЙД. Natural Earth дає рельєф ~1 км на піксель і без жодної
фактури поверхні: ліс, поле й місто виглядають однаково. На оглядових картах
під маршрутами лежить супутник, і саме він дає впізнаваність.

ЧОМУ САМЕ ЦЕ ДЖЕРЕЛО. Sentinel-2 cloudless (EOX IT Services) — CC BY 4.0:
похідні дозволені, потрібен лише підпис. Esri World Imagery і Google цього не
дозволяють поза власними застосунками, тому вони відпадають попри якість.
Нічні вогні — NASA VIIRS, суспільне надбання.

Обидва шари в Web Mercator, тобто в тій самій проєкції, що й редактор.
Мозаїка ріжеться ПО МЕЖАХ ТАЙЛІВ, а рамка театру рахується з них — інакше
растр з'їде відносно векторів.

Запуск:  python3 mktiles.py [zoom]
"""
import json
import math
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))

# З 10 вересня 2026 — до Уралу й Західного Сибіру (Новий Уренгой 76.6°),
# та сама рамка, що в basemap.js і labels.py. Кадр редактора за
# замовчуванням лишається європейським (`fit()` в editor.html).
BOX = (41.0, 70.0, 20.0, 82.0)          # la0, la1, lo0, lo1
CACHE = os.path.join(HERE, "tiles")
UA = "tgmine-map/1.0 (OSINT static map; contact via t.me)"

MAXZ = {"sat": 12, "night": 8}

SRC = {
    # {z}/{y}/{x} у EOX WMTS
    "sat": ("https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2020_3857/"
            "default/g/{z}/{y}/{x}.jpg"),
    # Нічні вогні — РІЧНИЙ композит Black Marble, а не добова радіація.
    # Добовий шар дає смугу прольоту через пів кадру: сенсор бачив цю
    # ділянку під іншим кутом, і на карті це виглядало як засвітка.
    "night": ("https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/"
              "VIIRS_Black_Marble/default/2016-01-01/"
              "GoogleMapsCompatible_Level8/{z}/{y}/{x}.png"),
}


def deg2num(la, lo, z):
    n = 2 ** z
    x = (lo + 180.0) / 360.0 * n
    y = (1 - math.log(math.tan(math.radians(la)) + 1 / math.cos(math.radians(la)))
         / math.pi) / 2 * n
    return x, y


def num2deg(x, y, z):
    n = 2 ** z
    lo = x / n * 360.0 - 180.0
    la = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return la, lo


def fetch(kind, z, x, y):
    path = f"{CACHE}/{kind}/{z}/{x}_{y}.img"
    if os.path.exists(path):
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    url = SRC[kind].format(z=z, x=x, y=y)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                data = r.read()
            open(path, "wb").write(data)
            return path
        except Exception as e:
            if attempt == 2:
                print(f"  пропуск {kind} {z}/{x}/{y}: {e}")
                return None
            time.sleep(1.5 * (attempt + 1))


def mosaic(kind, z):
    x0, y0 = deg2num(BOX[1], BOX[2], z)      # верхній лівий
    x1, y1 = deg2num(BOX[0], BOX[3], z)      # нижній правий
    tx0, ty0, tx1, ty1 = int(x0), int(y0), int(x1) + 1, int(y1) + 1
    w, h = (tx1 - tx0) * 256, (ty1 - ty0) * 256
    total = (tx1 - tx0) * (ty1 - ty0)
    done = 0
    for tx in range(tx0, tx1):
        for ty in range(ty0, ty1):
            p = fetch(kind, z, tx, ty)
            done += 1
            if done % 40 == 0:
                print(f"  {kind}: {done}/{total}")
    # рамка мозаїки — по МЕЖАХ тайлів, а не по запиту
    la1, lo0 = num2deg(tx0, ty0, z)
    la0, lo1 = num2deg(tx1, ty1, z)
    return None, [la0, la1, lo0, lo1]


def write_index():
    """Перелік викачаних зумів для редактора.

    Без нього редактор мусив ПРОБУВАТИ локальний шлях для кожного тайла й
    ловити 404: на машині без кешу це 60 марних запитів на кожен зум. Один
    маніфест замінює їх одним запитом.
    """
    idx = {}
    for kind in SRC:
        base = os.path.join(CACHE, kind)
        if not os.path.isdir(base):
            continue
        zs = sorted(int(z) for z in os.listdir(base) if z.isdigit())
        if zs:
            idx[kind] = zs
    with open(os.path.join(CACHE, "index.json"), "w", encoding="utf-8") as f:
        json.dump(idx, f)
    print("-> tiles/index.json", idx)


def main(zoom="8", kinds="sat,night"):
    """Викачує тайли в кеш. Мозаїку в один файл більше не збираємо: редактор
    малює з тайлів і сам обирає зум під масштаб, а склеєний растр обмежував
    деталізацію тим, з яким зумом його зібрали."""
    z = int(zoom)
    for kind in kinds.split(","):
        kz = min(z, MAXZ[kind])
        print(f"{kind}, зум {kz}")
        _, box = mosaic(kind, kz)
        print(f"  рамка {box[0]:.2f}..{box[1]:.2f} пн, {box[2]:.2f}..{box[3]:.2f} сх")
    write_index()


if __name__ == "__main__":
    main(*sys.argv[1:])
