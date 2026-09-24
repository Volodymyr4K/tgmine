"""Стан джерел для редактора: чи не замовк канал, поки інші пишуть.

Навіщо. Глибокий тил на карті тримається майже на одному каналі: частка
vrv_radar у крапках за 45 діб — Москва 93%, Твер 91%, Тула 89%, Рязань,
Татарстан і Самара 88% (аудит 24.09.2026, BACKLOG). Канал заблокують,
перейменують або він переїде в MAX — і тил тихо спорожніє, а оператор
вирішить, що ніч була спокійна. Збій самого збору (t.me не віддає сторінку)
виглядає так само. Тут це стає видимим: `site.py` кладе `mapper/health.json`,
редактор показує червоний блок у «Даних ночі».

Що вважається мовчанням. Не години самі по собі: у vrv_radar денне затишшя
буває 8.6 год, а exilenova_plus мовчить і по 15 год, коли нема влучань.
Мірило — скільки постів за той самий час написали ІНШІ канали моніторингу:
канал, що мовчить, поки навколо йде наліт, мовчить не через тишу. Пороги —
у 1.3 раза вище найбільшого числа на справжніх паузах з 1 травня по 24
вересня 2026 (у дужках): lpr1 100 (77), kupol 220 (165), vrv 320 (244),
locator 580 (446), exilenova 1250 (951). Запас удвічі давав тривогу про
vrv, що замовк о 21:00 МСК, аж до полудня наступного дня; з 1.3 — через
2–6.5 год (стенд: обрізати канал о 21:00 МСК на шести справжніх ночах), при
тому за ті ж пів року жодної хибної. Запасна межа в годинах — коли мовчать
усі (тоді «інших» нуль): 16 для моніторингу, 30 для наслідків; за пів року
її перейшла одна пауза — vrv_radar 9–10 травня, 25 год. І окремо: жоден
канал моніторингу не приніс нічого ALL_QUIET_H годин — це вже збір, а не
канал (найдовша така пауза з травня — 3.7 год).
"""
from __future__ import annotations

import bisect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

#: Канали моніторингу — «інші» для кожного з них (і для наслідків).
MONITOR = ("lpr1_treugolnik", "kupolrussia", "vrv_radar", "locatorru")

#: канал -> (постів інших за паузу, години без огляду на інших, що покриває)
LIMITS = {
    "lpr1_treugolnik": (100, 16, "прикордоння, Крим і ТОТ"),
    "kupolrussia": (220, 16, "Крим, ТОТ і прикордоння"),
    "vrv_radar": (320, 16, "глибокий тил: Москва, Центр, Поволжя"),
    "locatorru": (580, 16, "прикордоння, Центр і північ"),
    "exilenova_plus": (1250, 30, "наслідки ударів"),
}

#: Жоден канал моніторингу не приніс поста стільки годин — стоїть збір.
ALL_QUIET_H = 6
#: Скільки днів паузи зберігати — з запасом на ночі, які оператор відкриває
#: заднім числом.
KEEP_DAYS = 40


def _times(path: Path, since: float) -> list[float]:
    out = []
    if not path.exists():
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            t = datetime.fromisoformat(json.loads(line)["date"]).timestamp()
            if t >= since:
                out.append(t)
    out.sort()
    return out


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def gaps(times: dict[str, list[float]], now: float, since: float) -> list[dict]:
    """Паузи-мовчання всіх каналів. `to` = None — мовчить досі."""
    out = []
    for ch, (n_other, max_h, _) in LIMITS.items():
        ts = times.get(ch) or []
        others = [times.get(o) or [] for o in MONITOR if o != ch]
        # Паузи між постами і хвіст до «зараз». Канал без жодного поста у
        # вікні — пауза від початку вікна.
        edges = list(zip([since] + ts, ts + [now]))
        for i, (a, b) in enumerate(edges):
            if b - a < 3600:
                continue
            n = sum(bisect.bisect(o, b) - bisect.bisect(o, a) for o in others)
            if n >= n_other or (b - a) / 3600 >= max_h:
                ongoing = i == len(edges) - 1
                out.append({"ch": ch, "from": _iso(a), "to": None if ongoing else _iso(b),
                            "h": round((b - a) / 3600, 1), "others": n})
    # Мовчать усі канали моніторингу разом — це збір, а не канал.
    merged = sorted(t for ch in MONITOR for t in times.get(ch) or [])
    edges = list(zip([since] + merged, merged + [now]))
    for i, (a, b) in enumerate(edges):
        if (b - a) / 3600 >= ALL_QUIET_H:
            out.append({"ch": "*", "from": _iso(a), "to": None if i == len(edges) - 1 else _iso(b),
                        "h": round((b - a) / 3600, 1), "others": 0})
    out.sort(key=lambda g: g["from"])
    return out


def build(data_dir: Path, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=KEEP_DAYS)).timestamp()
    times = {ch: _times(data_dir / f"{ch}.jsonl", since) for ch in LIMITS}
    return {
        "built": _iso(now.timestamp()),
        "channels": {ch: {"last": _iso(ts[-1]) if ts else None, "covers": LIMITS[ch][2]}
                     for ch, ts in times.items()},
        "gaps": gaps(times, now.timestamp(), since),
    }


def write(data_dir: Path, out: Path, now: datetime | None = None) -> dict:
    h = build(data_dir, now)
    out.write_text(json.dumps(h, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    live = [g for g in h["gaps"] if g["to"] is None]
    print(f"-> {out}  (пауз за {KEEP_DAYS} діб: {len(h['gaps'])}, триває зараз: "
          + (", ".join(f"{g['ch']} {g['h']} год" for g in live) or "жодної") + ")")
    return h
