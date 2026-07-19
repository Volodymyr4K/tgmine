"""Крос-канальна дедуплікація.

Канали-монітори рясно копіюють одне одного: у зібраному корпусі
kupolrussia повторює lpr1_treugolnik у 70% постів із медіанним лагом 14 сек.
Без дедупу така пара дає подвійний рахунок і фальшиве відчуття підтвердження.

Кластеризація: однаковий нормалізований текст у межах часового вікна = одна подія.
Канонічною стає найраніша публікація; решта йде в `sources` — і кількість
НЕЗАЛЕЖНИХ каналів у кластері є мірою підтвердженості.
"""
from __future__ import annotations

import collections
import re
from datetime import datetime, timedelta

PUNCT = re.compile(r"\W+", re.UNICODE)


def norm(text: str) -> str:
    return PUNCT.sub(" ", text.lower()).strip()


def overlap_matrix(posts: list[dict], window_min: int = 10) -> dict:
    """Частка постів каналу A, що мають двійника в каналі B."""
    by_ch = collections.defaultdict(set)
    for p in posts:
        if p["text"].strip():
            by_ch[p["channel"]].add(norm(p["text"]))
    out = {}
    for a in by_ch:
        for b in by_ch:
            if a != b:
                inter = by_ch[a] & by_ch[b]
                out[(a, b)] = len(inter) / len(by_ch[a]) if by_ch[a] else 0.0
    return out


def cluster(posts: list[dict], window_min: int = 10,
            groups: dict[str, str] | None = None) -> list[dict]:
    """Схлопує дублікати в події.

    groups: канал -> назва кластера джерел. Канали одного кластера рахуються
    як ОДИН незалежний голос (напр. дзеркало і його джерело).
    """
    groups = groups or {}
    window = timedelta(minutes=window_min)
    buckets: dict[str, list[dict]] = collections.defaultdict(list)
    for p in sorted(posts, key=lambda x: x["date"]):
        if not p["text"].strip():
            continue
        buckets[norm(p["text"])].append(p)

    events = []
    for key, group in buckets.items():
        cur: list[dict] = []
        for p in group:
            t = datetime.fromisoformat(p["date"])
            if cur and t - datetime.fromisoformat(cur[0]["date"]) > window:
                events.append(_mk(cur, groups))
                cur = []
            cur.append(p)
        if cur:
            events.append(_mk(cur, groups))
    return sorted(events, key=lambda e: e["date"])


def _mk(group: list[dict], groups: dict[str, str]) -> dict:
    first = min(group, key=lambda p: p["date"])
    chans = sorted({p["channel"] for p in group})
    voices = sorted({groups.get(c, c) for c in chans})
    e = dict(first)
    e["sources"] = [p["url"] for p in sorted(group, key=lambda x: x["date"])]
    e["channels"] = chans
    e["n_channels"] = len(chans)
    e["n_independent"] = len(voices)     # підтвердженість
    e["dup_count"] = len(group)
    lags = [(datetime.fromisoformat(p["date"]) -
             datetime.fromisoformat(first["date"])).total_seconds() for p in group]
    e["max_lag_sec"] = max(lags) if lags else 0
    return e


def report(posts: list[dict], events: list[dict], out=print) -> None:
    out(f"\n== ДЕДУП ==")
    out(f"  постів {len(posts)} -> подій {len(events)} "
        f"(схлопнуто {len(posts)-len(events)}, {(1-len(events)/len(posts))*100:.1f}%)")
    dist = collections.Counter(e["n_independent"] for e in events)
    out("  підтверджень (незалежних джерел на подію):")
    for k in sorted(dist):
        out(f"    {k}: {dist[k]:5}")
    multi = [e for e in events if e["n_channels"] > 1]
    if multi:
        lags = sorted(e["max_lag_sec"] for e in multi)
        out(f"  медіанний лаг між копіями: {lags[len(lags)//2]:.0f} сек")



