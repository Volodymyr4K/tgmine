#!/usr/bin/env python3
"""Підказки з даних для редактора: маршрути ночі у night.js.

Редактор — інструмент оператора, а не генератор. Але оператор не має
згадувати з голови, де що літало: цей файл кладе на карту напівпрозорий шар
зі шляхами, зшитими з наших повідомлень (tgmine/routes.py). Клік по шляху
переводить його в редагований маршрут, далі оператор веде лінію сам.

Запуск:  python3 mapper/mknight.py raid_2026-08-01.json
         (raid-файл робиться командою `python3 raid.py <дата>`)
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from tgmine import routes as RT
from labels import CITY_UA, uk          # ті самі правила назв, що й у підписах


def strikes(raid):
    """Збиття й робота ППО за ніч — як заготовки обʼєктів для оператора.

    Це НЕ влучання: канали моніторять підліт, а не наслідки. Тому в редактор
    вони йдуть із власним підписом «збиття» і датою, а не як вогники на
    цілях. Оператор вирішує, що з них лишити.

    Події, геокодовані в центр області, не беремо: 30 тисяч кв. км не є
    місцем, і ставити туди позначку означає вигадати точність.
    """
    by = {}
    for e in raid["events"]:
        if e.get("kind") not in ("збиття", "ППО"):
            continue
        if e.get("scope") != "точка" or not e.get("lat"):
            continue
        if e.get("geo_conf") in ("centroid", "region-snap"):
            continue
        key = (round(e["lat"], 2), round(e["lon"], 2))
        b = by.setdefault(key, {"la": key[0], "lo": key[1], "n": 0,
                                "place": e.get("place") or "", "t": e.get("hhmm", ""),
                                "kinds": collections.Counter(), "src": []})
        b["n"] += 1
        b["kinds"][e["kind"]] += 1
        # Джерело позначки: адреса повідомлення, час і канал. Без цього
        # оператор бачив кружок на карті й не мав чим його перевірити, а
        # позначка без джерела — це твердження без підстави.
        if e.get("url"):
            b["src"].append({"u": e["url"], "t": e.get("hhmm", ""),
                             "k": e.get("kind", "")})
    out = []
    for b in by.values():
        name = CITY_UA.get(b["place"]) or uk(b["place"]) if b["place"] else ""
        kind = b["kinds"].most_common(1)[0][0]
        # Більше восьми посилань на одну позначку читати ніхто не буде, а
        # вага файла росте на кожну ніч. Скільки їх насправді — каже `n`.
        out.append({"la": b["la"], "lo": b["lo"], "n": b["n"], "place": name,
                    "kind": kind, "t": b["t"], "src": b["src"][:8]})
    out.sort(key=lambda s: -s["n"])
    return out


def main(src, out=None):
    out = out or os.path.join(os.path.dirname(os.path.abspath(__file__)), "night.js")
    raid = json.load(open(src, encoding="utf-8"))
    rs, meta = RT.build(raid)
    st = strikes(raid)
    dec = sum(l == "declared" for r in rs for l in r["legs"])
    open(out, "w", encoding="utf-8").write(
        "window.NIGHT=" + json.dumps({"date": raid.get("date"), "routes": rs,
                                      "strikes": st},
                                     ensure_ascii=False, separators=(",", ":")) + ";\n")
    print(f"{raid.get('date')}: маршрутів {len(rs)}, ланок {meta['in_routes']}, "
          f"з них заявлено текстом {dec}, збиття/ППО у точці {len(st)}")
    print("->", out)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    main(*sys.argv[1:])
