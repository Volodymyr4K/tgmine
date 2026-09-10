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
import re
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


def bearings(raid):
    """Курси словами за ніч — заготовки стрілок для оператора.

    «Пролёт БПЛА на северо-восток» — це не гіпотеза зшивання, а те, що
    канал написав. У ніч ідуть лише фіксації з координатою в місці (не
    центр області) і з курсом у тексті: 5.6% точкових подій, приблизно
    16 на добу. Одне місце з одним курсом за ніч згортається в одну стрілку
    з лічильником, як і позначки збиття.
    """
    by = {}
    for e in raid["events"]:
        if e.get("bearing") is None or e.get("scope") != "точка" or not e.get("lat"):
            continue
        if e.get("geo_conf") in ("centroid", "region-snap"):
            continue
        key = (round(e["lat"], 2), round(e["lon"], 2), int(e["bearing"]))
        b = by.setdefault(key, {"la": key[0], "lo": key[1], "deg": key[2], "n": 0,
                                "place": e.get("place") or "", "t": e.get("hhmm", ""),
                                "src": []})
        b["n"] += 1
        if e.get("url"):
            b["src"].append({"u": e["url"], "t": e.get("hhmm", ""),
                             "k": e.get("kind", "")})
    out = []
    for b in by.values():
        name = CITY_UA.get(b["place"]) or uk(b["place"]) if b["place"] else ""
        out.append({"la": b["la"], "lo": b["lo"], "deg": b["deg"], "n": b["n"],
                    "place": name, "t": b["t"], "src": b["src"][:8]})
    out.sort(key=lambda s: (s["t"], -s["n"]))
    return out


AREA_NAME = re.compile(r"rayon|raion|district|округ|район|\bГО\b", re.I)


def sightings(raid):
    """Усі фіксації ночі, згорнуті по місцю — шар свідчень для оператора.

    Навіщо. Досі в ніч ішли лише точки, які алгоритм зшив у маршрути, і
    оператор бачив нашу інтерпретацію замість даних: заміряно, 60–75% місць
    ночі не торкався жоден маршрут-підказка. Тут — кожне місце, де тієї
    ночі щось бачили: скільки повідомлень, коли (усі часи, бо фільтр годин
    у редакторі рахує саме їх), чого саме (фіксація, ППО, збиття), і
    посилання.

    Третина точок стоїть не на селі, а на центрі району («Рыльский район»)
    — 33% на 7 ночах. Крапка там бреше так само, як на центрі області,
    тому такі місця несуть `area`: «район», або «здогад» для збігу за
    населенням без області (conf global). Редактор малює їх порожнім
    кільцем, а не крапкою.
    """
    by = {}
    for e in raid["events"]:
        if e.get("scope") != "точка" or not e.get("lat"):
            continue
        if e.get("kind") not in ("фіксація", "пуск", "ППО", "збиття", "вибух"):
            continue
        if e.get("geo_conf") in ("centroid", "region-snap"):
            continue
        key = (round(e["lat"], 2), round(e["lon"], 2))
        b = by.setdefault(key, {"la": key[0], "lo": key[1], "n": 0,
                                "place": e.get("place") or "",
                                "kinds": collections.Counter(), "ts": [],
                                "degs": collections.Counter(), "src": [],
                                "area": ""})
        b["n"] += 1
        b["kinds"][e["kind"]] += 1
        if e.get("hhmm"):
            b["ts"].append(e["hhmm"])
        if e.get("bearing") is not None:
            b["degs"][int(e["bearing"])] += 1
        if e.get("url"):
            b["src"].append({"u": e["url"], "t": e.get("hhmm", ""),
                             "k": e.get("kind", "")})
        if AREA_NAME.search(e.get("place") or ""):
            b["area"] = "район"
        elif e.get("geo_conf") == "global" and not b["area"]:
            b["area"] = "здогад"
    # Ніч іде через північ: 23:45 стоїть ПЕРЕД 00:10. Рядкове сортування
    # ставило їх навпаки, і картка казала «00:01–23:45» про одну ніч.
    # Доба тут — від 12:00 до 12:00, як скрізь у проєкті.
    def night_key(hhmm):
        h = int(hhmm[:2])
        return (h + 24 if h < 12 else h, hhmm)

    out = []
    for b in by.values():
        name = CITY_UA.get(b["place"]) or uk(b["place"]) if b["place"] else ""
        ts = sorted(b["ts"], key=night_key)
        out.append({"la": b["la"], "lo": b["lo"], "n": b["n"], "place": name,
                    "kinds": dict(b["kinds"]), "ts": ts,
                    "t0": ts[0] if ts else "", "t1": ts[-1] if ts else "",
                    "deg": b["degs"].most_common(1)[0][0] if b["degs"] else None,
                    "area": b["area"], "src": b["src"][:8]})
    out.sort(key=lambda s: -s["n"])
    return out


#: Тривога, що покриває стільки годин ночі, неінформативна: це фронт і ТОТ,
#: де вона висить з полудня до ранку. Заміряно на 8 ночах: ≥12 год у ≥5 з 8
#: ночей мають рівно 11 областей (фронт, чотири ТОТ, Орловська); тил — 0–8.
ALERT_MUTED_HOURS = 12.0
#: Старт тривоги — перша тривога після такої тиші. Відбій перед ним є лише
#: у чверті випадків (56 із 223 проміжків ≥3 год), тож відбій — позначка
#: «після відбою», а не умова. Нагадування «действует тревога» йдуть
#: щогодини й при меншому порозі давали б хибні старти.
ALERT_GAP_HOURS = 3.0
#: Тривога без відбою вважається чинною стільки хвилин — для покриття.
ALERT_HOLD_MIN = 90


def alerts(raid):
    """Хронологія стартів тривог у тилу — «куди пішли далі» для оператора.

    Навіщо. Крапки й підказки відповідають, звідки зайшли; у глибокому тилу
    фіксацій майже нема, а стрілку треба довести. Заміряно на ночі 8 вересня
    2026: у тилу 47 стартів тривоги, у 20 областях з них — жодної фіксації;
    послідовність стартів (Мордовія 00:04 → Волгоградська 00:14 → …
    → Башкортостан 04:37 → Перм 06:39 → ХМАО 09:32) і є маршрут нальоту.

    Що рахується. Область — КОЖНА, названа в тексті тривоги, а не лише перша
    (13% тривог називають 2–6 областей). Старт — перша тривога після
    ALERT_GAP_HOURS тиші; «після відбою» — якщо між нею й попередньою був
    відбій. Область із покриттям ≥ ALERT_MUTED_HOURS за ніч іде в `muted`:
    редактор її не показує, бо там тривога не несе нічого. `silent` — за ніч
    у області не було жодної фіксації в точці: саме там оператор інакше має
    порожнє місце. Якір — той самий полюс недосяжності, що в підписів
    областей, тож чіп стане поруч із назвою.
    """
    from datetime import datetime, timedelta
    sys.path.insert(0, os.path.dirname(HERE))
    from tgmine import extract as E
    import mkreglabels as RL
    root = os.path.dirname(HERE)
    cfg = E.Config.load(os.path.join(root, "configs", "ru-monitor.yaml"))
    regions = json.load(open(os.path.join(root, "regions.json"), encoding="utf-8"))

    def night_key(hhmm):
        h = int(hhmm[:2])
        return (h + 24 if h < 12 else h, hhmm)

    msgs = collections.defaultdict(list)          # регіон -> [(t, kind, url)]
    for e in raid["events"]:
        if e.get("scope") != "область" or e.get("kind") not in ("тривога", "відбій"):
            continue
        t = datetime.fromisoformat(e["t"])
        regs = list(dict.fromkeys(x["value"] for x in E.entities_of(e.get("text", ""), cfg)
                                  if x["type"] == "регіон"))
        for r in regs:
            msgs[r].append((t, e["kind"], e.get("url", ""), e.get("hhmm", "")))
    fixes = collections.Counter(
        e.get("region") for e in raid["events"]
        if e.get("scope") == "точка" and e.get("lat") and e.get("region")
        and e.get("geo_conf") not in ("centroid", "region-snap"))
    onsets, cover, muted, anchors = [], {}, [], {}
    hold, gap = timedelta(minutes=ALERT_HOLD_MIN), timedelta(hours=ALERT_GAP_HOURS)
    for reg, lst in msgs.items():
        lst.sort()
        # покриття: обʼєднання вікон [тривога, відбій або +hold]
        cov, start, last = timedelta(0), None, None
        for t, k, _, _ in lst:
            if k == "тривога":
                if start is None:
                    start = t
                last = t
            elif start is not None:
                cov += max(timedelta(0), min(t, last + hold) - start)
                start = None
        if start is not None:
            cov += (last + hold) - start
        hours = round(cov.total_seconds() / 3600, 1)
        cover[reg] = hours
        if hours >= ALERT_MUTED_HOURS:
            muted.append(reg)
        prev, seen_otboy = None, False
        for t, k, url, hhmm in lst:
            if k == "відбій":
                seen_otboy = prev is not None
                continue
            if prev is None or (t - prev) >= gap:
                onsets.append({"t": hhmm, "reg": reg,
                               "name": (RL.NAMES.get(reg) or (reg, reg))[0],
                               "otboy": bool(seen_otboy and prev is not None),
                               "fix": fixes.get(reg, 0), "silent": not fixes.get(reg),
                               "src": [{"u": url, "t": hhmm, "k": k}] if url else []})
            prev, seen_otboy = t, False
        rings = regions.get(reg)
        if rings:
            pt = RL.anchor(max(rings, key=RL.area))
            if pt:
                anchors[reg] = [round(pt[0], 3), round(pt[1], 3)]
    onsets.sort(key=lambda o: (night_key(o["t"]), o["reg"]))
    return {"onsets": onsets, "muted": sorted(muted), "cover": cover, "anchors": anchors}


def main(src, out=None):
    out = out or os.path.join(os.path.dirname(os.path.abspath(__file__)), "night.js")
    raid = json.load(open(src, encoding="utf-8"))
    rs, meta = RT.build(raid)
    st = strikes(raid)
    br = bearings(raid)
    sg = sightings(raid)
    al = alerts(raid)
    dec = sum(l == "declared" for r in rs for l in r["legs"])
    open(out, "w", encoding="utf-8").write(
        "window.NIGHT=" + json.dumps({"date": raid.get("date"), "routes": rs,
                                      "strikes": st, "bearings": br,
                                      "sightings": sg, "alerts": al},
                                     ensure_ascii=False, separators=(",", ":")) + ";\n")
    rear = [o for o in al["onsets"] if o["reg"] not in al["muted"]]
    print(f"{raid.get('date')}: маршрутів {len(rs)}, ланок {meta['in_routes']}, "
          f"з них заявлено текстом {dec}, збиття/ППО у точці {len(st)}, "
          f"курсів словами {len(br)}, місць із фіксаціями {len(sg)}, "
          f"стартів тривоги в тилу {len(rear)} (німих {sum(o['silent'] for o in rear)})")
    print("->", out)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    main(*sys.argv[1:])
