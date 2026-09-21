"""Другий арбітр (BACKLOG §12): відстань крапки до району, який пост ПРЯМО назвав.

    python3 tools/ab/district_cmp.py <А> <Б>

Беруться точкові унікальні події, у першому рядку яких стоїть «X-ский район»
(називний відмінок), і цей район розвʼязується в області поста. Для кожної —
відстань від крапки до центру названого району: ≤40 км, >40 км чи центр
області. Незалежний від мітки області: полігонний арбітр (`geo_cmp.py`) карає
крапку, що пішла з хибно приписаної області, а цей — ні.

Застереження: район шукається ПОТОЧНИМ газетиром. Якщо правка сама додає
райони в газетир (як 21 вересня — наголоси в назвах), частина виграшу
закладена побудовою заміру; чесна частина — регреси («було ≤40, стало >40»),
вони друкуються поіменно. Крапка на СЕЛІ з того самого поста може бути далі
від центру району й при цьому точнішою — регреси читати очима.
"""
import collections
import glob
import json
import re
import sys

sys.path.insert(0, ".")
from tgmine import extract as E, geocode as GC  # noqa: E402

RX = re.compile(r"([А-ЯЁ][а-яё\-]+(?:ский|цкий))\s+район")
FALLBACK = ("centroid", "region-snap")


def load(root):
    d = {}
    for f in glob.glob(f"{root}/events/*.jsonl"):
        for line in open(f, encoding="utf-8"):
            if line.strip():
                e = json.loads(line)
                d[e["id"]] = e
    return d


def main():
    cfg = E.Config.load("configs/ru-monitor.yaml")
    gaz = GC.Gazetteer.load("gazetteer/RU.txt", "gazetteer/UA.txt")
    rc = gaz.region_codes(cfg.entities.get("регіон", {}), cfg.geo)
    A, B = load(sys.argv[1]), load(sys.argv[2])
    cache = {}

    def district(adj, reg):
        if (adj, reg) not in cache:
            codes = rc.get(reg)
            cache[(adj, reg)] = next(
                (c for c in gaz.by_name.get(GC.norm(adj + " район"), [])
                 if codes and (c["cc"], c["a1"]) in codes), None)
        return cache[(adj, reg)]

    def state(e, d):
        if not e.get("lat"):
            return "без коорд."
        if e.get("geo_conf") in FALLBACK:
            return "центр обл."
        return "≤40км" if GC.haversine((e["lat"], e["lon"]), (d["lat"], d["lon"])) <= 40 else ">40км"

    st = collections.Counter()
    regress = []
    for i, a in A.items():
        b = B.get(i)
        if not b or a.get("scope") != "точка" or a.get("dup_of") or a.get("noise"):
            continue
        m = RX.search(a["text"].split("\n")[0])
        d = m and district(m.group(1), a.get("region"))
        if not d:
            continue
        sa, sb = state(a, d), state(b, d)
        st["n"] += 1
        st["А " + sa] += 1
        st["Б " + sb] += 1
        if sa == "≤40км" and sb != "≤40км":
            regress.append((i, a.get("place"), b.get("place"), sb, a["text"][:100]))
    print(dict(sorted(st.items())))
    print("регресів (було ≤40 км, стало гірше):", len(regress))
    for r in regress[:40]:
        print("  ", *r)


if __name__ == "__main__":
    main()
