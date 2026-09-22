#!/usr/bin/env python3
"""Еталон = згода A і B + рішення по спірних (`decisions_*.json`).
Ланки — обʼєднання обох розміток (різниця між «кожне місце -> ціль»,
«останнє -> ціль» і ланцюгом не є помилкою жодної сторони; score.py
зараховує ланку за ціллю і будь-яким джерелом із поста).
  python3 tools/gold/merge.py A.jsonl B.jsonl decisions.json"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main(a, b, dec):
    A = {json.loads(l)["id"]: json.loads(l) for l in open(a, encoding="utf-8") if l.strip()}
    B = {json.loads(l)["id"]: json.loads(l) for l in open(b, encoding="utf-8") if l.strip()}
    D = {k: v for k, v in json.load(open(dec, encoding="utf-8")).items() if k != "_"}
    out = []
    for i in sorted(A):
        side, kind, why = D.get(i, ("A", None, None))
        g = dict((A if side == "A" else B)[i])
        if kind:
            g["kind"] = kind
        legs = [tuple(l) for l in A[i].get("legs", [])] + [tuple(l) for l in B[i].get("legs", [])]
        names = [m["text"] for m in g["mentions"]]

        def fit(x):
            # кінець з іншої розмітки може бути ширшим («с. Подсереднее»)
            return x if x in names else next((n for n in names if n in x or x in n), None)
        legs = [(fit(x), fit(y)) for x, y in legs]
        g["legs"] = [list(l) for l in dict.fromkeys(legs) if l[0] and l[1] and l[0] != l[1]]
        g["source"] = "agree" if i not in D else f"adjudicated:{side}"
        out.append(g)
    dst = ROOT / "tests/data/gold/labels.jsonl"
    with open(dst, "w", encoding="utf-8") as f:
        for g in out:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")
    print(len(out), "->", dst, "; вирішено спірних:", sum(1 for g in out if g["source"] != "agree"))


if __name__ == "__main__":
    main(*sys.argv[1:])
