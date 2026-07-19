"""Аналітика над збагаченими постами.

Головний принцип: будь-яка частота порівнюється з базовою лінією. "80% постів
про X згадують Y" нічого не варте, якщо Y є у 80% усіх постів.
"""
from __future__ import annotations

import collections
import re
import statistics
from datetime import datetime, timedelta, timezone


def _dt(p, tz):
    return datetime.fromisoformat(p["date"]).astimezone(tz)


def counts(posts, etype=None):
    """Скільки згадок кожної сутності; окремо — з розбивкою по модифікатору."""
    total, by_mod = collections.Counter(), collections.Counter()
    for p in posts:
        for e in p.get("entities", []):
            if etype and e["type"] != etype:
                continue
            total[e["value"]] += 1
            by_mod[(e["value"], e["modifier"] or "—")] += 1
    return total, by_mod


def timeline(posts, tz, unit="day"):
    fmt = {"hour": "%Y-%m-%d %H:00", "day": "%Y-%m-%d", "week": "%Y-W%V"}[unit]
    return collections.Counter(_dt(p, tz).strftime(fmt) for p in posts)


def hour_of_day(posts, tz):
    return collections.Counter(_dt(p, tz).hour for p in posts)


def bursts(posts, tz, gap_min=15, min_len=3):
    """Серії постів із малим інтервалом — масовані епізоди."""
    s = sorted(posts, key=lambda p: p["date"])
    out, cur = [], []
    for a, b in zip(s, s[1:]):
        if not cur:
            cur = [a]
        if (_dt(b, tz) - _dt(a, tz)).total_seconds() <= gap_min * 60:
            cur.append(b)
        else:
            if len(cur) >= min_len:
                out.append(cur)
            cur = []
    if len(cur) >= min_len:
        out.append(cur)
    return sorted(out, key=len, reverse=True)


def cooccurrence(posts, tag):
    """Чи згадується tag разом з іншими — З БАЗОВОЮ ЛІНІЄЮ.

    lift = P(інший | tag) / P(інший | не tag). lift≈1 → незалежні.
    """
    has = [p for p in posts if tag in p.get("tags", [])]
    hasnt = [p for p in posts if tag not in p.get("tags", [])]
    rows = []
    if not has or not hasnt:
        return rows
    others = {t for p in posts for t in p.get("tags", [])} - {tag}
    for o in sorted(others):
        a = sum(o in p["tags"] for p in has) / len(has)
        b = sum(o in p["tags"] for p in hasnt) / len(hasnt)
        rows.append({"tag": o, "with": a, "without": b,
                     "lift": (a / b) if b else float("inf")})
    return sorted(rows, key=lambda r: -r["lift"])


def hourly_correlation(posts, tz, tag_a, tag_b):
    """Кореляція інтенсивності двох тегів по годинах.

    Одиниця аналізу — година, не пост. У щільних каналах пост-рівнева
    ко-згадка меряє формат публікацій, а не реальність.
    """
    H = collections.defaultdict(collections.Counter)
    for p in posts:
        h = _dt(p, tz).replace(minute=0, second=0, microsecond=0)
        for t in p.get("tags", []):
            H[h][t] += 1
        H[h]["_all"] += 1
    hours = sorted(H)
    if len(hours) < 3:
        return None
    xs = [H[h][tag_a] for h in hours]
    ys = [H[h][tag_b] for h in hours]
    sx, sy = statistics.pstdev(xs), statistics.pstdev(ys)
    if not sx or not sy:
        return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    r = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / len(xs) / (sx * sy)
    with_a = [h for h in hours if H[h][tag_a]]
    without_a = [h for h in hours if not H[h][tag_a]]
    mean_with = statistics.mean([H[h][tag_b] for h in with_a]) if with_a else 0
    mean_without = statistics.mean([H[h][tag_b] for h in without_a]) if without_a else 0
    return {"r": r, "n_hours": len(hours), "hours_with": len(with_a),
            "mean_with": mean_with, "mean_without": mean_without,
            "lift": (mean_with / mean_without) if mean_without else float("inf")}


def views_median(posts):
    vs = []
    for p in posts:
        m = re.match(r"([\d.]+)([KM]?)", (p.get("views") or "").strip())
        if m:
            vs.append(float(m.group(1)) * {"": 1, "K": 1e3, "M": 1e6}[m.group(2)])
    return statistics.median(vs) if vs else None


def report(posts, cfg, tz_hours=0, focus=None, out=print):
    tz = timezone(timedelta(hours=tz_hours))
    tzname = f"UTC{tz_hours:+d}"
    focus = focus or cfg.segment_by
    sel = [p for p in posts if not focus or focus in p.get("tags", [])]

    out(f"\n{'='*60}\nКОНФІГ: {cfg.name}   період: {posts[0]['date'][:10]} … {posts[-1]['date'][:10]}")
    out(f"постів усього: {len(posts)}" + (f"   з тегом «{focus}»: {len(sel)}"
        f" ({len(sel)/len(posts)*100:.1f}%)" if focus else ""))
    chans = collections.Counter(p["channel"] for p in posts)
    out("канали: " + ", ".join(f"{c} ({n})" for c, n in chans.most_common()))

    for etype in cfg.entities:
        total, by_mod = counts(sel, etype)
        if not total:
            continue
        out(f"\n== {etype.upper()} ==")
        for v, c in total.most_common():
            mods = [f"{m}:{n}" for (vv, m), n in by_mod.most_common() if vv == v and m != "—"]
            out(f"  {c:5}  {v:22} {' '.join(mods)}")

    out(f"\n== ПО ДНЯХ ==")
    tl = timeline(sel, tz)
    mx = max(tl.values()) if tl else 1
    for k in sorted(tl):
        out(f"  {k}  {'#' * round(tl[k] / mx * 40)} {tl[k]}")

    out(f"\n== ПО ГОДИНАХ ДОБИ ({tzname}) ==")
    hh = hour_of_day(sel, tz)
    mx = max(hh.values()) if hh else 1
    for i in range(24):
        out(f"  {i:02}:00 {'#' * round(hh.get(i,0) / mx * 40)} {hh.get(i,0)}")

    bs = bursts(sel, tz)
    if bs:
        out(f"\n== СЕРІЇ (≥3 постів з інтервалом ≤15 хв) — {len(bs)} шт ==")
        for b in bs[:8]:
            ents = collections.Counter(e["value"] for p in b for e in p.get("entities", []))
            top = ", ".join(f"{v}" for v, _ in ents.most_common(2)) or "—"
            out(f"  {len(b):3} постів  {_dt(b[0],tz):%d.%m %H:%M}–{_dt(b[-1],tz):%H:%M}  {top}")

    if focus:
        co = cooccurrence(posts, focus)
        if co:
            out(f"\n== ЩО ЗГАДУЄТЬСЯ РАЗОМ З «{focus}» (з базовою лінією) ==")
            out(f"  {'тег':14} {'у постах з':>11} {'у решті':>9} {'lift':>7}")
            for r in co:
                out(f"  {r['tag']:14} {r['with']*100:10.1f}% {r['without']*100:8.1f}% {r['lift']:6.2f}x")
            out("  lift≈1 → незалежні; <1 → взаємовиключні; >1 → йдуть разом")

        out(f"\n== ГОДИННА КОРЕЛЯЦІЯ (одиниця = година, не пост) ==")
        for other in [t for t in cfg.tags if t != focus]:
            hc = hourly_correlation(posts, tz, focus, other)
            if hc:
                out(f"  {focus} ↔ {other:12} r={hc['r']:+.3f}  "
                    f"сер./год: з {focus} {hc['mean_with']:.2f} vs без {hc['mean_without']:.2f}"
                    f"  lift {hc['lift']:.2f}x")

    v = views_median(sel)
    if v:
        out(f"\nмедіана переглядів: {v:,.0f}")
    out("=" * 60)
