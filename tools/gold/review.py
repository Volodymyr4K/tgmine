#!/usr/bin/env python3
"""Аркуш звірки еталона для оператора: 30 вирішених спірних + 20 випадкових
узгоджених постів (згода двох розмітників не доводить правильність).
  python3 tools/gold/review.py  -> tests/data/gold/REVIEW.md"""
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
G = ROOT / "tests/data/gold"
NAMES = {"here": "ТУТ", "from": "звідки", "to": "куди", "via": "через", "ctx": "уточнення"}


def fmt(g):
    ms = []
    for m in g["mentions"]:
        flags = [f for f in ("conv", "maybe", "seg") if m.get(f)]
        ms.append(f"**{m['text']}** — {NAMES[m['role']]}" + (f" ({', '.join(flags)})" if flags else ""))
    legs = "; ".join(f"{a} → {b}" for a, b in g.get("legs", [])) or "—"
    return ms, legs


def main():
    posts = {json.loads(l)["id"]: json.loads(l) for l in open(G / "posts.jsonl", encoding="utf-8")}
    labels = [json.loads(l) for l in open(G / "labels.jsonl", encoding="utf-8")]
    rng = random.Random(22)
    disp = [g for g in labels if g["source"] != "agree"]
    agree = [g for g in labels if g["source"] == "agree"]
    pick = rng.sample(disp, min(30, len(disp))) + rng.sample(agree, 20)
    rng.shuffle(pick)
    out = ["# Звірка еталона — 50 постів",
           "",
           "Для кожного поста: чи правильно розмічено, ДЕ БАЧИЛИ (ТУТ), звідки й куди",
           "летить, і вид події. Якщо щось не так — допиши поруч, як має бути.",
           "Змішано навмання: частину розмітники оцінили по-різному (і я вирішив),",
           "частину — однаково. Які саме — не видно навмисно.",
           ""]
    for n, g in enumerate(pick, 1):
        ms, legs = fmt(g)
        out += [f"## {n}. {posts[g['id']]['channel']} · {g['id']}", "",
                "```", posts[g["id"]]["text"], "```", "",
                f"- вид: **{g['kind']}**"]
        out += [f"- {m}" for m in ms] or ["- (місць нема)"]
        out += [f"- рух: {legs}", "- [ ] правильно   · виправлення: ", ""]
    (G / "REVIEW.md").write_text("\n".join(out), encoding="utf-8")
    print("->", G / "REVIEW.md")


if __name__ == "__main__":
    main()
