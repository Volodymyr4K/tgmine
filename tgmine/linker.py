"""Звʼязування фрагментів ночі памʼяттю коридорів (BACKLOG §16.13).

Маршрути ночі (`routes.build`) — обрізки: канали не пишуть позицію однієї
групи безперервно. Людина звʼязує їх очима, бо знає, КУДИ зазвичай летять:
72% ланок «місце -> місце» кожної ночі (клітинки 0.5°) уже траплялись у
попередні ночі. Тут те саме знання — у скількох ночах ДО цієї (без
підглядання в майбутнє) був заявлений текстом перехід між клітинками.

Що перевірено, щоб не повторити хибний висновок. Памʼять коридорів добре
вгадує, КУДИ йде потік (прихована заявлена ціль — 66%, найвпевненіші 20% —
92%, `tools/ab/linking/prior_eval.py`), але чи наступний фрагмент — та сама
група в той самий час, дані не кажуть: звʼязків фрагментів стільки ж, як і
з перемішаним часом (149 проти 147; з напрямком із тексту й типом — ~20%
понад випадок). Тому звʼязок тут — «потік ішов звичним коридором», а не
«той самий дрон», і на карті він так і позначений (`link_corridors`).
"""
from __future__ import annotations

import collections
import json
from pathlib import Path

from .geocode import haversine

CELL = 0.5
DT_MIN, DT_MAX = 10, 180  # хв між кінцем A й початком B
V_NOM = 160.0
D_MIN, D_MAX = 5.0, 350.0

_DAYS: dict | None = None


def cell(la, lo):
    return (round(la / CELL), round(lo / CELL))


def day_counts(root="store") -> dict:
    """{день: Counter[(клітинка A, клітинка B)]} — унікальні за день ланки
    «місце -> місце» з поля `legs` (кінці не площі), без дублів і шуму.
    Рахується раз на процес."""
    global _DAYS
    if _DAYS is None:
        out = {}
        for f in sorted(Path(root, "events").glob("*.jsonl")):
            pairs = set()
            for line in f.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                e = json.loads(line)
                if e.get("dup_of") or e.get("noise"):
                    continue
                for g in e.get("legs") or []:
                    if not g[3] and not g[7]:
                        pairs.add((cell(g[1], g[2]), cell(g[5], g[6])))
            out[f.stem] = collections.Counter(pairs)
        _DAYS = out
    return _DAYS


class Prior:
    """Памʼять коридорів з днів СУВОРО до `day`.

    `trans` — у скількох днях траплялась пара клітинок (лічильники днів
    унікальні, тож це саме «ночей», а не повідомлень)."""

    def __init__(self, day, root="store"):
        self.trans = collections.Counter()
        for d, c in day_counts(root).items():
            if d < day:
                self.trans.update(c)

    def nights(self, a, c):
        """Скільки разів у попередніх ночах був коридор із клітинки `a` (чи
        сусідньої) у клітинку `c` (чи сусідню). Сусідні — з обох боків: кінці
        маршрутів — села поруч із місцями заявлених ланок, і точна клітинка
        0.5° відсікала 3/4 пар (перевірка 22.09.2026)."""
        ca, cc = cell(*a), cell(*c)
        return sum(self.trans[((ca[0] + ax, ca[1] + ay), (cc[0] + dx, cc[1] + dy))]
                   for ax in (-1, 0, 1) for ay in (-1, 0, 1)
                   for dx in (-1, 0, 1) for dy in (-1, 0, 1))


def _mins(hhmm):
    h, m = map(int, hhmm.split(":"))
    return (h + 24 if h < 12 else h) * 60 + m


def chains(n, links):
    """Ланцюги індексів маршрутів за звʼязками [(i, j, …)]; без циклів."""
    nxt = {i: j for i, j, _ in links}
    has_prev = {j for _, j, _ in links}
    out, seen = [], set()
    for s in range(n):
        if s in has_prev or s in seen:
            continue
        ch, cur = [], s
        while cur is not None and cur not in seen:
            ch.append(cur)
            seen.add(cur)
            cur = nxt.get(cur)
        out.append(ch)
    for s in range(n):                     # решта — у циклах, беремо як є
        if s not in seen:
            out.append([s])
            seen.add(s)
    return out


#: «Звичний коридор» — траплявся щонайменше в стількох попередніх ночах.
CORRIDOR_MIN_NIGHTS = 3
#: Швидкість між кінцем і початком, км/год.
CV_MIN, CV_MAX = 80.0, 230.0
#: Довший місток не малюємо: жирна лінія на пів театру читається як сильне
#: твердження, а підстава в неї та сама, що в короткої (знімок 22.09.2026).
BRIDGE_MAX_KM = 200.0


def link_corridors(routes, prior: Prior):
    """[(i, j, ночей)] — кінець маршруту i продовжено початком маршруту j
    ЗВИЧНИМ КОРИДОРОМ (рішення оператора 22.09.2026, BACKLOG §16.13).

    Це НЕ твердження «та сама група»: перевірено, що часова тотожність
    фрагментів у наших даних на рівні випадку. Це твердження «потік ночі
    йшов звичним коридором», і на карті воно так і позначене — жирним
    напівпрозорим містком із кількістю ночей, у які коридор траплявся.
    Умови: пізніше на DT_MIN..DT_MAX хв, швидкість CV_MIN..CV_MAX км/год,
    коридор у ≥ CORRIDOR_MIN_NIGHTS попередніх ночах; далі жадібно від
    найчастішого коридору, кожен кінець і початок — один раз.
    """
    ends, starts = [], []
    for i, r in enumerate(routes):
        pts = r.get("pts") or []
        if not pts or not pts[0].get("hhmm") or not pts[-1].get("hhmm"):
            continue
        ends.append((i, (pts[-1]["la"], pts[-1]["lo"]), _mins(pts[-1]["hhmm"])))
        starts.append((i, (pts[0]["la"], pts[0]["lo"]), _mins(pts[0]["hhmm"])))
    props = []
    for i, a, ta in ends:
        for j, c, tc in starts:
            if j == i:
                continue
            dt = tc - ta
            if not (DT_MIN <= dt <= DT_MAX):
                continue
            d = haversine(a, c)
            if not (D_MIN < d <= BRIDGE_MAX_KM):
                continue
            v = d / (dt / 60.0)
            if not (CV_MIN <= v <= CV_MAX):
                continue
            n = prior.nights(a, c)
            if n >= CORRIDOR_MIN_NIGHTS:
                props.append((n, -abs(v - V_NOM), i, j))
    used_end, used_start, out = set(), set(), []
    for n, _, i, j in sorted(props, key=lambda p: (-p[0], -p[1], p[2], p[3])):
        if i in used_end or j in used_start:
            continue
        used_end.add(i)
        used_start.add(j)
        out.append((i, j, n))
    return out
