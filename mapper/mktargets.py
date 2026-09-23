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
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


# Ярус за типом — копія rank_targets.TIER: імпорт кореневого скрипта звідси
# тягнув би tgmine.store і газетир у збірку сайту заради словника.
TIER = {"refinery": 1, "defense_plant": 1, "ammo_depot": 1, "airfield": 1,
        "chemical": 1, "fuel_depot": 2, "naval": 2, "military_base": 3, "range": 3}


def base_box(path=os.path.join(HERE, "basemap.js")):
    """Рамка — та, що в самої підкладки (`BASE.box`), а не власна копія числа.

    Власна копія тут і була: (41, 60.5, 25, 53) лишилась від першої,
    європейської підкладки. 9 вересня 2026 підкладку розширили до 82° сх.,
    а цю рамку ні — і 190 цілей ярусу 1-2 (Орський, Уфимський, Салаватський,
    Пермський НПЗ) карта показувала, а пошук не знаходив. Оператор: «ця зона
    добре відображається, а все інше через раз» (23.09.2026).
    """
    with open(path, encoding="utf-8") as f:
        head = f.read(4096)
    m = re.search(r'"box":\[([^\]]+)\]', head)
    if not m:
        raise SystemExit(f"! у {path} нема BASE.box — рамку цілей нема звідки взяти")
    return tuple(float(x) for x in m.group(1).split(","))


def main(src=None, out=None):
    src = src or os.path.join(ROOT, "targets.json")
    out = out or os.path.join(HERE, "targets.js")
    box = base_box()
    with open(src, encoding="utf-8") as f:
        t = json.load(f)
    items, colors = t["objects"], t["colors"]
    # Ярус дописує rank_targets.py. Щойно дозбираний обʼєкт його ще не має
    # (fetch_targets.py --tiles), і `i["tier"]` валив збірку сайту — тоді ярус
    # за типом, той самий, що дав би rank (рецензія 23.09.2026).
    for i in items:
        i.setdefault("tier", TIER.get(i["cat"], 3))
    keep = [i for i in items if i["tier"] <= 2
            and box[0] <= i["lat"] <= box[1] and box[2] <= i["lon"] <= box[3]]
    keep.sort(key=lambda i: -i.get("hits", 0))
    slim = [{"n": i["name"], "la": round(i["lat"], 3), "lo": round(i["lon"], 3),
             "c": i["cat"], "t": i["tier"], "h": i.get("hits", 0)} for i in keep]
    with open(out, "w", encoding="utf-8") as f:
        f.write("window.TARGETS=" + json.dumps({"colors": colors, "items": slim},
                                               ensure_ascii=False, separators=(",", ":")) + ";\n")
    print(f"цілей у рамці підкладки {box}: {len(slim)}  "
          f"{collections.Counter(i['c'] for i in slim).most_common(5)}")
    print("->", out)


if __name__ == "__main__":
    main(*sys.argv[1:])
