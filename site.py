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
import html
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from tgmine import store as ST

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
    РІЗНЕ. Виміряно: подій, підтверджених другим голосом (те саме місце й тип
    у вікні 60 хв), лише 3.1%.

    Спершу хотів ставити позначку «одне джерело» біля регіонів у таблиці. Не
    вийшло: при порозі 90% таких регіонів 35 із 39, при 95% — 23. Значок на
    майже кожному рядку нічого не повідомляє, а поріг створює артефакт (Крим
    із 94% лишався б «немаркованим», хоч фактично має одне джерело). Тому
    віддаємо число для тексту, а не прапорець на рядок.

    Рахуємо по ТОЧКОВИХ спостереженнях — саме їх показує таблиця регіонів.

    Повертає (скільки_регіонів_моно, усього_регіонів, частка_подій_у_моно).
    """
    days = st.dates()
    if not days:
        return (0, 0, 0.0)
    lo = datetime.fromisoformat(days[0]).replace(tzinfo=MSK)
    hi = datetime.fromisoformat(days[-1]).replace(tzinfo=MSK) + timedelta(days=2)
    by = collections.defaultdict(collections.Counter)
    for e in st.window(lo, hi):
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
        "drones": sum(e.get("drones") or 0 for e in uniq),
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


def day_page(date, ev, s, prev_stats, have_raid, prev_date=None, next_date=None):
    lo, hi = day_window(date)
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
        f'<tr><td>{esc(k)}</td><td class=n>{v}</td></tr>' for k, v in places.most_common(12))
    # 90-й перцентиль, а не максимум: одна помилка геокодування (тезка за
    # тисячу кілометрів) інакше стає «рекордом глибини» для цілого регіону
    def p90(reg):
        d = sorted(e["depth"] for e in pts if e.get("region") == reg and e.get("depth"))
        return d[int(len(d) * .9)] if d else 0
    regs = "\n".join(
        f'<tr><td>{esc(k)}</td><td class=n>{v}</td><td class=n>{p90(k)}</td></tr>'
        for k, v in s["regions"].most_common(14))

    big = sorted([e for e in pts if e.get("drones")],
                 key=lambda e: -e["drones"])[:8]
    bigrows = "\n".join(
        f'<tr><td>{datetime.fromisoformat(e["t"]).strftime("%H:%M")}</td>'
        f'<td class=n>{e["drones"]}</td><td>{esc(e["place"])}</td>'
        f'<td class=big>{esc(e["text"][:90])}</td>'
        f'<td><a href="{esc(e["url"])}" target=_blank>↗</a></td></tr>' for e in big)

    notable = [e for e in pts if e["kind"] in ("збиття", "вибух")][:10]
    notrows = "\n".join(
        f'<tr><td>{datetime.fromisoformat(e["t"]).strftime("%H:%M")}</td>'
        f'<td><span class=tag>{esc(e["kind"])}</span></td><td>{esc(e["place"])}</td>'
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
    # підтверджені хоча б двома повідомленнями — інакше показуємо помилку
    place_hits = collections.Counter(e["place"] for e in pts)
    conf = [e for e in pts if e.get("depth") and place_hits[e["place"]] >= 2]
    deepest = max(conf or pts, key=lambda e: e.get("depth") or 0, default=None)
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
  <div class=k><b>{s['drones'] or '—'}</b><span>заявлено апаратів</span>{cmp(s['drones'],'drones')}</div>
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
<div class=lead>{esc(deepest['place']) if deepest else '—'}
{f"· {deepest['depth']} км від кордону · {datetime.fromisoformat(deepest['t']).strftime('%H:%M')}" if deepest else ''}</div>

<h2>Найчастіші точки</h2>
<div class=tw><table><tr><th>місце</th><th class=n>повідомлень</th></tr>{top_pl}</table></div>

<div class=note>
{pager}
<div class=note>
«Спостереження» — повідомлення про побачений чи почутий апарат, не підтверджений
факт. «Заявлено апаратів» — сума чисел, які назвали канали; число вони вказують
рідко, тому це нижня межа. Збиття і вибухи систематично занижені: канали
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
    const stale = age>45;
    document.body.classList.toggle('stale',stale);
    document.getElementById('status').innerHTML =
      `<span class=pulse></span>дані станом на ${new Date(d.generated)
        .toLocaleString('uk-UA',{hour:'2-digit',minute:'2-digit',day:'2-digit',month:'2-digit'})}`+
      ` · ${age<1?'щойно':Math.round(age)+' хв тому'}`+
      (stale?' · <b style="color:#ff8a1f">оновлення затрималось</b>':'');
    document.getElementById('kpi').innerHTML = `
      <div class=k><b style="color:var(--cyan)">${d.points_6h}</b><span>спостережень за 6 год</span></div>
      <div class=k><b>${d.drones_6h||'—'}</b><span>заявлено апаратів</span></div>
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


def main():
    ap = argparse.ArgumentParser("site")
    ap.add_argument("--days", type=int, default=0, help="скільки останніх днів (0 = всі)")
    ap.add_argument("--raids", action="store_true", help="перегенерувати сторінки нальотів")
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
        if Path(name).exists():
            shutil.copyfile(name, OUT / name)
        else:
            print(f"! {name} нема — {why}")

    rows = []
    for d in dates:
        lo, hi = day_window(d)
        ev = st.window(lo, hi)
        if not ev:
            continue
        s = summarize(ev)
        s["date"] = d
        rows.append(s)

    # ---- сторінки нальотів ------------------------------------------------
    if a.raids:
        for r in rows:
            if r["points"] < 40:          # тихі ночі не варті окремої сторінки
                continue
            d = r["date"]
            try:
                subprocess.run([sys.executable, "raid.py", d], check=True,
                               capture_output=True, timeout=900)
                subprocess.run([sys.executable, "makeraid.py", f"raid_{d}.json"],
                               check=True, capture_output=True, timeout=900)
                shutil.move(f"raid_{d}.html", OUT / "raids" / f"{d}.html")
                Path(f"raid_{d}.json").unlink(missing_ok=True)
                print(f"  наліт {d} ok")
            except Exception as e:
                print(f"  ! наліт {d}: {e}")

    have = {p.stem for p in (OUT / "raids").glob("*.html")}

    # ---- денні звіти ------------------------------------------------------
    (OUT / "day").mkdir(exist_ok=True)
    for i, r in enumerate(rows):
        lo, hi = day_window(r["date"])
        ev = st.window(lo, hi)
        prev = rows[max(0, i - 7):i]
        (OUT / "day" / f"{r['date']}.html").write_text(
            day_page(r["date"], ev, r, prev, r["date"] in have,
                     rows[i - 1]["date"] if i > 0 else None,
                     rows[i + 1]["date"] if i + 1 < len(rows) else None),
            encoding="utf-8")

    # ---- жива сторінка ----------------------------------------------------
    now = datetime.now(timezone.utc).astimezone(MSK)
    recent = st.window(now - timedelta(hours=6), now + timedelta(minutes=5))
    recent = clean(recent)
    last_state = {}
    for e in clean(st.window(now - timedelta(hours=24), now + timedelta(minutes=5))):
        if e.get("region") and e["scope"] == "область":
            last_state[e["region"]] = e["kind"]
    live = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "points_6h": sum(1 for e in recent if e["scope"] == "точка"),
        "drones_6h": sum(e.get("drones") or 0 for e in recent),
        "pvo_6h": sum(1 for e in recent if e["kind"] in ("ППО", "збиття")),
        "alerts": sorted(k for k, v in last_state.items() if v not in ("відбій",)),
        "recent": [{"hhmm": datetime.fromisoformat(e["t"]).strftime("%H:%M"),
                    "kind": e["kind"], "place": e.get("place"),
                    "text": e["text"], "url": e["url"]}
                   for e in reversed(recent[-40:])],
    }
    json.dump(live, open(OUT / "live.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    (OUT / "live.html").write_text(live_page(), encoding="utf-8")

    # ---- зведення ---------------------------------------------------------
    tot = {k: sum(r[k] for r in rows) for k in
           ("msgs", "points", "drones", "pvo", "kills", "booms")}
    reg = collections.Counter()
    for r in rows:
        reg.update(r["regions"])
    mx_dr = max((r["drones"] for r in rows), default=1)
    mx_pt = max((r["points"] for r in rows), default=1)

    daily = "\n".join(
        f'<tr><td>{"<a href=raids/%s.html>%s</a>" % (r["date"], r["date"]) if r["date"] in have else r["date"]}</td>'
        f'<td class=n>{r["points"]}</td>'
        f'<td>{bar(r["points"], mx_pt, 110)}</td>'
        f'<td class=n>{r["drones"] or "—"}</td>'
        f'<td>{bar(r["drones"], mx_dr, 110, "r")}</td>'
        f'<td class=n>{r["pvo"] or "—"}</td><td class=n>{r["kills"] or "—"}</td>'
        f'<td class=n>{r["deep"]}</td>'
        f'<td class=big>{esc(", ".join(k for k, _ in r["regions"].most_common(3)))}</td></tr>'
        for r in reversed(rows))

    mxr = max(reg.values()) if reg else 1
    n_solo, n_reg, solo_share = voice_coverage(st)
    regtab = "\n".join(
        f'<tr><td>{esc(k)}</td><td class=n>{v}</td><td>{bar(v, mxr, 220)}</td></tr>'
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
  <div class=k><b>{tot['drones']}</b><span>заявлено апаратів</span></div>
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
<tr><th>доба</th><th class=n>спостережень</th><th></th><th class=n>апаратів</th><th></th>
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
апарат у конкретному місці, а не підтверджений факт. «Заявлено апаратів» —
сума чисел, які назвали самі канали; вони пишуть число далеко не завжди, тому
це <b>нижня межа</b>. «Глибина» — 90-й перцентиль відстані від українського
кордону.<br><br>
<b>Чого тут нема.</b> Наслідків ударів: канали моніторять підліт, а не влучання,
тому «збито» і «вибухів» тут систематично занижені й не годяться для оцінки
результативності.<br><br>
<b>Головне викривлення.</b> Щільність повідомлень залежить від кількості
спостерігачів. Підмосков'я виглядатиме активнішим за Тамбовщину навіть за
однакової кількості апаратів. Це дані про <b>повідомлення</b>, не про факти.<br><br>
<b>Скільки тут незалежних свідчень.</b> Каналів три, але два з них дзеркалять
одне одного, тож незалежних голосів лише два — і покривають вони різні
території, а не перевіряють одне одного. Спостережень, які підтвердив другий
голос (те саме місце й тип у вікні години), — <b>3.1%</b>. У <b>{n_solo} з
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
        f'<p>{r["points"]} спостережень · {r["drones"] or "—"} апаратів · '
        f'ППО {r["pvo"]}<br>{esc(", ".join(k for k, _ in r["regions"].most_common(3)))}'
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

    json.dump({"updated": st.state.get("updated"), "days": rows},
              open(OUT / "summary.json", "w", encoding="utf-8"),
              ensure_ascii=False, default=str, indent=1)

    print(f"-> {OUT}/index.html  ({len(rows)} діб, {len(have)} карт)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
