#!/usr/bin/env python3
"""Контури держав окремим шаром.

Межі областей у basemap беруться з Natural Earth admin-1 і спрощуються
кожен полігон окремо. Через це сусідні області не мають спільних вершин, і
«розчинити» внутрішні межі топологічно не виходить: частина внутрішніх ребер
лишається непарною й вилазить на карту білими уламками. Тому державні кордони
беремо з їхнього власного шару — admin-0.

Запуск: python3 mkcountries.py     (дописує ключ "countries" у basemap.json
                                    і перезбирає basemap.js)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.setrecursionlimit(20000)
import shapefile

from mkbase import KEEP, EPS, NE, polys_of

# Natural Earth має кілька «точок зору». У файлі за замовчуванням Крим
# віднесено до Росії — це де-факто контроль, а не кордон. Для української
# карти беремо українську точку зору: там Крим у складі України, а кордон
# із РФ іде Керченською протокою.
LAYER = "ne_10m_admin_0_countries_ukr"


def ensure_layer():
    import urllib.request
    import zipfile
    d = os.path.join(NE, LAYER)
    if os.path.isdir(d):
        return d
    os.makedirs(NE, exist_ok=True)
    url = f"https://naciscdn.org/naturalearth/10m/cultural/{LAYER}.zip"
    print(f"тягну {LAYER}…")
    tmp = os.path.join(NE, LAYER + ".zip")
    urllib.request.urlretrieve(url, tmp)
    with zipfile.ZipFile(tmp) as z:
        z.extractall(d)
    os.remove(tmp)
    return d


def payload(path):
    """basemap.js — це window.BASE={...}; плюс хвіст. Читаємо саме його
    вміст: js і json у репозиторії зібрані з різними рамками, і збирати js
    із json означало б підмінити дані (одного разу так зникли підписи міст)."""
    s = open(path, encoding="utf-8").read()
    i = s.index("=") + 1
    d, end = json.JSONDecoder().raw_decode(s[i:].lstrip())
    tail = s[i:].lstrip()[end:]
    return d, tail


def rings_for(path, box):
    out = {}
    for sr in shapefile.Reader(path).iterShapeRecords():
        rec = sr.record.as_dict()
        a3 = rec.get("ADM0_A3") or rec.get("adm0_a3")
        if a3 not in KEEP:
            continue
        rings = polys_of(sr.shape, EPS, box, 6)
        if rings:
            out.setdefault(a3, []).extend(rings)
    return out


def _inside(pt, ring):
    la, lo = pt
    ins = False
    for i in range(len(ring)):
        a, b = ring[i - 1], ring[i]
        if (b[0] > la) != (a[0] > la):
            x = (a[1] - b[1]) * (la - b[0]) / ((a[0] - b[0]) or 1e-12) + b[1]
            if lo < x:
                ins = not ins
    return ins


def fix_crimea(data):
    """Крим у файлі областей Natural Earth віднесено до Росії.

    Це де-факто контроль, а не кордон, і на українській карті так бути не
    може: шар «межі областей РФ» малював би півострів як російські області.
    Контури областей імені не мають, тож упізнаємо їх геометрично — за
    попаданням центра ваги в контур Криму, який уже є в `regions`.
    """
    crimea = (data.get("regions") or {}).get("Крим") or []
    if not crimea:
        return 0
    adm = data.get("admin") or {}
    ru, ua = adm.get("RUS") or [], adm.setdefault("UKR", [])
    keep, moved = [], 0
    for ring in ru:
        cla = sum(p[0] for p in ring) / len(ring)
        clo = sum(p[1] for p in ring) / len(ring)
        if any(_inside((cla, clo), r) for r in crimea):
            ua.append(ring)
            moved += 1
        else:
            keep.append(ring)
    adm["RUS"] = keep
    return moved


def main():
    path = os.path.join(ensure_layer(), LAYER)

    js = os.path.join(HERE, "basemap.js")
    data, tail = payload(js)
    data["countries"] = rings_for(path, tuple(data["box"]))
    moved = fix_crimea(data)
    if moved:
        print(f"Крим: контурів областей перенесено з RUS до UKR — {moved}")
    with open(js, "w", encoding="utf-8") as f:
        f.write("window.BASE=")
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        f.write(tail)
    n = data["countries"]
    print(f"basemap.js: країн {len(n)}, контурів {sum(len(v) for v in n.values())}")

    bm = os.path.join(HERE, "basemap.json")
    if os.path.exists(bm):
        d2 = json.load(open(bm, encoding="utf-8"))
        d2["countries"] = rings_for(path, tuple(d2["box"]))
        fix_crimea(d2)
        json.dump(d2, open(bm, "w", encoding="utf-8"),
                  ensure_ascii=False, separators=(",", ":"))
        print(f"basemap.json: країн {len(d2['countries'])}")


if __name__ == "__main__":
    main()
