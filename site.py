#!/usr/bin/env python3
"""Збирає статичний сайт зі сховища: зведення + сторінка на кожну ніч.

Усе статичне — жодного бекенду. Хоститься безкоштовно на GitHub Pages,
оновлюється по cron через GitHub Actions.

  python3 site.py               # усі дні зі сховища
  python3 site.py --days 14     # лише останні 14
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import hashlib
import importlib.util
import io
import re
import html
import json
import multiprocessing
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from tgmine import nightprint as NP
from tgmine import store as ST
from tgmine.labels import region_label

MSK = timezone(timedelta(hours=3))
OUT = Path("site")

CSS = """
:root{--bg:#060910;--panel:#0c1119;--line:#18212c;--fg:#e6eef7;--dim:#68798c;
      --cyan:#38d4dd;--red:#ff4d63;--amber:#ffb01f;--violet:#a78bfa}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
     font:14px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace}
.wrap{max-width:1080px;margin:0 auto;padding:28px 20px 80px}
h1{font-size:19px;letter-spacing:.1em;text-transform:uppercase;margin:0 0 4px}
h2{font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:var(--dim);
   margin:34px 0 12px;border-top:1px solid var(--line);padding-top:14px}
.lead{color:var(--dim);font-size:12px;margin-bottom:22px;line-height:1.7}
.kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:9px}
.k{background:var(--panel);border:1px solid var(--line);border-radius:7px;padding:12px}
.k b{display:block;font-size:23px;font-variant-numeric:tabular-nums}
.k span{font-size:9.5px;color:var(--dim);letter-spacing:.05em;text-transform:uppercase}
table{width:100%;border-collapse:collapse;font-size:12px}
th{text-align:left;color:var(--dim);font-weight:400;font-size:10px;letter-spacing:.08em;
   text-transform:uppercase;padding:7px 8px;border-bottom:1px solid var(--line)}
td{padding:7px 8px;border-bottom:1px solid #121a24}
tr:hover td{background:#0b1119}
td.n{text-align:right;font-variant-numeric:tabular-nums}
a{color:var(--cyan);text-decoration:none} a:hover{text-decoration:underline}
.bar{display:inline-block;height:9px;background:var(--cyan);border-radius:2px;
     vertical-align:middle;opacity:.75}
.bar.r{background:var(--red)}
.big{font-size:12px}
/* Широкі таблиці (денна — сім колонок) розтягували ВСЮ сторінку: на 731px
   документ мав 774px і зʼявлявся горизонтальний скрол усього макета.
   Скролитись має таблиця, а не сторінка. */
.tw{overflow-x:auto}
.tw table{min-width:max-content}
.note{font-size:10.5px;color:#4e5f70;line-height:1.8;margin-top:26px;
      border-top:1px solid var(--line);padding-top:14px}
.tag{display:inline-block;padding:1px 6px;border-radius:3px;font-size:10px;
     background:#141e29;color:#8fa3b6;margin-right:4px}
nav{position:sticky;top:0;z-index:50;display:flex;align-items:center;gap:4px;
    background:rgba(6,9,16,.93);backdrop-filter:blur(8px);
    border-bottom:1px solid var(--line);padding:11px 20px;flex-wrap:wrap}
nav .brand{font-size:11px;letter-spacing:.16em;color:var(--fg);margin-right:14px;
           font-weight:600}
nav a{color:var(--dim);font-size:11.5px;padding:5px 10px;border-radius:5px;
      border:1px solid transparent}
nav a:hover{color:var(--fg);background:#101a24;text-decoration:none}
nav a.on{color:var(--cyan);border-color:#1d3b45;background:#0b1a20}
nav .sp{flex:1}
nav .ghost{color:#5d6f82;font-size:10.5px}
.pager{display:flex;justify-content:space-between;gap:10px;margin:22px 0 0}
.pager a{font-size:11.5px;padding:7px 12px;border:1px solid var(--line);
         border-radius:6px;background:var(--panel)}
.pager a:hover{border-color:#2b3f52;text-decoration:none}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px;margin:14px 0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px}
.card h3{margin:0 0 4px;font-size:12px;letter-spacing:.06em;color:var(--fg)}
.card p{margin:0;font-size:10.5px;color:var(--dim);line-height:1.6}
.card:hover{border-color:#2b3f52}
"""


def nav(active="", up="", extra=""):
    """Наскрізна шапка. Без неї сторінки були островами: про існування
    денних звітів і програвача можна було дізнатись лише випадково."""
    def a(href, label, key):
        cls = ' class="on"' if key == active else ""
        return f'<a href="{up}{href}"{cls}>{label}</a>'
    return (f'<nav><span class=brand>УДАРИ ПО РФ</span>'
            f'{a("index.html","Зведення","index")}'
            f'{a("live.html","Що зараз","live")}'
            f'{a("nights.html","Доби","nights")}'
            f'<span class=sp></span>{extra}</nav>')


def esc(x):
    return html.escape(str(x or ""))




_TGT_BY_TID = None


def targets_by_tid():
    """tid -> обʼєкт цілі. Ліниво, один раз на процес."""
    global _TGT_BY_TID
    if _TGT_BY_TID is None:
        try:
            objs = json.load(open("targets.json", encoding="utf-8"))["objects"]
        except (FileNotFoundError, KeyError):
            objs = []
        _TGT_BY_TID = {ST.target_id(o): o for o in objs}
    return _TGT_BY_TID


#: Дзеркала схлопуються в один голос: kupolrussia переписує lpr1_treugolnik
#: (73% текстів збігаються, медіанний лаг 15 с), тож це не два свідчення.
VOICE = {"lpr1_treugolnik": "lpr1+kupol", "kupolrussia": "lpr1+kupol"}
#: Від якої частки вважаємо, що регіон висвітлює по суті один канал.
SOLO_SHARE = 0.90


def voice_coverage(st, threshold=SOLO_SHARE):
    """Скільки регіонів висвітлює по суті один голос.

    Проєкт слухає три канали, але незалежних голосів два, і покривають вони
    РІЗНЕ. Подій, підтверджених другим голосом (те саме місце й тип у вікні
    60 хв), у липні 2026 було близько трьох відсотків; тепер це число рахує
    `confirmed_share` на кожній збірці.

    Спершу хотів ставити позначку «одне джерело» біля регіонів у таблиці. Не
    вийшло: при порозі 90% таких регіонів 35 із 39, при 95% — 23. Значок на
    майже кожному рядку нічого не повідомляє, а поріг створює артефакт (Крим
    із 94% лишався б «немаркованим», хоч фактично має одне джерело). Тому
    віддаємо число для тексту, а не прапорець на рядок.

    Рахуємо по ТОЧКОВИХ спостереженнях — саме їх показує таблиця регіонів.

    Повертає (скільки_регіонів_моно, усього_регіонів, частка_подій_у_моно).
    """
    by = collections.defaultdict(collections.Counter)
    for e in full_window(st):
        if (e.get("noise") or e.get("dup_of") or not e.get("region")
                or e.get("scope") != "точка"):
            continue
        by[e["region"]][VOICE.get(e["channel"], e["channel"])] += 1
    if not by:
        return (0, 0, 0.0)
    mono = solo_events = total_events = 0
    for voices in by.values():
        total = sum(voices.values())
        total_events += total
        if voices.most_common(1)[0][1] / total >= threshold:
            mono += 1
            solo_events += total
    return (mono, len(by), solo_events / total_events if total_events else 0.0)


def count_share(st):
    """Частка згадок БпЛА, де канал назвав число. Йде в прозу як «нижня межа».

    Стояло літералом 3.2% (виміряно в липні 2026). Після розширення витягу
    числа (`store.drones_of`) стало 4.5%, а сторінка далі показувала старе —
    тому число рахується на кожній збірці. Лише унікальні події, без реклами.
    """
    rx = re.compile(r"БПЛА|бпла|дрон", re.I)
    men = num = 0
    for e in full_window(st):
        if e.get("noise") or e.get("dup_of") or not rx.search(e.get("text") or ""):
            continue
        men += 1
        num += bool(e.get("drones"))
    return num / men if men else 0.0


def confirmed_share(st, window_s=3600):
    """Частка точкових спостережень, які підтвердив ІНШИЙ голос: те саме
    місце й тип у вікні години. Дзеркала — один голос (див. VOICE).

    Стояло літералом 3.1% (липень 2026). Після добору locatorru — третього
    незалежного голосу — стало 10.4%; сторінка не помітила. Тому рахується
    на збірці. Це і є число «скільки тут другої думки», і воно має рухатись
    разом із набором каналів, а не з чиєюсь памʼяттю.
    """
    by = collections.defaultdict(list)
    for e in full_window(st):
        if (e.get("noise") or e.get("dup_of") or e.get("scope") != "точка"
                or not e.get("place")):
            continue
        by[(e["place"], e["kind"])].append(
            (datetime.fromisoformat(e["t"]), VOICE.get(e["channel"], e["channel"])))
    total = confirmed = 0
    for rows in by.values():
        rows.sort()
        for i, (t, v) in enumerate(rows):
            total += 1
            # сусіди за часом — сортовано, тож досить дивитись у вікно навколо
            for t2, v2 in rows[max(0, i - 40):i + 40]:
                if v2 != v and abs((t2 - t).total_seconds()) <= window_s:
                    confirmed += 1
                    break
    return confirmed / total if total else 0.0


def target_label(name, tid, dup_names):
    """Підпис цілі; тезкам додає координати.

    Назви генеруються як «категорія + найближчий НП», тому чотири різні склади
    БК під Севастополем звуться однаково. Відколи жар рахується по обʼєкту, а не
    по імені, вони дають РІЗНІ числа — два однакові підписи поруч виглядали б
    як помилка. Координати — найкоротше, що їх справді розрізняє.

    Чотири знаки не для краси: `fetch_targets` робить дедуп по `round(lat, 4)`,
    тобто це і є роздільність тотожності в цьому наборі. При двох знаках 13 з 44
    пар-тезок серед цінних категорій лишались нерозрізненними, при трьох — 5.
    """
    if name not in dup_names:
        return esc(name)
    o = targets_by_tid().get(tid)
    if not o or o.get("lat") is None:
        return esc(name)
    return (f'{esc(name)} <span style="color:var(--dim);font-size:11px">'
            f'· {o["lat"]:.4f}, {o["lon"]:.4f}</span>')


def day_window(date: str):
    """Оперативна доба: 12:00 МСК — 12:00 наступного дня.

    Було 16:00 → 12:00, і проміжок 12:00–16:00 не входив у ЖОДНЕ вікно —
    з аналізу тихо випадало 14.8% подій, причому найактивніший денний час.
    Опівдні межа безпечна: нічні нальоти (22:00–05:00) не розриваються,
    а вікна стикуються без дірок і накладань.
    """
    d0 = datetime.fromisoformat(date).replace(tzinfo=MSK, hour=12)
    return d0, d0 + timedelta(days=1)


# Одне й те саме вікно за збірку питають по кілька разів, і кожен раз — це
# перечитування й розбір json з диска. Заміряно профайлером на 143 добах:
# 1 722 326 розборів json на ~250 тис. подій, тобто кожна подія розбиралась
# усьоме, і це 14.8 с із 17.3 с усієї збірки. Джерела повторів рівно два:
# три довідкові числа для прози (`voice_coverage`, `count_share`,
# `confirmed_share`) роблять ТРИ однакові проходи по всьому архіву, а денні
# звіти двічі йдуть по всіх добах — спершу за зведеннями, потім за
# сторінками.
#
# Памʼятка тримає розібрані події за ключем вікна. Це безпечно рівно тому, що
# в site.py події лише ЧИТАЮТЬ: `summarize`, `clean`, `day_page` нічого в них
# не пишуть. `raid.py`, який дописує подіям `hhmm` і перекладає `region`,
# з 22.09.2026 працює в цьому ж процесі (`_night_job`), але читає події
# своїм `ST.Store().window` з диска, а не через цю памʼятку, тож спільних
# обʼєктів із нею нема. Хто додасть у site.py запис у подію — має спершу прибрати памʼятку
# або віддавати копії.
#
# Ціна — памʼять: увесь архів лишається розібраним у процесі, ~250 МБ на 143
# добах. На ранері 7 ГБ, локально теж не проблема; але якщо архів виросте в
# рази, дешевше буде злити два денні проходи в один, ніж памʼять.
_WIN = {}
_FULL = None


def win(st, lo, hi):
    k = (lo.isoformat(), hi.isoformat())
    if k not in _WIN:
        _WIN[k] = st.window(lo, hi)
    return _WIN[k]


def full_window(st):
    """Увесь архів одним проходом — на всі три довідкові числа для прози."""
    global _FULL
    if _FULL is None:
        days = st.dates()
        if not days:
            return []
        lo = datetime.fromisoformat(days[0]).replace(tzinfo=MSK)
        hi = datetime.fromisoformat(days[-1]).replace(tzinfo=MSK) + timedelta(days=2)
        _FULL = st.window(lo, hi)
    return _FULL


def forget_full():
    """Відпустити архів: далі йдуть подобові вікна, і тримати обидва — це
    зайвих ~600 МБ на ранері, де поруч ще й підпроцеси карт нальотів."""
    global _FULL
    _FULL = None


def clean(events):
    """Без дублів і без не-бойового контенту (збори, реклама, вербування)."""
    return [e for e in events if not e.get("dup_of") and not e.get("noise")]


def summarize(events):
    uniq = clean(events)
    pts = [e for e in uniq if e["scope"] == "точка"]
    kinds = collections.Counter(e["kind"] for e in uniq)
    regions = collections.Counter(e["region"] for e in pts if e.get("region"))
    depths = sorted(e["depth"] for e in pts if e.get("depth"))
    return {
        "msgs": len(uniq), "points": len(pts),
        # профіль заявлених апаратів рахує store.declared — одна реалізація
        # на весь проєкт. Раніше та сама сума стояла тут і в store.stat()
        # окремими рядками, і розʼїхатись вони могли будь-якої правки.
        **ST.declared(uniq),
        "pvo": kinds["ППО"], "kills": kinds["збиття"], "booms": kinds["вибух"],
        "alerts": len({e["region"] for e in uniq
                       if e["scope"] == "область" and e.get("region")}),
        "regions": regions,
        "deep": depths[int(len(depths) * .9)] if depths else 0,
        "max_deep": depths[-1] if depths else 0,
    }


def bar(v, mx, w=150, cls=""):
    px = 0 if not mx else max(1, round(v / mx * w))
    return f'<span class="bar {cls}" style="width:{px}px"></span>'


def hour_hist(events, lo, hi, w=520, h=52):
    """Погодинна гістограма ночі — SVG, без бібліотек."""
    pts = [e for e in clean(events) if e["scope"] == "точка"]
    bins = collections.Counter(datetime.fromisoformat(e["t"]).strftime("%H") for e in pts)
    hours = []
    t = lo
    while t < hi:
        hours.append(t.strftime("%H"))
        t += timedelta(hours=1)
    mx = max(bins.values()) if bins else 1
    bw = w / max(1, len(hours))
    bars, labels = [], []
    for i, hh in enumerate(hours):
        v = bins.get(hh, 0)
        bh = v / mx * (h - 14)
        night = int(hh) >= 22 or int(hh) < 6
        bars.append(f'<rect x="{i*bw:.1f}" y="{h-14-bh:.1f}" width="{bw*.78:.1f}" '
                    f'height="{bh:.1f}" fill="{"#38d4dd" if not night else "#2b8f96"}"/>')
        if i % 3 == 0:
            labels.append(f'<text x="{i*bw+bw*.4:.1f}" y="{h-3}" fill="#5d6f82" '
                          f'font-size="8" text-anchor="middle">{hh}</text>')
    return (f'<svg width="{w}" height="{h}" style="max-width:100%">'
            + "".join(bars) + "".join(labels) + "</svg>")


def day_page(date, ev, s, prev_stats, have_raid, prev_date=None, next_date=None,
             count_pct=None):
    lo, hi = day_window(date)
    # частка згадок із числом — рахує main() раз на збірку (count_share)
    cp = f"{count_pct:.1%}" if count_pct is not None else "кількох відсотків"
    uniq = clean(ev)
    pts = [e for e in uniq if e["scope"] == "точка"]

    # порівняння з нормою: медіана попередніх ночей
    def cmp(v, key):
        base = sorted(x[key] for x in prev_stats) if prev_stats else []
        # Норма — це медіана попередніх діб, максимум 7. На перших добах набору
        # їх 1-2, і «+140% до норми» проти однієї доби — не порівняння, а шум.
        # Нижче трьох не показуємо взагалі, до семи — пишемо, на скількох рахано.
        if len(base) < 3:
            return ""
        med = base[len(base) // 2]
        if not med:
            return ""
        d = (v - med) / med * 100
        col = "#ff8a9b" if d > 25 else ("#7ddb9a" if d < -25 else "#68798c")
        n = "" if len(base) >= 7 else f" з {len(base)} діб"
        return (f'<span style="color:{col};font-size:10px"> '
                f'{"+" if d >= 0 else ""}{d:.0f}% до норми{n}</span>')

    places = collections.Counter(e["place"] for e in pts if e.get("place"))
    top_pl = "\n".join(
        f'<tr><td>{esc(region_label(k))}</td><td class=n>{v}</td></tr>'
        for k, v in places.most_common(12))
    # 90-й перцентиль, а не максимум: одна помилка геокодування (тезка за
    # тисячу кілометрів) інакше стає «рекордом глибини» для цілого регіону
    def p90(reg):
        d = sorted(e["depth"] for e in pts if e.get("region") == reg and e.get("depth"))
        return d[int(len(d) * .9)] if d else 0
    regs = "\n".join(
        f'<tr><td>{esc(region_label(k))}</td><td class=n>{v}</td>'
        f'<td class=n>{p90(k)}</td></tr>'
        for k, v in s["regions"].most_common(14))

    big = sorted([e for e in pts if e.get("drones")],
                 key=lambda e: -e["drones"])[:8]
    bigrows = "\n".join(
        f'<tr><td>{datetime.fromisoformat(e["t"]).strftime("%H:%M")}</td>'
        f'<td class=n>{e["drones"]}</td><td>{esc(region_label(e["place"]))}</td>'
        f'<td class=big>{esc(e["text"][:90])}</td>'
        f'<td><a href="{esc(e["url"])}" target=_blank>↗</a></td></tr>' for e in big)

    notable = [e for e in pts if e["kind"] in ("збиття", "вибух")][:10]
    notrows = "\n".join(
        f'<tr><td>{datetime.fromisoformat(e["t"]).strftime("%H:%M")}</td>'
        f'<td><span class=tag>{esc(e["kind"])}</span></td><td>{esc(region_label(e["place"]))}</td>'
        f'<td class=big>{esc(e["text"][:90])}</td>'
        f'<td><a href="{esc(e["url"])}" target=_blank>↗</a></td></tr>' for e in notable)

    # Цілі, поблизу яких фіксували активність. Пріоритет цінним категоріям,
    # «військова зона»/полігон не показуємо — їх тисячі, це шум.
    VALUABLE = {"refinery", "airfield", "ammo_depot", "defense_plant",
                "chemical", "fuel_depot", "naval"}
    T_UA = {"refinery": "НПЗ", "airfield": "аеродром", "ammo_depot": "склад БК",
            "defense_plant": "оборонний завод", "chemical": "хімія",
            "fuel_depot": "нафтобаза", "naval": "ВМБ"}
    # Ключ — tid, не назва. За назвою Counter ЗЛИВАВ різні обʼєкти-тезки в один
    # рядок: 27 з 31 доби мали в топ-12 щонайменше одну таку назву.
    # `or n["name"]` — сховище, зібране конвеєром < v9, tid не має; тоді
    # лишається стара (неточна) поведінка замість порожньої таблиці.
    near_hits = collections.Counter()
    near_meta = {}
    for e in pts:
        n = e.get("near")
        if n and n["cat"] in VALUABLE and n["name"]:
            k = n.get("tid") or n["name"]
            near_hits[k] += 1
            near_meta[k] = (n["name"], n["cat"])
    top = near_hits.most_common(12)
    dup_near = {nm for nm, c in collections.Counter(
        near_meta[k][0] for k, _ in top).items() if c > 1}
    nearrows = "\n".join(
        f'<tr><td>{target_label(near_meta[k][0], k, dup_near)}</td>'
        f'<td><span class=tag>{esc(T_UA.get(near_meta[k][1], near_meta[k][1]))}</span></td>'
        f'<td class=n>{v}</td></tr>'
        for k, v in top)

    # для «найглибшої» беремо не абсолютний максимум, а найглибшу з тих, що
    # підтверджені хоча б двома повідомленнями — інакше показуємо помилку.
    # Відкат на центр області (centroid/region-snap) — не фіксація в місці,
    # а «десь у цій області»: такий рядок і глибину бреше, і замість назви
    # друкував внутрішній ключ («ТОТ_Донецьк · 68 км»), спіймано тестом
    # 9 вересня 2026.
    located = [e for e in pts if e.get("depth")
               and e.get("geo_conf") not in ST.REGIONAL_FALLBACK]
    place_hits = collections.Counter(e["place"] for e in located)
    conf = [e for e in located if place_hits[e["place"]] >= 2]
    deepest = max(conf or located, key=lambda e: e.get("depth") or 0, default=None)
    link = (f'<div class=cards><a class=card href="../raids/{date}.html">'
            f'<h3>→ Карта доби</h3><p>Програвач: рух у часі, треки, '
            f'області під тривогою, клік по точці — джерело.</p></a></div>'
            if have_raid else "")

    pager = (
        f'<div class=pager>'
        f'{f"<a href={prev_date}.html>← {prev_date}</a>" if prev_date else "<span></span>"}'
        f'{f"<a href={next_date}.html>{next_date} →</a>" if next_date else "<span></span>"}'
        f'</div>')
    body = f"""{nav("nights", up="../",
                    extra=f'<a href="../raids/{date}.html" class=ghost>карта цієї доби →</a>'
                          if have_raid else "")}
<div class=wrap>
<h1>Доба {date}</h1>
<div class=lead>{lo:%d.%m %H:%M} — {hi:%d.%m %H:%M} МСК (оперативна доба) ·
за повідомленнями моніторингових каналів</div>
<div class=kpi>
  <div class=k><b style="color:var(--cyan)">{s['points']}</b><span>спостережень</span>{cmp(s['points'],'points')}</div>
  <div class=k><b>{s['largest'] or '—'}</b><span>найбільша група</span>{cmp(s['largest'],'largest')}</div>
  <div class=k><b>{s['count_places'] or '—'}</b><span>місць із числом</span></div>
  <div class=k><b style="color:var(--red)">{s['pvo']}</b><span>робота ППО</span></div>
  <div class=k><b>{s['kills']}</b><span>збиття</span></div>
  <div class=k><b style="color:var(--amber)">{s['alerts']}</b><span>областей під тривогою</span></div>
  <div class=k><b>{s['deep']}</b><span>глибина 90%, км</span></div>
</div>
{link}
<h2>Хід доби</h2>
{hour_hist(ev, lo, hi)}
<div style="color:#5d6f82;font-size:10px">спостережень за годину (МСК), від 12:00 до 12:00; темніше — нічні години</div>

<h2>Регіони</h2>
<div class=tw><table><tr><th>регіон</th><th class=n>спостережень</th><th class=n>глибина 90%, км</th></tr>
{regs}</table></div>

<h2>Найбільші групи</h2>
{'<div class=tw><table><tr><th>час</th><th class=n>апаратів</th><th>місце</th><th>повідомлення</th><th></th></tr>'+bigrows+'</table></div>' if big else '<div class=lead>каналі не назвали жодного числа за цю ніч</div>'}

<h2>Збиття та вибухи</h2>
{'<div class=tw><table><tr><th>час</th><th>тип</th><th>місце</th><th>повідомлення</th><th></th></tr>'+notrows+'</table></div>' if notable else '<div class=lead>не повідомлялось</div>'}

<h2>Активність поблизу відомих цілей</h2>
{'<div class=tw><table><tr><th>ціль</th><th>тип</th><th class=n>спостережень поруч</th></tr>'+nearrows+'</table></div>' if nearrows else '<div class=lead>цієї доби не зафіксовано поблизу відомих цілей</div>'}
<div class=lead style="margin-top:6px">Прив'язка орієнтовна: спостереження — центр
НП, а не координата удару. Показано лише цінні цілі (НПЗ, аеродроми, склади БК,
заводи), військові зони й полігони пропущено.</div>

<h2>Найглибша фіксація</h2>
<div class=lead>{esc(region_label(deepest['place'])) if deepest else '—'}
{f"· {deepest['depth']} км від підконтрольної України · {datetime.fromisoformat(deepest['t']).strftime('%H:%M')}" if deepest else ''}</div>

<h2>Найчастіші точки</h2>
<div class=tw><table><tr><th>місце</th><th class=n>повідомлень</th></tr>{top_pl}</table></div>

<div class=note>
{pager}
<div class=note>
«Спостереження» — повідомлення про побачений чи почутий апарат, не підтверджений
факт. «Найбільша група» — найбільше число, яке назвали канали за добу; число
вони вказують рідко ({cp} згадок), тому це нижня межа. Суму чисел за добу тут
свідомо не показано: одна група летить через кілька районів і кожен дає власне
повідомлення, тож сума рахує її по кілька разів. Збиття і вибухи систематично занижені: канали
моніторять підліт, а не наслідки. Порівняння «до норми» — з медіаною попередніх
діб у сховищі.
</div>
</div>"""
    return (f"<!doctype html><html lang=uk><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>Доба {date}</title><style>{CSS}</style></head><body>{body}</body></html>")


def live_page():
    return """<!doctype html><html lang=uk><head><meta charset=utf-8>
<meta name=viewport content='width=device-width,initial-scale=1'>
<title>Зараз · моніторинг</title><style>__CSS__
.pulse{display:inline-block;width:8px;height:8px;border-radius:50%;background:#4ade80;
       margin-right:7px;animation:p 2s infinite}
@keyframes p{0%,100%{opacity:1}50%{opacity:.25}}
.stale .pulse{background:#ff8a1f;animation:none}
.reg{display:inline-block;padding:3px 9px;margin:0 5px 5px 0;border-radius:4px;
     background:#2a1116;border:1px solid #58202b;color:#ff9db0;font-size:11px}
.feed div{padding:6px 0;border-bottom:1px solid #121a24;font-size:12px}
.feed time{color:var(--cyan);margin-right:8px}
</style></head><body>__NAV__
<div class=wrap>
<h1>Що зараз</h1>
<div class=lead id=status><span class=pulse></span>завантаження…</div>
<div class=kpi id=kpi></div>
<h2>Області під тривогою</h2><div id=alerts></div>
<h2>Останні спостереження</h2><div class=feed id=feed></div>
<div class=note id=note></div>
</div>
<script>
// Сторінка статична, дані оновлює cron. Тому опитуємо файл, а не тримаємо
// зʼєднання — і чесно показуємо, наскільки дані застаріли.

// live.json містить сирий текст постів. Усе, що йде в innerHTML, екранується:
// решта сторінок рендериться на сервері через html.escape(), а тут розмітку
// збирає браузер — і без цього пост із <img onerror> виконався б у відвідувача.
// Лапки теж, бо url підставляється в href="${...}".
function esc(t){return String(t==null?'':t).replace(/[&<>"']/g,
  ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));}

async function tick(){
  try{
    const r = await fetch('live.json?_='+Date.now());
    const d = await r.json();
    const age = (Date.now()-new Date(d.generated).getTime())/60000;
    // Поріг привʼязаний до крону (година) з подвійним запасом: GitHub регулярно
    // запізнюється на десятки хвилин, і при 45 хв позначка стояла б майже
    // завжди — тобто не значила б нічого.
    const stale = age>120;
    document.body.classList.toggle('stale',stale);
    document.getElementById('status').innerHTML =
      `<span class=pulse></span>дані станом на ${new Date(d.generated)
        .toLocaleString('uk-UA',{hour:'2-digit',minute:'2-digit',day:'2-digit',month:'2-digit'})}`+
      ` · ${age<1?'щойно':Math.round(age)+' хв тому'}`+
      (stale?' · <b style="color:#ff8a1f">оновлення затрималось</b>':'');
    document.getElementById('kpi').innerHTML = `
      <div class=k><b style="color:var(--cyan)">${d.points_6h}</b><span>спостережень за 6 год</span></div>
      <div class=k><b>${d.drones_6h||'—'}</b><span>найбільша група</span></div>
      <div class=k><b style="color:var(--red)">${d.pvo_6h}</b><span>робота ППО</span></div>
      <div class=k><b style="color:var(--amber)">${d.alerts.length}</b><span>областей під тривогою</span></div>`;
    document.getElementById('alerts').innerHTML = d.alerts.length
      ? d.alerts.map(a=>`<span class=reg>${esc(a)}</span>`).join('')
      : '<div class=lead>жодної активної тривоги у даних</div>';
    document.getElementById('feed').innerHTML = d.recent.map(e=>
      `<div><time>${esc(e.hhmm)}</time><span class=tag>${esc(e.kind)}</span> ${esc(e.place)}
       <span style="color:var(--dim)"> ${esc((e.text||'').slice(0,110))}</span>
       <a href="${esc(e.url)}" target=_blank>↗</a></div>`).join('');
    document.getElementById('note').textContent =
      'Сторінка оновлюється автоматично раз на хвилину, але самі дані оновлює '+
      'збирач за розкладом. Стан «під тривогою» вираховується з останнього '+
      'повідомлення по кожній області: тривога без наступного відбою вважається чинною. '+
      'Канали оголошують відбій не завжди, тому частина тривог тут може «висіти» довше за реальну.';
  }catch(e){
    document.getElementById('status').innerHTML='<span class=pulse></span>дані недоступні';
  }
}
tick(); setInterval(tick,60000);
</script></body></html>""".replace("__CSS__", CSS).replace("__NAV__", nav("live"))


# Редактор карт їде на сайт разом із рештою: інакше показати його комусь
# можна тільки зі свого ноутбука через localhost. Тека самодостатня —
# підкладка, шрифт, цілі, підписи й кеш плиток лежать поруч. Плитки важать
# 16 МБ, але хостинг вантажить лише змінені файли, тож це разова заливка.
MAPPER_FILES = ("editor.html", "basemap.js", "targets.js", "labels.js",
                "font.css", "night.js", "README.md")


_SCRIPTS: dict = {}


def _script(path):
    """Скрипт збірки ночі як модуль (raid.py, makeraid.py, mapper/mknight.py)."""
    if path not in _SCRIPTS:
        d = str(Path(path).resolve().parent)
        if d not in sys.path:
            sys.path.insert(0, d)
        name = "tgmine_night_" + Path(path).stem
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        _SCRIPTS[path] = mod
    return _SCRIPTS[path]


def _night_job(job):
    """Одна ніч: raid.py -> makeraid.py -> mapper/mknight.py, у цьому процесі.

    Ті самі кроки й аргументи, що й раніше (`NP.NIGHT_ARGV`), лише без
    окремого процесу на кожен: до 22.09.2026 кожна ніч тричі запускала
    Python і двічі розбирала довідники (газетир 7.5 с у CI, якорі областей
    ~2 с) — повна перебудова архіву йшла 23.5 хв.
    """
    d, want_page, want_night, night, fp = job
    argv = [[x.format(d=d, night=night) for x in step] for step in NP.NIGHT_ARGV]
    res = {"d": d, "fp": fp, "page": want_page, "err": None, "night_err": None}
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            _script(argv[0][0]).main(*argv[0][1:])
            if want_page:
                _script(argv[1][0]).main(*argv[1][1:])
                shutil.move(f"raid_{d}.html", OUT / "raids" / f"{d}.html")
            if want_night:
                try:
                    _script(argv[2][0]).main(*argv[2][1:])
                except Exception as e:
                    res["night_err"] = repr(e)
        Path(f"raid_{d}.json").unlink(missing_ok=True)
    except Exception as e:
        res["err"] = repr(e)
    return res


def run_nights(jobs):
    """Ночі — паралельно на всіх ядрах (fork: довідники, завантажені тут
    один раз, діляться з робітниками). Результати — у порядку `jobs`.
    `NIGHT_JOBS=1` — послідовно, для налагодження."""
    if not jobs:
        return []
    from tgmine import geocode as GC
    GC.Gazetteer.load("gazetteer/RU.txt", "gazetteer/UA.txt")
    mk = _script(NP.NIGHT_ARGV[2][0])
    for path in mk.UN.GAZ:
        if os.path.exists(path):
            mk.UN._memo(("offs", path), lambda p=path: mk.UN._offsets(p))
    for step in NP.NIGHT_ARGV[:2]:
        _script(step[0])
    n = int(os.environ.get("NIGHT_JOBS") or min(len(jobs), os.cpu_count() or 1, 8))
    if n <= 1 or "fork" not in multiprocessing.get_all_start_methods():
        return [_night_job(j) for j in jobs]
    with multiprocessing.get_context("fork").Pool(n) as pool:
        return list(pool.imap(_night_job, jobs))


def night_index(nights: Path):
    """Список ночей для випадайки в редакторі.

    Читаю саме файли на диску, а не рядки звіту: у кеші хостингу лежить те,
    що справді зібралось, і список має збігатися з ним, інакше оператор
    вибирає дату, якої нема.
    """
    out = []
    for f in sorted(nights.glob("*.js")):
        try:
            t = f.read_text(encoding="utf-8")
            d = json.loads(t[t.index("=") + 1:].rstrip().rstrip(";"))
        except Exception:
            continue
        out.append({"date": d.get("date") or f.stem,
                    "routes": len(d.get("routes") or []),
                    "strikes": len(d.get("strikes") or []),
                    "bearings": len(d.get("bearings") or []),
                    "sightings": len(d.get("sightings") or []),
                    "alerts": sum(1 for o in (d.get("alerts") or {}).get("onsets", [])
                                  if o.get("reg") not in ((d.get("alerts") or {}).get("muted") or []))})
    out.sort(key=lambda r: r["date"], reverse=True)
    (nights / "index.json").write_text(
        json.dumps(out, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8")
    print(f"-> {nights}/index.json  ({len(out)} ночей)")


def stamp_assets(dst: Path):
    """Дописати версію до посилань на власні файли редактора.

    Вони підключені як `labels.js` і `font.css` — без версії, — і браузер
    тримав їх у кеші після кожного оновлення: оператор відкривав карту й
    бачив ті самі підписи, які щойно прибрали, а потім питав, чи взагалі
    задеплоїлось. Версія — короткий хеш ВМІСТУ, тож адреса міняється рівно
    тоді, коли міняється файл, і не міняється просто так.

    Робиться на збірці, а не в самому editor.html: інакше номер довелося б
    правити руками щоразу, а це саме та дисципліна, яка одного разу
    забувається.
    """
    html = dst / "editor.html"
    if not html.exists():
        return
    src = html.read_text(encoding="utf-8")
    for f in sorted(dst.iterdir()):
        if f.name == "editor.html" or not f.is_file():
            continue
        if f.suffix not in (".js", ".css"):
            continue
        v = hashlib.md5(f.read_bytes()).hexdigest()[:8]
        # і чисте посилання, і вже проставлену вручну версію (`?v=4`)
        src = re.sub(rf'(["\'])({re.escape(f.name)})(\?v=[^"\']*)?\1',
                     rf'\g<1>\g<2>?v={v}\g<1>', src)
    html.write_text(src, encoding="utf-8")


def copy_mapper():
    src = Path(__file__).resolve().parent / "mapper"
    if not (src / "editor.html").exists():
        print("! mapper/editor.html нема — редактор на сайт не поїде")
        return
    dst = OUT / "mapper"
    dst.mkdir(parents=True, exist_ok=True)
    n = 0
    for name in MAPPER_FILES:
        f = src / name
        if f.exists():
            shutil.copyfile(f, dst / name)
            n += 1
    stamp_assets(dst)
    # HTML не кешується взагалі, решта — назавжди: адреса скриптів уже несе
    # хеш вмісту, тож змінений файл приходить під новою адресою, а незмінений
    # береться з кешу. Без цього браузер тримав СТАРИЙ editor.html, і жодна
    # версія всередині нього не рятувала — оператор бачив попередню карту.
    (OUT / "_headers").write_text(
        "/*.html\n  Cache-Control: no-cache\n"
        "/\n  Cache-Control: no-cache\n"
        "/mapper/*.js\n  Cache-Control: public, max-age=31536000\n"
        "/mapper/*.css\n  Cache-Control: public, max-age=31536000\n",
        encoding="utf-8")
    tiles = src / "tiles"
    if tiles.is_dir():
        shutil.copytree(tiles, dst / "tiles", dirs_exist_ok=True)
    print(f"-> {dst}/editor.html  ({n} файлів + кеш плиток)")


def main():
    ap = argparse.ArgumentParser("site")
    ap.add_argument("--days", type=int, default=0, help="скільки останніх днів (0 = всі)")
    ap.add_argument("--raids", action="store_true", help="перегенерувати сторінки нальотів")
    # Карти нальотів — 99% часу збірки: 93 доби без них будуються 6 секунд, з
    # ними 5.5 хвилини. При цьому карта минулої доби більше не змінюється.
    # Тому свіжі перебудовуються щоразу (дані ще доходять), а старі — лише якщо
    # їх нема на диску. Разом із кешем site/raids у CI це тримає щогодинний
    # прогін у бюджеті безкоштовних хвилин, не ріжучи архів.
    ap.add_argument("--raid-days", type=int, default=0, metavar="N",
                    help="перебудовувати карти лише за N останніх діб "
                         "(0 = усі; відсутні добудовуються завжди)")
    a = ap.parse_args()

    st = ST.Store()
    dates = st.dates()
    if not dates:
        print("сховище порожнє — спершу python3 sync.py --rebuild")
        return 1
    if a.days:
        dates = dates[-a.days:]

    OUT.mkdir(exist_ok=True)
    (OUT / "raids").mkdir(exist_ok=True)

    # Спільний шар цілей для всіх карт. Копіюється щоразу, бо саме через це
    # сторінки й розʼїжджались: раніше кожна вшивала власний знімок, а cron
    # перебудовує лише останні дні. Один файл — одна версія для всього архіву.
    for name, why in (("targets.json", "карти будуть без шару цілей"),
                      ("regions.json", "карти будуть без меж областей")):
        if not Path(name).exists():
            print(f"! {name} нема — {why}")
            continue
        if name == "regions.json":
            # Карта зшиває контур області з подією ЗА НАЗВОЮ (`POLY[e.region]`),
            # а події публікуються вже з назвою для читача. Якби тут лишились
            # внутрішні ключі, для пʼяти перейменованих областей POLY[reg]
            # повертав би undefined і заливка тривоги тихо зникала б — карта
            # малювалась би далі, без жодної помилки в консолі.
            poly = json.load(open(name, encoding="utf-8"))
            json.dump({region_label(k): v for k, v in poly.items()},
                      open(OUT / name, "w", encoding="utf-8"), ensure_ascii=False)
        else:
            shutil.copyfile(name, OUT / name)

    copy_mapper()

    # Числа для прози — раз на збірку, з поточного сховища, не з памʼяті.
    #
    # Рахуються ПЕРШИМИ навмисно: усі три йдуть одним проходом по всьому
    # архіву, а далі збірка працює подобово. Порахувати їх посередині означало
    # б тримати в памʼяті і весь архів, і всі подобові вікна разом — заміряно
    # 1.47 ГБ проти 0.9 ГБ, і це на ранері, де поруч ще й підпроцеси карт
    # нальотів.
    count_pct = count_share(st)
    conf_pct = confirmed_share(st)
    n_solo, n_reg, solo_share = voice_coverage(st)
    forget_full()

    rows = []
    for d in dates:
        lo, hi = day_window(d)
        ev = win(st, lo, hi)
        if not ev:
            continue
        s = summarize(ev)
        s["date"] = d
        rows.append(s)

    # ---- сторінки нальотів ------------------------------------------------
    if a.raids:
        # Свіжі доби перебудовуються завжди: дані по них ще доходять, і карта
        # вчорашньої ночі о 03:00 неповна. Старі — тільки якщо файлу нема.
        rebuild = {r["date"] for r in rows[-a.raid_days:]} if a.raid_days else None
        built = {p.stem for p in (OUT / "raids").glob("*.html")}
        # Дані ночі для редактора роблю тим самим прогоном: raid_<дата>.json
        # уже на диску, а mknight з нього дає підказки й позначки. Ніч без
        # свого файла — це ніч, якої оператор не побачить у списку дат.
        nights = OUT / "mapper" / "nights"
        nights.mkdir(parents=True, exist_ok=True)
        have_night = {p.stem for p in nights.glob("*.js")}
        # Пороги РІЗНІ, і це не дрібниця. Сторінка нальоту — публічна, тиха
        # доба на ній читається як порожня новина, тому там лишається 40
        # точок. А ніч для редактора — інструмент оператора: він відкриває
        # поточну добу, коли вона тільки почалась і подій за неї ще п'ять.
        # Спільний поріг давав рівно те, на що він і поскаржився: «а чому
        # немає за 9 число? це ж з 12 дня мало вже бути 9 число» — доба йшла
        # п'яту годину, у зведенні стояло 15 спостережень, а в списку дат
        # редактора її не було взагалі.
        PAGE_MIN, NIGHT_MIN = 40, 3
        # Відбиток кожної ночі — див. tgmine/nightprint.py. Ніч, чий відбиток
        # змінився (сховище її вікна, код чи дані, що її будують), будується
        # наново; записаний відбиток — лише після успішної збірки, тож
        # обірваний прогін просто доробить решту наступного разу.
        fp_path = OUT / "raids" / "_fingerprints.json"
        fp_path.parent.mkdir(parents=True, exist_ok=True)
        prints = NP.load(fp_path)
        code = NP.code_print(Path("."))
        why = collections.Counter()
        jobs = []
        for r in rows:
            d = r["date"]
            want_page = r["points"] >= PAGE_MIN
            want_night = r["points"] >= NIGHT_MIN
            if not want_page and not want_night:
                continue
            fresh = rebuild is not None and d in rebuild
            done_page = (not want_page) or d in built
            done_night = (not want_night) or d in have_night
            fp = NP.night_print(Path("."), d, code)
            stale = prints.get(d) != fp
            if not fresh and done_page and done_night and not stale:
                continue
            why["свіжих" if fresh else "відсутніх" if not (done_page and done_night)
                else "застарілих"] += 1
            jobs.append((d, want_page, want_night, str(nights / f"{d}.js"), fp))
        for res in run_nights(jobs):
            d = res["d"]
            if res["err"]:
                print(f"  ! наліт {d}: {res['err']}")
                continue
            if res["night_err"]:
                print(f"  ! ніч для редактора {d}: {res['night_err']}")
            else:
                prints[d] = res["fp"]
                NP.save(fp_path, prints)
            print(f"  наліт {d} ok" if res["page"] else f"  ніч {d} ok (тиха доба)")
        # Рядок для логу CI — окремо свіжі (завжди), відсутні (холодний кеш)
        # і застарілі (змінився відбиток). У звичайному прогоні відсутніх і
        # застарілих 0. Перша версія рахувала лише застарілі й на холодному
        # прогоні писала «0», хоча зібрано було все, — рядок, який має бути
        # доказом, вводив в оману.
        print("  відбиток: перебудовано " + (", ".join(
            f"{k} {why[k]}" for k in ("свіжих", "відсутніх", "застарілих")) or "0"))
        # Відбиток АРХІВУ — ночей поза свіжими — для ключа кешу CI. Свіжі
        # змінюються щогодини; з ними ключ міняв би кожен прогін (53 МБ × 24
        # на добу). Без них ключ сталий у звичайні прогони і новий рівно тоді,
        # коли перебудовано архів, — інакше збереження «вже існує» не пустило
        # б новий архів у кеш, і кожен наступний прогін будував би його знову.
        arch = {d: f for d, f in prints.items() if not (rebuild and d in rebuild)}
        (OUT / "raids" / "_archive_print.txt").write_text(
            hashlib.sha256(json.dumps(arch, sort_keys=True).encode()).hexdigest() + "\n",
            encoding="utf-8")
        night_index(nights)

    have = {p.stem for p in (OUT / "raids").glob("*.html")}

    # ---- денні звіти ------------------------------------------------------
    (OUT / "day").mkdir(exist_ok=True)
    for i, r in enumerate(rows):
        lo, hi = day_window(r["date"])
        ev = win(st, lo, hi)
        prev = rows[max(0, i - 7):i]
        (OUT / "day" / f"{r['date']}.html").write_text(
            day_page(r["date"], ev, r, prev, r["date"] in have,
                     rows[i - 1]["date"] if i > 0 else None,
                     rows[i + 1]["date"] if i + 1 < len(rows) else None,
                     count_pct=count_pct),
            encoding="utf-8")

    # ---- жива сторінка ----------------------------------------------------
    now = datetime.now(timezone.utc).astimezone(MSK)
    recent = win(st, now - timedelta(hours=6), now + timedelta(minutes=5))
    recent = clean(recent)
    last_state = {}
    for e in clean(win(st, now - timedelta(hours=24), now + timedelta(minutes=5))):
        if e.get("region") and e["scope"] == "область":
            last_state[e["region"]] = e["kind"]
    live = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "points_6h": sum(1 for e in recent if e["scope"] == "точка"),
        "drones_6h": ST.declared([e for e in recent if not e.get("dup_of")])["largest"],
        "pvo_6h": sum(1 for e in recent if e["kind"] in ("ППО", "збиття")),
        "alerts": sorted(region_label(k) for k, v in last_state.items()
                         if v not in ("відбій",)),
        "recent": [{"hhmm": datetime.fromisoformat(e["t"]).strftime("%H:%M"),
                    "kind": e["kind"], "place": region_label(e.get("place")),
                    "text": e["text"], "url": e["url"]}
                   for e in reversed(recent[-40:])],
    }
    json.dump(live, open(OUT / "live.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    (OUT / "live.html").write_text(live_page(), encoding="utf-8")

    # ---- зведення ---------------------------------------------------------
    tot = {k: sum(r[k] for r in rows) for k in
           ("msgs", "points", "pvo", "kills", "booms", "with_count")}
    # найбільшу групу за період не сумують — беруть максимум
    tot["largest"] = max((r["largest"] for r in rows), default=0)
    reg = collections.Counter()
    for r in rows:
        reg.update(r["regions"])
    mx_dr = max((r["largest"] for r in rows), default=1)
    mx_pt = max((r["points"] for r in rows), default=1)

    daily = "\n".join(
        f'<tr><td>{"<a href=raids/%s.html>%s</a>" % (r["date"], r["date"]) if r["date"] in have else r["date"]}</td>'
        f'<td class=n>{r["points"]}</td>'
        f'<td>{bar(r["points"], mx_pt, 110)}</td>'
        f'<td class=n>{r["largest"] or "—"}</td>'
        f'<td>{bar(r["largest"], mx_dr, 110, "r")}</td>'
        f'<td class=n>{r["pvo"] or "—"}</td><td class=n>{r["kills"] or "—"}</td>'
        f'<td class=n>{r["deep"]}</td>'
        f'<td class=big>{esc(", ".join(region_label(k) for k, _ in r["regions"].most_common(3)))}</td></tr>'
        for r in reversed(rows))

    mxr = max(reg.values()) if reg else 1
    regtab = "\n".join(
        f'<tr><td>{esc(region_label(k))}</td><td class=n>{v}</td><td>{bar(v, mxr, 220)}</td></tr>'
        for k, v in reg.most_common(18))

    # Найгарячіші цілі за весь період — з рангу targets.json (hits за місяць).
    T_UA = {"refinery": "НПЗ", "airfield": "аеродром", "ammo_depot": "склад БК",
            "defense_plant": "оборонний завод", "chemical": "хімія",
            "fuel_depot": "нафтобаза", "naval": "ВМБ",
            "military_base": "військова зона", "range": "полігон"}
    try:
        tgt = json.load(open("targets.json", encoding="utf-8"))["objects"]
    except FileNotFoundError:
        tgt = []
    # лише стратегічні цілі й паливо (ярус 1-2); військові зони/полігони (ярус 3)
    # виключено — їх «жар» це артефакт міст із багатьма тривогами, не удари.
    # Дедуп за tid, не за назвою. Раніше тут стояв дедуп за назвою — милиця під
    # те, що hits рахувався по імені й тезки давали однакові рядки. Тепер жар
    # рахується по обʼєкту, тож тезки — це РІЗНІ обʼєкти з різними числами, і
    # викидати їх не можна.
    seen = set()
    hot = []
    for o in sorted(tgt, key=lambda o: -o.get("hits", 0)):
        tid = ST.target_id(o)
        if (o.get("hits", 0) <= 0 or not o.get("name") or o.get("tier", 3) > 2
                or tid in seen):
            continue
        seen.add(tid)
        hot.append(o)
        if len(hot) >= 20:
            break
    dup_names = {n for n, c in collections.Counter(
        o["name"] for o in hot).items() if c > 1}
    mxh = hot[0]["hits"] if hot else 1
    hottab = "\n".join(
        f'<tr><td>{target_label(o["name"], ST.target_id(o), dup_names)}</td>'
        f'<td><span class=tag>{esc(T_UA.get(o["cat"], o["cat"]))}</span></td>'
        f'<td class=n>{o["hits"]}</td><td>{bar(o["hits"], mxh, 200, "r")}</td></tr>'
        for o in hot)

    upd = (st.state.get("updated") or "")[:16].replace("T", " ")
    body = f"""{nav("index")}
<div class=wrap>
<h1>Удари по РФ · моніторинг</h1>
<div class=lead>
Реконструкція за повідомленнями публічних моніторингових Telegram-каналів
(lpr1_treugolnik, kupolrussia, vrv_radar). Дзеркальні канали схлопнуто.<br>
Період {rows[0]['date']} — {rows[-1]['date']} · доба рахується 12:00–12:00 МСК · оновлено {upd} UTC
</div>

<div class=kpi>
  <div class=k><b style="color:var(--cyan)">{tot['points']}</b><span>спостережень</span></div>
  <div class=k><b>{tot['largest']}</b><span>найбільша група за період</span></div>
  <div class=k><b style="color:var(--red)">{tot['pvo']}</b><span>робота ППО</span></div>
  <div class=k><b>{tot['kills']}</b><span>збиття</span></div>
  <div class=k><b style="color:var(--amber)">{len(rows)}</b><span>діб</span></div>
</div>

<div class=cards>
  <a class=card href="live.html"><h3>→ Що зараз</h3>
    <p>Стан за останні 6 годин: області під тривогою, свіжі спостереження,
       індикатор свіжості даних.</p></a>
  <a class=card href="day/{rows[-1]['date']}.html"><h3>→ Звіт за останню добу</h3>
    <p>{rows[-1]['date']} · {rows[-1]['points']} спостережень.
       Хід ночі по годинах, регіони, найбільші групи.</p></a>
  <a class=card href="nights.html"><h3>→ Усі доби</h3>
    <p>{len(rows)} діб зі звітами та картами-програвачами.</p></a>
</div>

<h2>По добах</h2>
<div class=tw><table>
<tr><th>доба</th><th class=n>спостережень</th><th></th><th class=n>найбільша група</th><th></th>
    <th class=n>ППО</th><th class=n>збито</th><th class=n>глибина, км</th><th>основні регіони</th></tr>
{daily}
</table></div>

<h2>Регіони за весь період</h2>
<div class=tw><table>
<tr><th>регіон</th><th class=n>спостережень</th><th></th></tr>
{regtab}
</table></div>

<h2>Найгарячіші цілі за весь період</h2>
<div class=lead style="margin-bottom:10px">Скільки разів за {len(rows)} діб біля відомого
обʼєкта фіксували активність. Прив'язка орієнтовна (спостереження — центр НП,
не координата удару), тож це показник уваги, а не влучань.</div>
{'<div class=tw><table><tr><th>ціль</th><th>тип</th><th class=n>активностей</th><th></th></tr>'+hottab+'</table></div>' if hottab else '<div class=lead>даних про цілі нема — запусти rank_targets.py</div>'}

<div class=note>
<b>Як це читати.</b> «Спостереження» — це повідомлення про побачений або почутий
апарат у конкретному місці, а не підтверджений факт. «Найбільша група» — найбільше
з чисел, які назвали самі канали; число вони пишуть лише в {count_pct:.1%} згадок, тому це
<b>нижня межа</b>. Суми чисел за добу тут нема навмисно: одну групу фіксують
у кількох районах поспіль, і сума рахує її двічі-тричі. «Глибина» — 90-й перцентиль відстані від
підконтрольної Україні території; межа взята на рівні областей, тож для точок
поруч із Запоріжжям чи Херсоном вона занижена на десятки кілометрів.<br><br>
<b>Чого тут нема.</b> Наслідків ударів: канали моніторять підліт, а не влучання,
тому «збито» і «вибухів» тут систематично занижені й не годяться для оцінки
результативності.<br><br>
<b>Головне викривлення.</b> Щільність повідомлень залежить від кількості
спостерігачів. Підмосков'я виглядатиме активнішим за Тамбовщину навіть за
однакової кількості апаратів. Це дані про <b>повідомлення</b>, не про факти.<br><br>
<b>Скільки тут незалежних свідчень.</b> Каналів три, але два з них дзеркалять
одне одного, тож незалежних голосів лише два — і покривають вони різні
території, а не перевіряють одне одного. Спостережень, які підтвердив другий
голос (те саме місце й тип у вікні години), — <b>{conf_pct:.1%}</b>. У <b>{n_solo} з
{n_reg}</b> регіонів понад 90% спостережень дає один канал; на них припадає
{solo_share:.0%} усіх точкових спостережень. Практично це означає: майже скрізь
на цій карті другої думки немає, і помилка, мовчання чи упередженість одного
каналу нічим не компенсуються.
</div>
</div>"""

    page = (f"<!doctype html><html lang=uk><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>Удари по РФ · моніторинг</title><style>{CSS}</style></head>"
            f"<body>{body}</body></html>")
    (OUT / "index.html").write_text(page, encoding="utf-8")

    # сторінка-перелік: кожна ніч зі звітом і картою
    cards = "\n".join(
        f'<a class=card href="day/{r["date"]}.html"><h3>{r["date"]}</h3>'
        f'<p>{r["points"]} спостережень · найбільша група {r["largest"] or "—"} · '
        f'ППО {r["pvo"]}<br>{esc(", ".join(region_label(k) for k, _ in r["regions"].most_common(3)))}'
        f'{" · <span style=color:#38d4dd>є карта</span>" if r["date"] in have else ""}</p></a>'
        for r in reversed(rows))
    nights = (f"<!doctype html><html lang=uk><head><meta charset=utf-8>"
              f"<meta name=viewport content='width=device-width,initial-scale=1'>"
              f"<title>Доби · моніторинг</title><style>{CSS}</style></head><body>"
              f'{nav("nights")}<div class=wrap><h1>Усі доби</h1>'
              f'<div class=lead>{len(rows)} діб у сховищі. Клік — звіт за добу, '
              f'усередині посилання на карту-програвач.</div>'
              f'<div class=cards>{cards}</div></div></body></html>')
    (OUT / "nights.html").write_text(nights, encoding="utf-8")

    # ---- 404 --------------------------------------------------------------
    # Без цього файла Cloudflare Pages на будь-який неіснуючий шлях віддає
    # index.html із кодом 200. Перевірено на бойовому домені: /raids/1999-01-01
    # і /raids/явно-нема повертали байт-у-байт головну сторінку, код 200.
    #
    # Це не косметика. По-перше, будь-яка перевірка «карта на місці?» за кодом
    # відповіді стає безглуздою — 200 приходить і на відсутній файл, тобто
    # зникнення половини архіву виглядало б як повний порядок. По-друге,
    # пошуковики індексують нескінченну кількість однакових сторінок. І це
    # реально плутає: карти поточної доби ще нема (вона зʼявляється, коли за
    # добу набереться 40 точкових спостережень), а посилання на неї віддавало
    # головну, ніби все зібрано.
    notfound = (f"<!doctype html><html lang=uk><head><meta charset=utf-8>"
                f"<meta name=viewport content='width=device-width,initial-scale=1'>"
                f"<title>Сторінки нема · моніторинг</title>"
                f"<style>{CSS}</style></head><body>"
                # up="/" — 404 віддається для БУДЬ-ЯКОГО шляху, зокрема
                # /raids/…, і відносні посилання шапки вели б звідти в
                # /raids/index.html. Тільки абсолютні.
                f'{nav("", up="/")}<div class=wrap><h1>Такої сторінки нема</h1>'
                f'<div class=lead>Можливо, карти за цю добу ще нема: сторінка '
                f'нальоту зʼявляється, коли за оперативну добу (12:00-12:00 МСК) '
                f'набереться щонайменше 40 точкових спостережень. Тиха доба '
                f'окремої карти не отримує.</div>'
                f'<div class=cards>'
                f'<a class=card href="/"><h3>→ Головна</h3><p>зведення за всі доби</p></a>'
                f'<a class=card href="/nights.html"><h3>→ Усі доби</h3>'
                f'<p>{len(rows)} діб, {len(have)} карт</p></a>'
                f'<a class=card href="/live.html"><h3>→ Що зараз</h3>'
                f'<p>останні шість годин</p></a>'
                f'</div></div></body></html>')
    (OUT / "404.html").write_text(notfound, encoding="utf-8")

    json.dump({"updated": st.state.get("updated"), "days": rows},
              open(OUT / "summary.json", "w", encoding="utf-8"),
              ensure_ascii=False, default=str, indent=1)

    print(f"-> {OUT}/index.html  ({len(rows)} діб, {len(have)} карт)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
