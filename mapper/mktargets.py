#!/usr/bin/env python3
"""Шар цілей для редактора: ярус 1-2 з нашого рейтингу у targets.js.

Оператор шукає ціль за назвою («Джанкой», «НПЗ») замість того, щоб водити
курсором по карті. Беремо лише перші два яруси: третій — це тло на чотири
тисячі обʼєктів, у пошуку воно заважає, а на карті перетворюється на кашу.

Запуск:  python3 mapper/mktargets.py
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BOX = (41.0, 60.5, 25.0, 53.0)          # той самий театр, що й у підкладки


def main(src=None, out=None):
    src = src or os.path.join(ROOT, "targets.json")
    out = out or os.path.join(HERE, "targets.js")
    t = json.load(open(src, encoding="utf-8"))
    items, colors = t["objects"], t["colors"]
    keep = [i for i in items if i["tier"] <= 2
            and BOX[0] <= i["lat"] <= BOX[1] and BOX[2] <= i["lon"] <= BOX[3]]
    keep.sort(key=lambda i: -i.get("hits", 0))
    slim = [{"n": i["name"], "la": round(i["lat"], 3), "lo": round(i["lon"], 3),
             "c": i["cat"], "t": i["tier"], "h": i.get("hits", 0)} for i in keep]
    open(out, "w", encoding="utf-8").write(
        "window.TARGETS=" + json.dumps({"colors": colors, "items": slim},
                                       ensure_ascii=False, separators=(",", ":")) + ";\n")
    print(f"цілей у театрі: {len(slim)}  "
          f"{collections.Counter(i['c'] for i in slim).most_common(5)}")
    print("->", out)


if __name__ == "__main__":
    main(*sys.argv[1:])
