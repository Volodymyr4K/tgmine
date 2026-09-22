#!/usr/bin/env python3
"""Вид голих постів проти розмітки з контекстом (22.09.2026).

  python3 tools/ctx/score.py            # обидві вибірки

`dev/` — 150 постів «інше» з крапкою за 22.08-21.09 (голі, «меры
безопасности», апарат названий без тригера), `test/` — свіжі 100 за
24.07-22.08 (лише голі й «меры»), відібрані ПІСЛЯ того, як правило
зафіксовано. Кожен пост розмічено двома незалежними розмітниками
(A — Opus, B — Sonnet) за `GUIDE.md`, з контекстом: відповідь, пости свого
каналу до/після, пости інших каналів ≤60 км ±45 хв. Міра — лише пости, де
розмітники згодні; «ін.» = усе, крім фіксації й тривоги.

Порівнюється вид із коду (`kind_of` + `context_kinds`) з тим, що було до
v27 (усе це — «інше»). Сусідів з інших постів код не бере, тож досить
розібрати самі пости й батьків-відповідей.
"""
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tgmine import extract as E, geocode as GC, store as ST  # noqa: E402
import sync  # noqa: E402

HERE = Path(__file__).resolve().parent
red = lambda k: k if k in ("фіксація", "тривога") else "ін."


def load(split):
    rd = lambda f: [json.loads(l) for l in open(HERE / split / f, encoding="utf-8")]
    return rd("items.jsonl"), rd("ann_A.jsonl"), rd("ann_B.jsonl")


def events(ids, cfg, gaz):
    want = collections.defaultdict(set)
    for i in ids:
        ch, n = i.split("/")
        want[ch].add(int(n))
    raw = {}
    for ch in want:
        for l in open(ROOT / "data" / f"{ch}.jsonl", encoding="utf-8"):
            p = json.loads(l)
            raw[(ch, p["id"])] = p
    posts = []
    for ch, ns in want.items():
        for n in ns:
            p = raw[(ch, n)]
            posts.append(p)
            par = ST._parent_id(p)          # батько-відповідь теж у пакет
            if par:
                pc, pn = par.split("/")
                if (pc, int(pn)) in raw:
                    posts.append(raw[(pc, int(pn))])
    posts = E.enrich(sorted({(p["channel"], p["id"]): p for p in posts}.values(),
                            key=lambda p: p["date"]), cfg)
    GC.geocode_posts(posts, gaz, cfg.geo, aliases=cfg.geo_aliases,
                     region_a1=gaz.region_codes(cfg.entities.get("регіон", {}), cfg.geo))
    ST.link_replies(posts)
    st = ST.Store.__new__(ST.Store)
    evs = [st._event(p, cfg) for p in posts]
    ST.context_kinds(evs)
    return {e["id"]: e for e in evs}


def main():
    cfg = E.Config.load(ROOT / sync.CONFIG)
    gaz = GC.Gazetteer.load(*[ROOT / g for g in sync.GAZ])
    for split in ("dev", "test"):
        items, A, B = load(split)
        ev = events([i["id"] for i in items], cfg, gaz)
        cm = collections.Counter()
        agree = 0
        for i, a, b in zip(items, A, B):
            assert i["id"] == a["id"] == b["id"]
            if a["kind"] != b["kind"]:
                continue
            agree += 1
            cm[(red(a["kind"]), red(ev[i["id"]]["kind"]))] += 1
        ok = sum(v for (g, p), v in cm.items() if g == p)
        was = sum(v for (g, p), v in cm.items() if g == "ін.")
        fp = sum(v for (g, p), v in cm.items() if p == "фіксація" and g != "фіксація")
        print(f"{split}: згода розмітників {agree}/{len(items)}; вид збігся {ok}/{agree} "
              f"({ok / agree:.0%}), до v27 {was}/{agree} ({was / agree:.0%}); "
              f"фіксація TP {cm[('фіксація', 'фіксація')]} FP {fp}")
        for (g, p), v in sorted(cm.items()):
            print(f"   розмітка {g:9} код {p:9} {v}")


if __name__ == "__main__":
    main()
