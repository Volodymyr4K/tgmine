#!/usr/bin/env python3
"""Міри розбору проти еталона ролей (GUIDE.md).

  python3 tools/gold/score.py tests/data/gold/sys_v1.jsonl [--split dev|test|all]

Зіставлення — за позицією: спан згадки еталона (перший збіг `text` після
попередньої згадки) проти спанів, які видав розбір. Перетин спанів = та сама
згадка.

Міри (усі — частки постів чи згадок; «зв.» — зважено `w`, «опер.» —
`w * occ`, тобто як часто це бачить оператор; [a–b] — 90% бутстреп):
  крапка:   з показаних крапок (`shown`) — на here / to / from / via / ctx /
            на неназві (сутності, якої в еталоні нема); `+conv` — роль, яку
            звичай каналів робить місцем («От X» першим, «в вашем
            направлении»), рахується окремо;
  повнота:  з here-згадок еталона в постах-спостереженнях — скільки показано;
  ланки:    P/R пар [звідки, куди] за спанами кінців.
"""
import argparse
import collections
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOLD = ROOT / "tests/data/gold"
OBS = {"фіксація", "ППО", "збиття", "вибух", "пуск"}
CATS = ("here", "from+conv", "to+conv", "to", "from", "via", "ctx", "неназва")


def spans(text, mentions):
    out, cur = [], 0
    for m in mentions:
        i = text.find(m["text"], cur)
        if i < 0:
            i = text.find(m["text"])
        if i < 0:
            out.append(None)
            continue
        out.append((i, i + len(m["text"])))
        cur = i + 1
    return out


def hit(a, b):
    return a and b and a[0] < b[1] and b[0] < a[1]


def role_at(span, text, gold):
    for m, s in zip(gold["mentions"], spans(text, gold["mentions"])):
        if hit(span, s):
            return m["role"] + ("+conv" if m.get("conv") and m["role"] != "here" else "")
    return "неназва"


def leg_spans(text, gold_or_sys, key_text):
    out = []
    for a, b in gold_or_sys:
        sa, sb = text.find(a), text.find(b)
        if sa >= 0 and sb >= 0:
            out.append(((sa, sa + len(a)), (sb, sb + len(b))))
    return out


def boot(vals, weights, n=1000, seed=1):
    rng = random.Random(seed)
    idx = list(range(len(vals)))
    est = []
    for _ in range(n):
        s = [rng.choice(idx) for _ in idx]
        w = sum(weights[i] for i in s)
        est.append(sum(vals[i] * weights[i] for i in s) / w if w else 0)
    est.sort()
    return est[int(0.05 * n)], est[int(0.95 * n)]


def rate(rows, key):
    """rows: [(value 0/1, w, occ)] -> рядок з трьома оцінками."""
    if not rows:
        return "—"
    v = [r[0] for r in rows]
    w = [r[1] for r in rows]
    o = [r[1] * r[2] for r in rows]
    raw = sum(v) / len(v)
    zw = sum(a * b for a, b in zip(v, w)) / sum(w)
    zo = sum(a * b for a, b in zip(v, o)) / sum(o)
    lo, hi = boot(v, o)
    return f"{raw:6.1%}  зв.{zw:6.1%}  опер.{zo:6.1%} [{lo:.0%}–{hi:.0%}]  n={len(v)}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("system")
    ap.add_argument("--split", default="dev")
    ap.add_argument("--labels", default=str(GOLD / "labels.jsonl"))
    a = ap.parse_args()
    posts = {json.loads(l)["id"]: json.loads(l) for l in open(GOLD / "posts.jsonl", encoding="utf-8")}
    gold = {json.loads(l)["id"]: json.loads(l) for l in open(a.labels, encoding="utf-8")}
    sysr = {json.loads(l)["id"]: json.loads(l) for l in open(a.system, encoding="utf-8")}
    ids = [i for i in gold if i in sysr and (a.split == "all" or posts[i]["split"] == a.split)]

    point = collections.defaultdict(list)
    recall, lp, lr, kind_ok = [], [], [], []
    for i in ids:
        p, g, s = posts[i], gold[i], sysr[i]
        w, occ, text = p["w"], p["occ"], p["text"]
        kind_ok.append((int(s["kind"] == g["kind"]), w, occ))
        if s.get("shown") and s.get("point"):
            r = role_at(tuple(s["point"]), text, g)
            for k in CATS:
                point[k].append((int(r == k), w, occ))
        if g["kind"] in OBS:
            gs = [sp for m, sp in zip(g["mentions"], spans(text, g["mentions"])) if m["role"] == "here" and sp]
            shown = [tuple(x) for x in s.get("places", [])]
            for sp in gs:
                recall.append((int(any(hit(sp, x) for x in shown)), w, occ))
        # Ланка: ціль має бути кінцем ланки еталона, джерело — будь-яким
        # here/from/via поста або початком ланки еталона (розмітники
        # розходились у «кожне місце -> ціль» / «останнє -> ціль» / ланцюг,
        # і це не помилка жодного — merge.py).
        gsp = spans(text, g["mentions"])
        byname = {m["text"]: sp for m, sp in zip(g["mentions"], gsp)}
        ends = [byname.get(y) for _, y in g.get("legs", []) if byname.get(y)]
        starts = [byname.get(x) for x, _ in g.get("legs", []) if byname.get(x)]
        starts += [sp for m, sp in zip(g["mentions"], gsp) if sp and m["role"] in ("here", "from", "via")]
        sl = leg_spans(text, s.get("legs", []), False)
        for x in sl:
            lp.append((int(any(hit(x[1], e) for e in ends) and any(hit(x[0], b) for b in starts)), w, occ))
        for e in dict.fromkeys(ends):
            lr.append((int(any(hit(x[1], e) for x in sl)), w, occ))
    print(f"{a.system}  split={a.split}  постів={len(ids)}")
    print("вид поста збігся      ", rate(kind_ok, 0))
    print("крапка (показані):")
    for k in CATS:
        print(f"   на {k:10}        ", rate(point[k], k))
    print("повнота here (спост.) ", rate(recall, 0))
    print("ланки: точність       ", rate(lp, 0))
    print("ланки: повнота        ", rate(lr, 0))


if __name__ == "__main__":
    main()
