#!/usr/bin/env python3
"""Реконструкція нальоту по всьому театру: точки фіксацій + вектори руху.

На відміну від night.py (один регіон), бере всю ніч цілком — від заходу з
українського боку до кінцевих цілей у глибині РФ.

Запуск:  python3 raid.py 2026-07-17
"""
from __future__ import annotations

import collections
import json
import math
import random
import statistics
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")
from tgmine import extract as E, geocode as GC, store as ST, territory as T, tracker as TR
from tgmine.labels import region_label

MSK = timezone(timedelta(hours=3))
# Точка відліку — підконтрольна Україні територія (territory.depth_km);
# все, що ближче за 60 км, вважаємо заходом.


def hav(a, b):
    R = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = (math.sin((la2 - la1) / 2) ** 2 +
         math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(h))


def depth(pt):
    return T.depth_km(pt[0], pt[1])


#: Скільки перемішувань. 20 вистачає для середнього; 40 змінюють z на ~0.1,
#: а найбільша ніч (398 точок) коштує 0.37 с проти 0.74 с.
NULL_SHUFFLES = 20
#: Фіксоване зерно: перезбірка тієї самої доби має давати той самий файл.
NULL_SEED = 20260717


def null_test(dets, observed, shuffles=NULL_SHUFFLES):
    """Скільки треків дало б чисте перемішування часових міток.

    Точки лишаються ті самі, порядок у часі руйнується. Якщо трекер збирає
    стільки ж ланцюжків із перемішаних міток — він ловить щільність точок,
    а не рух.

    Рахується для КОЖНОЇ доби окремо. Раніше на всі сторінки йшло одне вшите
    число (12 проти 5.4, z=+4.55) — насправді це результат 2026-07-17,
    найкращої ночі в наборі. У липні 2026 медіана z по 31 ночі була 0.00;
    після перебудови сховища у вересні — +1.17 по 138 ночах (див. CLAUDE.md).
    Число живе на сторінці ночі, не тут — тут лише чому воно рахується щоразу.
    """
    if len(dets) < 10:
        return None
    rnd = random.Random(NULL_SEED)
    counts = []
    for _ in range(shuffles):
        times = [d["dt"] for d in dets]
        rnd.shuffle(times)
        counts.append(len(TR.build([{**d, "dt": t} for d, t in zip(dets, times)])))
    mean = statistics.mean(counts)
    sd = statistics.pstdev(counts)
    return {"observed": observed, "mean": round(mean, 2),
            "sd": round(sd, 2), "shuffles": shuffles,
            "z": round((observed - mean) / sd, 2) if sd else 0.0}


def main(date="2026-07-17", h_from="12", h_to="12", src=None):
    """Читає готові події зі сховища. Розбір уже зроблено на етапі sync —
    тут лише вибірка вікна, треки й вектори."""
    d0 = datetime.fromisoformat(date).replace(tzinfo=MSK)
    # оперативна доба 12:00 -> 12:00: вікна стикуються без дірок,
    # нічний наліт не розривається межею
    lo = d0.replace(hour=int(h_from))
    hi = (d0 + timedelta(days=1)).replace(hour=int(h_to))

    cfg = E.Config.load("configs/ru-monitor.yaml")
    st = ST.Store()
    raw = st.window(lo, hi)
    if not raw:
        print(f"у сховищі нема подій за {date}. Запусти: python3 sync.py --rebuild")
        return
    # дзеркала: беремо лише канонічні, інакше подія важить стільки разів,
    # скільки каналів її переписали
    events = [e for e in raw if not e.get("dup_of") and not e.get("noise")]
    for e in events:
        e["hhmm"] = datetime.fromisoformat(e["t"]).strftime("%H:%M")
    events = [e for e in events if e.get("lat")]

    # Вектори руху — з ланок, які розбір уже поклав у подію (`legs`,
    # `store.legs_of`, конвеєр v26). До 22.09.2026 їх читав окремий розбір
    # (`vectors.geocode_vectors`) — одна ланка на пост, кінці-області
    # відкинуті; за еталоном повнота ланок 29-38%, точність 43-77%; тепер
    # 61-73% і 93% (BACKLOG §16.11-16.13).
    vecs = []
    for e in raw:
        if e.get("dup_of") or e.get("noise"):
            continue
        for sn, sla, slo, sar, dn, dla, dlo, dar in e.get("legs") or []:
            vecs.append({"t": e["t"], "url": e["url"], "src_name": sn, "src": [sla, slo],
                         "dst_name": dn, "dst": [dla, dlo], "src_area": sar, "dst_area": dar,
                         "marker": "legs", "text": e["text"]})
    for v in vecs:
        v["hhmm"] = datetime.fromisoformat(v["t"]).astimezone(MSK).strftime("%H:%M")
        v["t"] = datetime.fromisoformat(v["t"]).astimezone(MSK).isoformat()
        v["len_km"] = round(hav(v["src"], v["dst"]))
    vecs = [v for v in vecs if 5 <= v["len_km"] <= 700]   # відсіяти сміття
    vecs.sort(key=lambda v: v["t"])

    print(f"ДОБА {date}  ({lo:%d.%m %H:%M} – {hi:%d.%m %H:%M} МСК)")
    print(f"джерело: сховище ({len(raw)} записів, {len(raw)-len(events)} дублів/без гео)")
    kc = collections.Counter(e["kind"] for e in events)
    pts = sum(1 for e in events if e["scope"] == "точка")
    dr = [e["drones"] for e in events if e["drones"]]
    print(f"повідомлень: {len(events)}   з них спостережень у точці: {pts}, "
          f"станів по області: {len(events)-pts}")
    print("  " + "  ".join(f"{k}:{v}" for k, v in kc.most_common()))
    print(f"  заявлено апаратів: {sum(dr)} (у {len(dr)} повідомленнях, макс {max(dr) if dr else 0})")
    print(f"  векторів руху: {len(vecs)}\n")

    print("== ХВИЛЯ ЗА ХВИЛЕЮ: перша фіксація в регіоні ==")
    first = {}
    for e in events:
        if e["region"] and e["region"] not in first:
            first[e["region"]] = e
    for r, e in sorted(first.items(), key=lambda kv: kv[1]["t"]):
        print(f"  {e['hhmm']}  {e['depth']:5} км  {r:18} {e['place']}")

    print("\n== ВЕКТОРИ РУХУ (як пишуть канали) ==")
    for v in vecs[:25]:
        d1, d2 = depth(v["src"]), depth(v["dst"])
        arrow = "вглиб" if d2 > d1 + 30 else ("до кордону" if d1 > d2 + 30 else "вбік")
        print(f"  {v['hhmm']}  {v['src_name'][:20]:21} -> {v['dst_name'][:20]:21} "
              f"{v['len_km']:4} км  {arrow}")

    print("\n== ГЛИБИНА В ЧАСІ (медіана по годинах) ==")
    byh = collections.defaultdict(list)
    for e in events:
        byh[e["hhmm"][:2]].append(e["depth"])
    for h in sorted(byh):
        v = byh[h]
        bar = "#" * min(60, int(statistics.median(v) / 20))
        print(f"  {h}:00  {bar} {statistics.median(v):5.0f} км  n={len(v)}")

    # ---- ТРЕКИ ------------------------------------------------------------
    dets = [{"dt": datetime.fromisoformat(e["t"]), "xy": (e["lat"], e["lon"]),
             "place": e["place"], "status": e["kind"], "url": e["url"],
             "depth": e["depth"]}
            # у трекер ідуть тільки СПОСТЕРЕЖЕННЯ в точці. Тривога по області
            # не є свідченням, що апарат там був, і псує асоціацію.
            for e in events if e["scope"] == "точка"]
    tracks = TR.build(dets)
    null = null_test(dets, len(tracks))
    print(f"\n== ТРЕКИ (гіпотези руху) ==")
    print(f"  побудовано: {len(tracks)} з {len(dets)} фіксацій")
    if null:
        print(f"  нуль-тест: {null['mean']:.1f} очікуваних від випадковості, "
              f"z={null['z']:+.2f}")
    for t in tracks[:12]:
        print(f"  #{t['id']:<4} {t['n']:2} точок  {t['km']:4} км  {t['hours']:4.1f} год  "
              f"{t['kmh']:3} км/год  курс {t['course']:3}°  "
              f"{(t['from'] or '')[:16]:17} -> {(t['to'] or '')[:16]}")

    # Назви для читача підставляються тут, а не в JS карти: обидві сторони
    # (подія і region_geo) мають лишитись узгодженими, бо карта зшиває їх за
    # цим рядком. Перейменувати ключі у сховищі не можна — вони в кожній події.
    for e in events:
        if e.get("region"):
            e["region"] = region_label(e["region"])
        # place теж несе ключ, коли подія стосується цілої області
        if e.get("place"):
            e["place"] = region_label(e["place"])
    out = {"date": date, "events": events, "vectors": vecs, "tracks": tracks,
           "null": null,
           "region_geo": {region_label(k): list(v) for k, v in cfg.geo.items()}}
    fn = f"raid_{date}.json"
    json.dump(out, open(fn, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n-> {fn}")


if __name__ == "__main__":
    main(*sys.argv[1:])
