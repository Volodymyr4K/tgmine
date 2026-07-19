#!/usr/bin/env python3
"""Аналіз ударів по РФ за даними моніторингових каналів.

Три продукти, яких не дає загальний звіт:
  1. Глибина — відстань цілі від українського кордону, і чи росте вона в часі.
  2. Нічні кампанії — згрупувати по ночах, а не по добах: наліт 23:00–04:00
     календарно розривається надвоє і в денній статистиці зникає.
  3. Коридори — послідовність регіонів у межах однієї ночі = маршрут прольоту.
"""
from __future__ import annotations

import collections
import json
import math
import statistics
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")
from tgmine import dedupe as D, extract as E, geocode as GC

MSK = timezone(timedelta(hours=3))

# Груба лінія українського кордону (пн-сх ділянка + Азов). Для метрики глибини
# точність до десятків км достатня — нас цікавить тренд, не абсолют.
BORDER = [(52.15, 31.79), (52.25, 33.20), (51.60, 34.30), (50.95, 35.30),
          (50.45, 36.30), (50.00, 37.50), (49.60, 38.30), (49.20, 39.20),
          (48.60, 39.70), (48.00, 39.80), (47.30, 38.30), (46.60, 35.30),
          (46.10, 33.60), (45.30, 32.60)]

MIRROR = {"lpr1_treugolnik": "lpr1+kupol", "kupolrussia": "lpr1+kupol",
          "vrv_radar": "vrv_radar"}


def haversine(a, b):
    R = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = (math.sin((la2 - la1) / 2) ** 2 +
         math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(h))


def depth_km(pt):
    return min(haversine(pt, b) for b in BORDER)


def night_of(dt):
    """Ніч, до якої належить момент. 03:00 27-го = ніч 26-го."""
    return (dt - timedelta(hours=6)).date()


def main(path="/tmp/all3.json", cfg_path="configs/ru-monitor.yaml"):
    cfg = E.Config.load(cfg_path)
    posts = json.load(open(path, encoding="utf-8"))
    # дзеркала схлопуємо, інакше lpr1+kupol важать удвічі
    posts = D.cluster(posts, groups=MIRROR)
    posts = E.enrich(posts, cfg)
    gaz = GC.Gazetteer.load("gazetteer/RU.txt", "gazetteer/UA.txt")
    st = GC.geocode_posts(posts, gaz, cfg.geo)
    print(f"геокодування: НП {st['ok']}/{st['ok']+st['miss']}, "
          f"міст-маркерів уточнено {st.get('region_refined',0)}\n")
    for p in posts:
        p["dt"] = datetime.fromisoformat(p["date"]).astimezone(MSK)

    # Точка події — реальні координати НП/міста, а не центроїд області.
    # Для глибини це критично: Керч і центр Криму різняться на 150 км.
    hits = []
    for p in posts:
        region = next((e["value"] for e in p["entities"]
                       if e["type"] == "регіон"), None)
        pts = [e for e in p["entities"] if "lat" in e]
        best = max(pts, key=lambda e: (e.get("geo_conf") != "centroid",
                                       e.get("geo_pop", 0)), default=None)
        if not best:
            continue
        geo = (best["lat"], best["lon"])
        hits.append({"dt": p["dt"], "region": region or best["value"], "geo": geo,
                     "place": best.get("geo_name", best["value"]),
                     "precise": best.get("geo_conf") != "centroid",
                     "depth": depth_km(geo), "tags": p["tags"],
                     "text": p["text"][:70].replace("\n", " "), "url": p["url"]})
    hits.sort(key=lambda h: h["dt"])
    prec = sum(1 for h in hits if h["precise"])
    print(f"подій із геоприв'язкою: {len(hits)} (точних {prec}, "
          f"{prec/len(hits)*100:.0f}%)   "
          f"період: {hits[0]['dt']:%d.%m} … {hits[-1]['dt']:%d.%m}\n")

    # ---- 1. ГЛИБИНА -------------------------------------------------------
    print("== ГЛИБИНА ЦІЛЕЙ (км від кордону) ==")
    by_reg = collections.defaultdict(list)
    for h in hits:
        by_reg[h["region"]].append(h)
    for r, v in sorted(by_reg.items(),
                       key=lambda kv: -statistics.median(h["depth"] for h in kv[1])):
        if len(v) < 15:
            continue
        d = [h["depth"] for h in v]
        print(f"  {statistics.median(d):6.0f} км (мед)  {min(d):5.0f}–{max(d):<5.0f}  "
              f"{r:18} {len(v):5} подій")

    print("\n  розподіл по діапазонах:")
    bands = [(0, 100, "прикордоння"), (100, 300, "ближній тил"),
             (300, 600, "середній тил"), (600, 2000, "глибокий тил")]
    for lo, hi, name in bands:
        n = sum(1 for h in hits if lo <= h["depth"] < hi)
        print(f"    {name:14} {lo:4}-{hi:<5}км  {n:5}  {n/len(hits)*100:5.1f}%")

    print("\n  медіанна глибина по днях (чи йде вглиб):")
    by_day = collections.defaultdict(list)
    for h in hits:
        by_day[h["dt"].date()].append(h["depth"])
    days = sorted(by_day)
    for d in days:
        v = by_day[d]
        med = statistics.median(v)
        deep = sum(1 for x in v if x > 600)
        print(f"    {d}  медіана {med:6.0f} км  |  >600км: {deep:3}  n={len(v)}")
    if len(days) >= 4:
        half = len(days) // 2
        a = statistics.median([x for d in days[:half] for x in by_day[d]])
        b = statistics.median([x for d in days[half:] for x in by_day[d]])
        print(f"    перша половина {a:.0f} км -> друга {b:.0f} км  ({b-a:+.0f})")

    # ---- 2. НІЧНІ КАМПАНІЇ ------------------------------------------------
    print("\n== НІЧНІ КАМПАНІЇ (ніч = 18:00–06:00 МСК) ==")
    by_night = collections.defaultdict(list)
    for h in hits:
        if h["dt"].hour >= 18 or h["dt"].hour < 6:
            by_night[night_of(h["dt"])].append(h)
    for n in sorted(by_night, key=lambda k: -len(by_night[k]))[:8]:
        v = by_night[n]
        regs = collections.Counter(h["region"] for h in v)
        mx = max(h["depth"] for h in v)
        print(f"  ніч {n}  {len(v):4} подій, {len(regs)} регіонів, "
              f"макс.глибина {mx:.0f} км")
        print(f"      {', '.join(f'{r}({c})' for r, c in regs.most_common(5))}")

    print("\n  ніч vs день:")
    night = sum(1 for h in hits if h["dt"].hour >= 18 or h["dt"].hour < 6)
    print(f"    ніч 18-06: {night:5} ({night/len(hits)*100:.1f}%)   "
          f"день 06-18: {len(hits)-night:5} ({(len(hits)-night)/len(hits)*100:.1f}%)")

    # ---- 3. КОРИДОРИ ------------------------------------------------------
    print("\n== НАЙГЛИБШІ ЦІЛІ ==")
    deep = sorted({(h["place"], round(h["depth"])) for h in hits if h["precise"]},
                  key=lambda x: -x[1])[:12]
    for place, d in deep:
        print(f"  {d:5} км  {place}")

    print("\n== КОРИДОРИ (послідовність регіонів у межах ночі) ==")
    paths = collections.Counter()
    for n, v in by_night.items():
        seq, last = [], None
        for h in sorted(v, key=lambda x: x["dt"]):
            if h["region"] != last:
                seq.append(h["region"])
                last = h["region"]
        for i in range(len(seq) - 1):
            if seq[i] != seq[i + 1]:
                paths[(seq[i], seq[i + 1])] += 1
    for (a, b), c in paths.most_common(12):
        d1, d2 = depth_km(cfg.geo[a]), depth_km(cfg.geo[b])
        arrow = "вглиб" if d2 > d1 + 50 else ("назовні" if d1 > d2 + 50 else "вбік")
        print(f"  {c:4}  {a:16} -> {b:16} {arrow}")

    # ---- 4. ТИПИ ЗАСОБІВ ПО ГЛИБИНІ ---------------------------------------
    print("\n== ЧИМ ПРАЦЮЮТЬ НА РІЗНІЙ ГЛИБИНІ ==")
    print(f"  {'діапазон':16}" + "".join(f"{t:>10}" for t in
          ["БПЛА", "ракета", "УАБ", "РСЗО"]))
    for lo, hi, name in bands:
        sel = [h for h in hits if lo <= h["depth"] < hi]
        if not sel:
            continue
        row = f"  {name:16}"
        for t in ["БПЛА", "ракета", "УАБ", "РСЗО"]:
            n = sum(1 for h in sel if t in h["tags"])
            row += f"{n/len(sel)*100:9.1f}%"
        print(row)


if __name__ == "__main__":
    main(*sys.argv[1:])
