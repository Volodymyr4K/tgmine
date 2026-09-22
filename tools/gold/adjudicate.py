#!/usr/bin/env python3
"""Звірка двох незалежних розміток еталона.

  python3 tools/gold/adjudicate.py A.jsonl B.jsonl [--out <тека>]

Згадки зіставляються за позицією в тексті (як у score.py). Рахує:
  - згоду щодо виду поста;
  - згоду щодо НАБОРУ згадок (скільки знайшов лише один);
  - каппу Коена по ролях на спільних згадках;
  - згоду щодо ланок.
Пише у <тека>: `agreed.jsonl` (пости без жодної розбіжності — згода A і B),
`disputes.jsonl` (пост, обидві версії, перелік розбіжностей) — їх судить
людина (або суддя) поіменно, результат — `labels.jsonl`.
"""
import argparse
import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOLD = ROOT / "tests/data/gold"


def spans(text, mentions):
    out, cur = [], 0
    for m in mentions:
        i = text.find(m["text"], cur)
        if i < 0:
            i = text.find(m["text"])
        out.append(None if i < 0 else (i, i + len(m["text"])))
        cur = i + 1 if i >= 0 else cur
    return out


def hit(a, b):
    return a and b and a[0] < b[1] and b[0] < a[1]


def kappa(pairs):
    n = len(pairs)
    if not n:
        return float("nan")
    po = sum(a == b for a, b in pairs) / n
    ca = collections.Counter(a for a, _ in pairs)
    cb = collections.Counter(b for _, b in pairs)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / n / n
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def role_key(m):
    return m["role"] + ("+conv" if m.get("conv") else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--out", default=str(GOLD))
    a = ap.parse_args()
    posts = {json.loads(l)["id"]: json.loads(l) for l in open(GOLD / "posts.jsonl", encoding="utf-8")}
    A = {json.loads(l)["id"]: json.loads(l) for l in open(a.a, encoding="utf-8") if l.strip()}
    B = {json.loads(l)["id"]: json.loads(l) for l in open(a.b, encoding="utf-8") if l.strip()}
    ids = sorted(set(A) & set(B))
    C = collections.Counter()
    role_pairs, agreed, disputes = [], [], []
    confusion = collections.Counter()
    for i in ids:
        t = posts[i]["text"]
        x, y = A[i], B[i]
        issues = []
        if x["kind"] != y["kind"]:
            C["kind_diff"] += 1
            issues.append(f"вид: {x['kind']} / {y['kind']}")
        sx, sy = spans(t, x["mentions"]), spans(t, y["mentions"])
        used = set()
        for mx, px in zip(x["mentions"], sx):
            j = next((j for j, py in enumerate(sy) if j not in used and hit(px, py)), None)
            if j is None:
                C["only_a"] += 1
                issues.append(f"лише A: {mx['text']} ({mx['role']})")
                continue
            used.add(j)
            my = y["mentions"][j]
            C["both"] += 1
            role_pairs.append((mx["role"], my["role"]))
            if role_key(mx) != role_key(my):
                confusion[(role_key(mx), role_key(my))] += 1
                issues.append(f"роль {mx['text']}: {role_key(mx)} / {role_key(my)}")
        for j, my in enumerate(y["mentions"]):
            if j not in used:
                C["only_b"] += 1
                issues.append(f"лише B: {my['text']} ({my['role']})")
        lx = {tuple(l) for l in x.get("legs", [])}
        ly = {tuple(l) for l in y.get("legs", [])}
        C["legs_both"] += len(lx & ly)
        C["legs_diff"] += len(lx ^ ly)
        if lx != ly:
            issues.append(f"ланки: A {sorted(lx)} / B {sorted(ly)}")
        if issues:
            disputes.append({"id": i, "text": t, "issues": issues, "A": x, "B": y})
        else:
            agreed.append(x)
    out = Path(a.out)
    with open(out / "agreed.jsonl", "w", encoding="utf-8") as f:
        for g in agreed:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")
    with open(out / "disputes.jsonl", "w", encoding="utf-8") as f:
        for d in disputes:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    n = len(ids)
    print(f"постів {n}; без розбіжностей {len(agreed)} ({len(agreed)/n:.0%}); спірних {len(disputes)}")
    print(f"вид різний: {C['kind_diff']}")
    print(f"згадки: спільні {C['both']}, лише A {C['only_a']}, лише B {C['only_b']}")
    print(f"каппа ролей (спільні згадки): {kappa(role_pairs):.3f}")
    print(f"ланки: спільні {C['legs_both']}, розбіжні {C['legs_diff']}")
    print("найчастіші розбіжності ролей:", confusion.most_common(8))


if __name__ == "__main__":
    main()
