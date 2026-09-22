#!/usr/bin/env python3
"""Вибірка постів для еталона ролей (BACKLOG §16.9, крок 1).

  python3 tools/gold/sample.py            # -> tests/data/gold/posts.jsonl

Одиниця — УНІКАЛЬНИЙ текст (нормалізований як у `dedupe.norm`): однакові
шаблонні пости («Борисоглебск / Воронежская область / Еще фиксации БПЛА»)
розмічати двічі нема сенсу. Скільки разів текст трапився — поле `occ`, ним
зважується міра «як часто це бачить оператор».

Розбиття — ЗА ЧАСОМ, не випадкове: dev (на ньому правимо правила) і test
(не дивимось, поки не закінчимо крок). Текст, що вже був у dev-періоді, у
test не йде — інакше шаблон, під який підігнали правило, пройде «чесну»
перевірку сам собою.

Страти — канал × клас (F — спостереження, A — тривога/відбій, O — інше) ×
«складний» (кілька рядків-місць або слово руху). Складні вибираються
частіше; поле `w` = N_страти / n_страти повертає справжні пропорції.
Вибір детермінований (сід), повторний запуск дає той самий файл.
"""
import collections
import json
import random
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tgmine import dedupe as D, extract as E, store as ST  # noqa: E402
import sync  # noqa: E402

DEV = ("2026-08-22", "2026-09-10")
TEST = ("2026-09-11", "2026-09-21")
N = {"dev": 240, "test": 160}
CLASS_SHARE = {"F": 0.5, "A": 0.35, "O": 0.15}
HARD_SHARE = 0.5
SEED = 20260922

MOTION = re.compile(r"направлени|сторону|далее|курсом|\bна\s+[А-ЯЁ]|через|"
                    r"с\s+выходом|\bот\s+[А-ЯЁ]|пролёт|пролет", re.I)
FCLASS = {"фіксація", "ППО", "збиття", "вибух", "пуск"}
ACLASS = {"тривога", "відбій"}


def klass(kind):
    return "F" if kind in FCLASS else "A" if kind in ACLASS else "O"


def hard(text):
    lines = [l for l in text.split("\n") if l.strip()]
    caps = sum(1 for l in lines if re.match(r"\s*[А-ЯЁ][а-яё]", l))
    return bool(MOTION.search(text)) or caps >= 3


def main():
    cfg = E.Config.load(ROOT / sync.CONFIG)
    groups = {}                         # norm -> запис
    for ch in sync.CHANNELS:
        for line in open(ROOT / "data" / f"{ch}.jsonl", encoding="utf-8"):
            p = json.loads(line)
            d = datetime.fromisoformat(p["date"]).astimezone(ST.MSK).strftime("%Y-%m-%d")
            if not (DEV[0] <= d <= TEST[1]) or not p["text"].strip():
                continue
            key = D.norm(p["text"])
            g = groups.get(key)
            if g is None or p["date"] < g["date"]:
                occ = g["occ"] if g else 0
                g = groups[key] = {"url": p["url"], "channel": ch, "date": p["date"],
                                   "d": d, "text": p["text"], "occ": occ}
            g["occ"] += 1
    strata = collections.defaultdict(list)
    for g in groups.values():
        split = "dev" if g["d"] <= DEV[1] else "test"
        clean, _ = ST.strip_promo(g["text"], cfg)
        k = klass(ST.kind_of(clean))
        strata[(split, g["channel"], k, hard(g["text"]))].append(g)
    rng = random.Random(SEED)
    out = []
    for split, n in N.items():
        chans = {c: sum(len(v) for (s, cc, _, _), v in strata.items()
                        if s == split and cc == c) ** 0.5 for c in sync.CHANNELS}
        tot = sum(chans.values())
        for ch in sync.CHANNELS:
            for k, share in CLASS_SHARE.items():
                for h in (True, False):
                    pop = sorted(strata.get((split, ch, k, h), []), key=lambda g: g["url"])
                    want = round(n * chans[ch] / tot * share
                                 * (HARD_SHARE if h else 1 - HARD_SHARE))
                    take = rng.sample(pop, min(want, len(pop)))
                    for g in take:
                        out.append({"id": g["url"], "channel": ch, "date": g["date"][:16],
                                    "split": split, "stratum": f"{ch}|{k}|{'hard' if h else 'easy'}",
                                    "w": round(len(pop) / len(take), 3), "occ": g["occ"],
                                    "text": g["text"]})
    out.sort(key=lambda r: (r["split"], r["id"]))
    dst = ROOT / "tests" / "data" / "gold" / "posts.jsonl"
    with open(dst, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    c = collections.Counter((r["split"], r["stratum"].split("|")[1]) for r in out)
    print(f"{len(out)} постів -> {dst.relative_to(ROOT)}", dict(sorted(c.items())))


if __name__ == "__main__":
    main()
