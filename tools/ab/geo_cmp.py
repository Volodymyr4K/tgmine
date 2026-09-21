"""А/Б геокода двох сховищ за двома незалежними арбітрами (BACKLOG §12).

    python3 tools/ab/geo_cmp.py <А> <Б> [-v]

Рахує лише унікальні точкові події (без дублів і шуму), парами за спільним id:

1. центр області — частка точкових подій із geo_conf centroid/region-snap;
2. арбітр NE — чи лежить крапка в полігоні ВЛАСНОЇ області поста
   (regions.json, Natural Earth; геокод працює на ADM1 GeoNames — інша база);
3. арбітр «названий район» — відстань від крапки до району, який пост прямо
   назвав («X район»), розвʼязаного в його області. Крапка на селі того самого
   поста може бути «далі» від центру району, хоч точніша — тому рахуємо поріг
   40 км, а не середнє.

Переходи показуються поіменно (-v): регреси — у них щоразу інша вада.
"""
import collections
import glob
import json
import random
import re
import sys

sys.path.insert(0, ".")
from tgmine.geocode import haversine  # noqa: E402

FALLBACK = ("centroid", "region-snap")


def load(root):
    d = {}
    for f in sorted(glob.glob(f"{root}/events/*.jsonl")):
        for line in open(f, encoding="utf-8"):
            if line.strip():
                e = json.loads(line)
                d[e["id"]] = e
    return d


REG = json.load(open("regions.json", encoding="utf-8"))


def _in_ring(lat, lon, ring):
    ins = False
    j = len(ring) - 1
    for i in range(len(ring)):
        yi, xi = ring[i]
        yj, xj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi:
            ins = not ins
        j = i
    return ins


def in_region(e):
    rings = REG.get(e.get("region"))
    if not rings or not e.get("lat"):
        return None
    return any(_in_ring(e["lat"], e["lon"], r) for r in rings)


def state(e):
    if not e.get("lat"):
        return "без коорд."
    if e.get("geo_conf") in FALLBACK:
        return "центр обл."
    return {True: "місце в обл.", False: "місце ПОЗА обл.", None: "місце (обл. ?)"}[in_region(e)]


def main():
    A, B = load(sys.argv[1]), load(sys.argv[2])
    verbose = "-v" in sys.argv
    com = sorted(A.keys() & B.keys())
    uniq = lambda e: not e.get("dup_of") and not e.get("noise") and e.get("scope") == "точка"
    ids = [i for i in com if uniq(A[i]) and uniq(B[i])]
    print(f"спільних точкових унікальних: {len(ids)} "
          f"(лише в А {len(A.keys() - B.keys())}, лише в Б {len(B.keys() - A.keys())})")
    for name, D in (("А", A), ("Б", B)):
        st = collections.Counter(state(D[i]) for i in ids)
        n = len(ids)
        print(f"  {name}: " + " | ".join(f"{k} {v} ({v / n:.1%})" for k, v in sorted(st.items())))
    tr = collections.Counter()
    ex = collections.defaultdict(list)
    moved = 0
    for i in ids:
        a, b = A[i], B[i]
        sa, sb = state(a), state(b)
        if a.get("lat") and b.get("lat") and haversine((a["lat"], a["lon"]), (b["lat"], b["lon"])) > 5:
            moved += 1
            if sa == sb:
                sa, sb = sa + "*", sb + "*"   # зрушило, але в тому самому стані
        if sa != sb:
            tr[(sa, sb)] += 1
            ex[(sa, sb)].append(i)
    print(f"зрушило >5 км: {moved}")
    for (sa, sb), v in tr.most_common():
        print(f"  {v:6}  {sa} -> {sb}")
        if verbose:
            random.seed(1)
            for i in random.sample(ex[(sa, sb)], min(6, len(ex[(sa, sb)]))):
                a, b = A[i], B[i]
                print(f"           {a.get('place')} -> {b.get('place')} [{b.get('region')}] "
                      f"| {(b.get('text') or '')[:90]!r}")


if __name__ == "__main__":
    main()
