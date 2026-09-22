#!/usr/bin/env python3
"""Перевірка файла розмітки: формат, ролі, `text` — точний підрядок поста,
кінці ланок — серед згадок.   python3 tools/gold/validate.py <labels.jsonl> [posts.jsonl]"""
import json
import sys
from pathlib import Path

ROLES = {"here", "from", "to", "via", "ctx"}
KINDS = {"фіксація", "тривога", "відбій", "ППО", "збиття", "вибух", "пуск", "огляд", "інше"}
TYPES = {"нп", "район", "область", "вода", "обʼєкт", "частина", "інше"}


def main(labels, posts=None):
    posts = posts or Path(__file__).resolve().parents[2] / "tests/data/gold/posts.jsonl"
    text = {}
    for l in open(posts, encoding="utf-8"):
        p = json.loads(l)
        text[p["id"]] = p["text"]
    errs, n = [], 0
    for i, l in enumerate(open(labels, encoding="utf-8"), 1):
        if not l.strip():
            continue
        try:
            g = json.loads(l)
        except Exception as e:
            errs.append(f"рядок {i}: не JSON ({e})")
            continue
        n += 1
        t = text.get(g.get("id"))
        if t is None:
            errs.append(f"рядок {i}: невідомий id {g.get('id')}")
            continue
        if g.get("kind") not in KINDS:
            errs.append(f"{g['id']}: kind {g.get('kind')!r}")
        ms = g.get("mentions", [])
        for m in ms:
            if m.get("role") not in ROLES:
                errs.append(f"{g['id']}: роль {m.get('role')!r}")
            if m.get("type") not in TYPES:
                errs.append(f"{g['id']}: тип {m.get('type')!r} у {m.get('text')!r}")
            if not m.get("text") or m["text"] not in t:
                errs.append(f"{g['id']}: text не підрядок: {m.get('text')!r}")
        names = {m.get("text") for m in ms}
        for leg in g.get("legs", []):
            if len(leg) != 2 or leg[0] not in names or leg[1] not in names:
                errs.append(f"{g['id']}: ланка {leg} — кінці не серед згадок")
    missing = set(text) - {json.loads(l)["id"] for l in open(labels, encoding="utf-8") if l.strip()}
    print(f"розмічено {n}; помилок {len(errs)}; без розмітки {len(missing)} (якщо файл — частина, це нормально)")
    for e in errs[:60]:
        print("  ", e)
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
