#!/usr/bin/env python3
"""Ранжує цілі за важливістю = тип (ярус) × емпіричний жар.

Важливість не вигадана, а виведена: «жар» — скільки разів за весь період
у сховищі біля цілі фіксували активність. Тип задає базовий ярус і зум-gating,
жар додає ваги конкретному об'єкту.

Записує в targets.json для кожного обʼєкта: tier (1..3) і hits (жар).

  python3 rank_targets.py
"""
import collections
import glob
import json
import math
import sys
from pathlib import Path

from tgmine.atomic import write_text
from tgmine.store import target_id

# Ярус за типом. 1 — стратегічні цілі (по яких б'ють кампанією), 3 — тло.
TIER = {
    "refinery": 1, "defense_plant": 1, "ammo_depot": 1, "airfield": 1,
    "chemical": 1, "fuel_depot": 2, "naval": 2,
    "military_base": 3, "range": 3,
}
OUT = Path("targets.json")


def main():
    # емпіричний жар: скільки разів обʼєкт був найближчою ціллю за весь період.
    # Ключ — tid, не назва: назви не унікальні, і join за ними роздував жар у
    # 2.81 раза (кожен обʼєкт-тезка отримував ПОВНИЙ лік свого імені).
    hits = collections.Counter()
    stale = 0
    for f in glob.glob("store/events/*.jsonl"):
        for line in open(f, encoding="utf-8"):
            if not line.strip():
                continue
            e = json.loads(line)
            if (e.get("dup_of") or e.get("noise") or e.get("scope") != "точка"):
                continue
            n = e.get("near")
            if not n:
                continue
            if n.get("tid"):
                hits[n["tid"]] += 1
            else:
                stale += 1

    if stale:
        print(f"! {stale} подій без near.tid — сховище зібране старим "
              f"конвеєром (< v9).\n  Спершу: python3 sync.py --rebuild",
              file=sys.stderr)
        return 1

    data = json.load(open(OUT, encoding="utf-8"))
    for o in data["objects"]:
        o["tier"] = TIER.get(o["cat"], 3)
        o["hits"] = hits.get(target_id(o), 0)
        # importance: ярус домінує, жар додає в межах ярусу (log, щоб один
        # гучний обʼєкт не забивав решту). 0..~1.
        base = {1: 0.66, 2: 0.4, 3: 0.15}[o["tier"]]
        heat = math.log1p(o["hits"]) / math.log1p(200)      # 200 подій ~ максимум
        o["imp"] = round(min(1.0, base + heat * 0.34), 3)

    data["objects"].sort(key=lambda o: -o["imp"])
    # Атомарно: скрипт тепер у cron кожні 30 хв, а обрубок targets.json коштує
    # повторного fetch_targets.py — 10 хвилин мережі.
    write_text(OUT, json.dumps(data, ensure_ascii=False))

    hot = [o for o in data["objects"] if o["hits"] > 0]
    print(f"обʼєктів: {len(data['objects'])}, з активністю поруч: {len(hot)}")
    print("\n== топ-15 за важливістю ==")
    for o in data["objects"][:15]:
        print(f"  imp={o['imp']:.2f}  T{o['tier']}  {o['hits']:4}×  "
              f"[{o['cat']:13}] {(o['name'] or '(без назви)')[:40]}")
    return 0


if __name__ == "__main__":
    # код виходу важливий: у CI цей крок має валити збірку, а не мовчати
    raise SystemExit(main())
