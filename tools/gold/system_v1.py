#!/usr/bin/env python3
"""Що видає ЧИННИЙ розбір на постах еталона — для `score.py`.

  python3 tools/gold/system_v1.py [вихід]   # -> tests/data/gold/sys_v1.jsonl

Вибір крапки повторює `Store._event` (пуск -> джерело, інакше
`point_entity`, далі область поста, далі будь-яка сутність) і відкат за
санітарною межею 400 км. Ланки — з `vectors.parse` (сирі назви, щоб знайти
їх у тексті за позицією). Пости розбираються ОДНИМ пакетом, як у збірці.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tgmine import extract as E, geocode as GC, store as ST, vectors as V  # noqa: E402
import sync  # noqa: E402

SHOWN = lambda ev: ev["scope"] == "точка" and ev["lat"] and ev["geo_conf"] not in ("centroid", "region-snap")


def span_of(text, name, start=0):
    i = text.find(name, start)
    return None if i < 0 else [i, i + len(name)]


def main(out=None):
    gold = [json.loads(l) for l in open(ROOT / "tests/data/gold/posts.jsonl", encoding="utf-8")]
    cfg = E.Config.load(ROOT / sync.CONFIG)
    gaz = GC.Gazetteer.load(*[ROOT / g for g in sync.GAZ])
    posts = [{"channel": g["channel"], "id": int(g["id"].rsplit("/", 1)[1]), "url": g["id"],
              "date": g["date"] + ":00+00:00", "text": g["text"]} for g in gold]
    posts = E.enrich(posts, cfg)
    GC.geocode_posts(posts, gaz, cfg.geo, aliases=cfg.geo_aliases,
                     region_a1=gaz.region_codes(cfg.entities.get("регіон", {}), cfg.geo))
    st = ST.Store.__new__(ST.Store)
    rows = []
    for p in posts:
        ev = st._event(p, cfg)
        k = ev["kind"]
        best = (ST.launch_origin(p) if k == "пуск" else None) or ST.point_entity(p)
        span = None
        if best and best.get("pos") is not None and best.get("match"):
            span = [best["pos"], best["pos"] + len(str(best["match"]))]
        legs = []
        for v in V.parse(p["text"]):
            flat = " ".join(l.strip() for l in p["text"].split("\n"))
            if v["src"] and v["dst"]:
                legs.append([v["src"][-1], v["dst"][0]])
        rows.append({"id": p["url"], "kind": k, "scope": ev["scope"], "geo_conf": ev["geo_conf"],
                     "shown": bool(SHOWN(ev)), "aim": ev["aim"], "point": span,
                     "point_text": p["text"][span[0]:span[1]] if span else None,
                     "places": [span] if span and SHOWN(ev) else [], "legs": legs})
    dst = Path(out) if out else ROOT / "tests/data/gold/sys_v1.jsonl"
    with open(dst, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(len(rows), "->", dst)


if __name__ == "__main__":
    main(*sys.argv[1:])
