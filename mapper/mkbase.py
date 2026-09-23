#!/usr/bin/env python3
"""Підкладка карти-плаката: рельєф і те, що робить карту картою.

Плаский полігон області читається як схема, а не як місцевість. На оглядових
картах під маршрутами завжди лежить фактура: рельєф, річки, дороги, міські
масиви, розсип населених пунктів. Вона не несе даних про наліт — вона дає
масштаб і впізнаваність, без яких лінія «Тамбов -> Рязань» ні про що не
говорить.

Джерела ті самі, що вже в проєкті (Natural Earth 10m) плюс газетир GeoNames.
Виходить basemap.json (вектор) і relief.png (рельєф, обрізаний по рамці).

Запуск:  python3 mkbase.py [lat0 lat1 lon0 lon1]
         python3 mkbase.py --regions   (лише області конфіга в basemap.js)
"""
import json
import sys

import os

sys.setrecursionlimit(20000)
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import shapefile
from mkregions import rings_of, rdp, MATCH

NE = os.path.join(HERE, "ne")
ADMIN = f"{ROOT}/gazetteer/ne_10m_admin_1_states_provinces"

# країни, чиї межі потрапляють у кадр
KEEP = {"RUS", "UKR", "BLR", "MDA", "POL", "ROU", "LTU", "LVA", "EST", "KAZ",
        "GEO", "AZE", "ARM", "TUR", "BGR", "SVK", "HUN", "FIN", "SWE", "SRB"}


# Шари Natural Earth, яких нема в репозиторії: разом ~23 МБ. Тягнемо самі —
# інакше оператор мусить шукати посилання в README і класти файли руками.
NE_LAYERS = {
    "ne_10m_rivers_lake_centerlines": "10m/physical",
    "ne_10m_lakes": "10m/physical",
    "ne_10m_urban_areas": "10m/cultural",
    "ne_10m_roads": "10m/cultural",
}


def ensure_ne():
    import urllib.request
    import zipfile
    os.makedirs(NE, exist_ok=True)
    for name, path in NE_LAYERS.items():
        if os.path.isdir(os.path.join(NE, name)):
            continue
        url = f"https://naciscdn.org/naturalearth/{path}/{name}.zip"
        print(f"тягну {name}…")
        tmp = os.path.join(NE, name + ".zip")
        urllib.request.urlretrieve(url, tmp)
        with zipfile.ZipFile(tmp) as z:
            z.extractall(os.path.join(NE, name))
        os.remove(tmp)


def need_gazetteer():
    """Розсип НП береться з газетира проєкту. Він у .gitignore і тягнеться
    разово — див. README у корені."""
    if os.path.exists(os.path.join(ROOT, "gazetteer", "RU.txt")):
        return
    raise SystemExit(
        "нема gazetteer/RU.txt — спершу:\n"
        "  mkdir -p gazetteer && cd gazetteer\n"
        "  curl -sLO https://download.geonames.org/export/dump/RU.zip\n"
        "  curl -sLO https://download.geonames.org/export/dump/UA.zip\n"
        "  curl -sLO https://naciscdn.org/naturalearth/10m/cultural/"
        "ne_10m_admin_1_states_provinces.zip\n"
        "  unzip -oq '*.zip' && rm -f *.zip")


def box_hit(pts, box, pad=2.0):
    la0, la1, lo0, lo1 = box
    return any(la0 - pad <= la <= la1 + pad and lo0 - pad <= lo <= lo1 + pad
               for la, lo in pts)


def lines_of(shape, eps, box):
    """Незамкнені лінії (річки, дороги) — Дуглас-Пекер без різання кільця."""
    parts = list(shape.parts) + [len(shape.points)]
    out = []
    for i in range(len(parts) - 1):
        seg = shape.points[parts[i]:parts[i + 1]]
        if len(seg) < 2:
            continue
        simp = rdp([(round(x, 4), round(y, 4)) for x, y in seg], eps)
        pts = [[round(y, 3), round(x, 3)] for x, y in simp]
        if len(pts) >= 2 and box_hit(pts, box):
            out.append(pts)
    return out


def polys_of(shape, eps, box, min_pts=5):
    out = []
    for ring in rings_of(shape, eps, min_pts):
        if box_hit(ring, box):
            out.append(ring)
    return out


def settlements(box, min_pop=12_000):
    """Розсип НП: дає щільність, якої не дасть жоден полігон.

    Без підписів — назви в газетирі латиницею, а підписувати латиницею
    україномовну карту гірше, ніж не підписувати. Підписи йдуть окремо, зі
    словника (poster.CITY_UA).
    """
    la0, la1, lo0, lo1 = box
    out = []
    for path in ("gazetteer/RU.txt", "gazetteer/UA.txt"):
        for line in open(f"{ROOT}/{path}", encoding="utf-8"):
            f = line.split("\t")
            if len(f) < 15 or f[6] != "P":
                continue
            pop = int(f[14] or 0)
            if pop < min_pop:
                continue
            la, lo = float(f[4]), float(f[5])
            if not (la0 <= la <= la1 and lo0 <= lo <= lo1):
                continue
            out.append([round(la, 3), round(lo, 3), 1 if pop < 50_000 else 2])
    return out


# Спрощення дрібніше, ніж у конвеєрі сайту (0.04): там карта інтерактивна й
# важить кожен кілобайт, тут — один статичний кадр, і берегова лінія має
# лягати на рельєф, а не зрізати затоки.
EPS = 0.004


def admin_rings(box):
    """Межі країн і області конфіга — з одного проходу, тими самими вершинами."""
    admin, named = {}, {}
    for sr in shapefile.Reader(ADMIN).iterShapeRecords():
        rec = sr.record.as_dict()
        a3 = rec.get("adm0_a3")
        if a3 not in KEEP:
            continue
        rings = polys_of(sr.shape, EPS, box, 6)
        if not rings:
            continue
        admin.setdefault(a3, []).extend(rings)
        nr = (rec.get("name_ru") or "").lower()
        for key, pats in MATCH.items():
            if any(pt.lower() in nr for pt in pats):
                named.setdefault(key, []).extend(rings)
    return admin, named


def regions_only():
    """Оновити в basemap.js лише області конфіга (`--regions`).

    Повна збірка тягне рельєф, воду й дороги, і basemap.js із неї робиться
    не напряму (див. CLAUDE.md: .js і .json — різні файли). Коли в `MATCH`
    додали субʼєкт, міняти треба один ключ: той самий прохід по тих самих
    контурах із рамкою самого файлу. Перевірено 23.09.2026: для 48 наявних
    областей результат побайтово той самий, що в basemap.js.
    """
    js = os.path.join(HERE, "basemap.js")
    s = open(js, encoding="utf-8").read()
    i = s.index("=") + 1
    body = s[i:].lstrip()
    data, end = json.JSONDecoder().raw_decode(body)
    _, named = admin_rings(tuple(data["box"]))
    added = sorted(set(named) - set(data.get("regions") or {}))
    data["regions"] = named
    with open(js, "w", encoding="utf-8") as f:
        f.write("window.BASE=")
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        f.write(body[end:])
    print(f"basemap.js: областей {len(named)}, нових {added}")


def main(*box):
    box = tuple(float(x) for x in box) if box else (42.0, 62.0, 20.0, 66.0)
    need_gazetteer()
    ensure_ne()
    out = {"box": list(box)}

    # 1. межі областей І області конфіга — ОДИН прохід, ОДНЕ спрощення.
    # Було два джерела: підкладка різалась тут, а regions.json — окремо
    # своїм спрощенням. Та сама межа виходила двома різними контурами, і на
    # карті вони не збігались: Крим ставав клякcою поперек берегової лінії.
    # Тепер заливка області й межа під нею — буквально ті самі вершини.
    admin, named = admin_rings(box)
    out["admin"] = admin
    out["regions"] = named

    # 2. вода: озера полігонами, річки лініями
    out["lakes"] = [r for s in shapefile.Reader(f"{NE}/ne_10m_lakes/ne_10m_lakes").shapes()
                    for r in polys_of(s, 0.015, box, 5)]
    riv = shapefile.Reader(f"{NE}/ne_10m_rivers_lake_centerlines/"
                           "ne_10m_rivers_lake_centerlines")
    out["rivers"] = [ln for s in riv.shapes() for ln in lines_of(s, 0.012, box)]

    # 3. дороги — лише магістралі: решта на масштабі країни зливається в кашу
    rd = shapefile.Reader(f"{NE}/ne_10m_roads/ne_10m_roads")
    roads = []
    for s in rd.iterShapeRecords():
        r = s.record.as_dict()
        if r.get("scalerank", 99) > 8:
            continue
        if r.get("type") not in ("Major Highway", "Secondary Highway", "Road"):
            continue
        roads.extend(lines_of(s.shape, 0.03, box))
    out["roads"] = roads

    # 4. міські масиви — світлі плями там, де справді місто
    ua = shapefile.Reader(f"{NE}/ne_10m_urban_areas/ne_10m_urban_areas")
    out["urban"] = [r for s in ua.shapes() for r in polys_of(s, 0.02, box, 4)]

    # 5. розсип НП
    out["places"] = settlements(box)

    json.dump(out, open(os.path.join(HERE, "basemap.json"), "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    print(f"контурів: {sum(len(v) for v in admin.values())}  "
          f"областей конфіга: {len(named)}  озер: {len(out['lakes'])}  "
          f"річок: {len(out['rivers'])}  доріг: {len(out['roads'])}  "
          f"міських масивів: {len(out['urban'])}  НП: {len(out['places'])}")
    print(f"-> basemap.json ({os.path.getsize(os.path.join(HERE,'basemap.json'))/1024/1024:.1f} МБ)")


if __name__ == "__main__":
    if sys.argv[1:] == ["--regions"]:
        regions_only()
    else:
        main(*sys.argv[1:])
