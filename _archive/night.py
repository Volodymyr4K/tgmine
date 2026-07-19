#!/usr/bin/env python3
"""Реконструкція одного нальоту: хронологія, лічильники, маршрут, events.json.

Запуск:  python3 night.py 2026-07-17 Московська
"""
from __future__ import annotations

import collections
import json
import math
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")
from tgmine import dedupe as D, extract as E, geocode as GC

MSK = timezone(timedelta(hours=3))
MIRROR = {"lpr1_treugolnik": "lpr1+kupol", "kupolrussia": "lpr1+kupol",
          "vrv_radar": "vrv_radar"}

# "Фиксация от 7 БПЛА", "Фиксация группы БПЛА", "от 4 БПЛА"
COUNT = re.compile(r"(?:от\s+)?(\d+)\s*(?:БПЛА|бпла)", re.I)
GROUP = re.compile(r"груп\w*\s+БПЛА", re.I)

STATUS = [
    ("ППО", r"работа\s+ПВО|работает\s+ПВО|ПВО\s+по\s+БПЛА"),
    ("ВКС", r"работа\s+ВКС"),
    ("фіксація", r"фиксаци\w*"),
    ("небезпека", r"опасность"),
    ("тривога", r"тревога"),
    ("відбій", r"отбой"),
    ("вибух", r"взрыв\w*"),
]
STATUS = [(k, re.compile(v, re.I)) for k, v in STATUS]


def status_of(text):
    for name, rx in STATUS:
        if rx.search(text):
            return name
    return "інше"


def drones(text):
    m = COUNT.search(text)
    if m:
        return int(m.group(1))
    return 1 if GROUP.search(text) else None


def haversine(a, b):
    R = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = (math.sin((la2 - la1) / 2) ** 2 +
         math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(h))


def main(date="2026-07-17", region="Московська", src="/tmp/all3.json", radius="250"):
    d0 = datetime.fromisoformat(date).replace(tzinfo=MSK)
    lo, hi = d0.replace(hour=17), d0 + timedelta(days=1, hours=12)

    cfg = E.Config.load("configs/ru-monitor.yaml")
    gaz = GC.Gazetteer.load("gazetteer/RU.txt", "gazetteer/UA.txt")
    posts = D.cluster(json.load(open(src, encoding="utf-8")), groups=MIRROR)
    posts = E.enrich(posts, cfg)
    GC.geocode_posts(posts, gaz, cfg.geo)
    for p in posts:
        p["dt"] = datetime.fromisoformat(p["date"]).astimezone(MSK)

    sel = [p for p in posts if lo <= p["dt"] < hi
           and any(e["value"] == region for e in p["entities"])]
    events = []
    for p in sorted(sel, key=lambda x: x["dt"]):
        pts = [e for e in p["entities"]
               if "lat" in e and e.get("geo_conf") != "centroid"]
        best = max(pts, key=lambda e: e.get("geo_pop", 0), default=None)
        events.append({
            "t": p["dt"].isoformat(),
            "hhmm": p["dt"].strftime("%H:%M"),
            "place": (best or {}).get("geo_name"),
            "lat": (best or {}).get("lat"),
            "lon": (best or {}).get("lon"),
            "status": status_of(p["text"]),
            "drones": drones(p["text"]),
            "text": p["text"].replace("\n", " / "),
            "url": p["url"],
            "channels": p.get("channels", [p["channel"]]),
        })

    # Пост "Московская область / Тульская область" може віддати точку сусіда.
    # Для карти лишаємо те, що реально в межах регіону.
    center = cfg.geo.get(region)
    R = float(radius)
    if center:
        for e in events:
            if e["lat"] and haversine(center, (e["lat"], e["lon"])) > R:
                e["out_of_region"] = True
                e["lat"] = e["lon"] = None
    geo = [e for e in events if e["lat"]]
    print(f"НАЛІТ {date} -> {region}")
    print(f"подій: {len(events)} (з координатами {len(geo)})")
    if not events:
        return
    print(f"вікно: {events[0]['hhmm']} – {events[-1]['hhmm']} МСК "
          f"({(datetime.fromisoformat(events[-1]['t'])-datetime.fromisoformat(events[0]['t'])).seconds//60} хв)\n")

    print("== ЕТАПИ (по 30 хв) ==")
    buckets = collections.defaultdict(list)
    for e in events:
        t = datetime.fromisoformat(e["t"])
        buckets[t.replace(minute=(t.minute // 30) * 30, second=0)].append(e)
    for k in sorted(buckets):
        v = buckets[k]
        places = [x["place"] for x in v if x["place"]]
        st = collections.Counter(x["status"] for x in v)
        dr = sum(x["drones"] or 0 for x in v)
        print(f"  {k:%H:%M}  {len(v):3} подій  дронів≥{dr:3}  "
              f"{', '.join(f'{a}:{b}' for a, b in st.most_common(3))}")
        if places:
            print(f"          {', '.join(dict.fromkeys(places))[:100]}")

    print("\n== ЛІЧИЛЬНИКИ ==")
    st = collections.Counter(e["status"] for e in events)
    for k, v in st.most_common():
        print(f"  {v:4}  {k}")
    tot = sum(e["drones"] or 0 for e in events)
    named = [e for e in events if e["drones"]]
    print(f"  сума заявлених БпЛА у постах з числом: {tot} (у {len(named)} постах)")

    print("\n== НАЙЧАСТІШІ ТОЧКИ ==")
    for place, c in collections.Counter(e["place"] for e in geo).most_common(12):
        pts = [e for e in geo if e["place"] == place]
        sts = collections.Counter(e["status"] for e in pts)
        print(f"  {c:3}  {place:22} {', '.join(f'{a}:{b}' for a, b in sts.most_common(2))}")

    if geo:
        print("\n== ГЕОМЕТРІЯ ==")
        lats = [e["lat"] for e in geo]
        lons = [e["lon"] for e in geo]
        print(f"  межі: {min(lats):.2f}–{max(lats):.2f}°N, {min(lons):.2f}–{max(lons):.2f}°E")
        span = haversine((min(lats), min(lons)), (max(lats), max(lons)))
        print(f"  діагональ зони: {span:.0f} км")
        first, last = geo[0], geo[-1]
        print(f"  перша точка {first['hhmm']} {first['place']} -> "
              f"остання {last['hhmm']} {last['place']}, "
              f"зсув {haversine((first['lat'],first['lon']),(last['lat'],last['lon'])):.0f} км")

    out = f"night_{date}_{region}.json"
    json.dump(events, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n-> {out}")


if __name__ == "__main__":
    main(*sys.argv[1:])
