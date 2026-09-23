#!/usr/bin/env python3
"""Оновлення сховища. Одна команда, безпечна для повторних запусків.

  python3 sync.py                 # доваантажити нове й розібрати
  python3 sync.py --since 30d     # ширше вікно збору
  python3 sync.py --rebuild       # перебудувати похідний шар із сирого
  python3 sync.py --stat          # що вже є у сховищі

Придатне для cron: сирий шар накопичується інкрементально, похідний
перезаписується ідемпотентно, повторний запуск нічого не ламає.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from tgmine import aftermath as AF, extract as E, geocode as GC, scrape as S, store as ST

#: locatorru доданий 2026-07-24. НЕ дзеркало: висока схожість із рештою лише
#: 17.8% проти 73% у пари kupolrussia↔lpr1, унікальних 43%. Дає те, чого в
#: інших майже нема: вектори руху 36.2% постів проти 11.5%, наслідки (пожежа,
#: пошкодження) 1.2% проти 0.1%, і вчетверо-увосьмеро щільніше покриття півночі
#: та глибокого тилу (Ленінградська 24.3 згадки на 1000 постів проти 3.8,
#: Владимирська 30.9 проти 6.4, Удмуртія 5.8 проти 1.1). Пише населений пункт,
#: а не лише район.
#:
#: ВАЖЛИВО ПРО ГОЛОСИ: для обласних тривог і відбоїв це НЕ окремий голос —
#: медіанний лаг зі схожими постами +7…+9 с при 54/46, тобто обидва переказують
#: одне офіційне джерело (РСЧС/ЄДДС). Самостійним є точковий шар.
#:
#: Історія каналу глибша за наш корпус (id 68548 на 24.06), але добір ще не
#: зроблено, тому до 2026-06-24 його даних нема. Поки цього не виправлено,
#: будь-яке порівняння «місяць до місяця» через цю межу дасть стрибок покриття.
CHANNELS = ["lpr1_treugolnik", "kupolrussia", "vrv_radar", "locatorru"]
#: Канал НАСЛІДКІВ (з 23.09.2026, рішення власника): звітує про влучання й
#: пожежі, а не про підліт, тому в сховище подій не йде — з нього будується
#: окремий шар `store/aftermath/` (`tgmine/aftermath.py`). supernova_plus
#: перевіряли й не взяли.
AFTERMATH = ["exilenova_plus"]
CONFIG = "configs/ru-monitor.yaml"
GAZ = ("gazetteer/RU.txt", "gazetteer/UA.txt")


def parse_since(s):
    if s.endswith("d"):
        return datetime.now(timezone.utc) - timedelta(days=int(s[:-1]))
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def main():
    ap = argparse.ArgumentParser("sync")
    ap.add_argument("--since", default="2d", help="глибина збору (default: 2d)")
    ap.add_argument("--channels", nargs="*", default=CHANNELS)
    ap.add_argument("--rebuild", action="store_true",
                    help="перебудувати похідний шар із сирого, без мережі")
    ap.add_argument("--all-dates", action="store_true",
                    help="з --rebuild: не обмежуватись вікном наявного сховища")
    ap.add_argument("--stat", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    log = (lambda *x: None) if a.quiet else print

    st = ST.Store()

    if a.stat:
        rows = st.stat()
        if not rows:
            print("сховище порожнє")
            return 0
        print(f"{'дата':12}{'подій':>8}{'унік.':>8}{'точкових':>10}"
              f"{'з коорд.':>10}{'найб.група':>12}{'місць':>7}")
        for r in rows:
            print(f"{r['date']:12}{r['all']:>8}{r['uniq']:>8}{r['points']:>10}"
                  f"{r['geo']:>10}{r['largest']:>12}{r['count_places']:>7}")
        tot = {k: sum(r[k] for r in rows) for k in ("all", "uniq", "points")}
        # найбільшу групу не сумують — це максимум за період
        print(f"{'РАЗОМ':12}{tot['all']:>8}{tot['uniq']:>8}{tot['points']:>10}"
              f"{'':>10}{max(r['largest'] for r in rows):>12}")
        print(f"\nднів: {len(rows)}   {rows[0]['date']} … {rows[-1]['date']}")
        print(f"версія конвеєра: {st.state.get('version')}   "
              f"оновлено: {(st.state.get('updated') or '')[:19]}")
        return 0

    cfg = E.Config.load(CONFIG)
    gaz = GC.Gazetteer.load(*GAZ)
    try:
        targets = json.load(open("targets.json", encoding="utf-8"))
    except FileNotFoundError:
        targets = None

    if a.rebuild:
        # Перебудова з сирого шару: жодного мережевого запиту. Саме заради
        # цього сирий і похідний шари розділені.
        log("перебудова похідного шару з кешу…")
        posts = []
        for ch in a.channels:
            f = Path("data") / f"{ch}.jsonl"
            if not f.exists():
                log(f"  ! нема {f}")
                continue
            rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
            posts.extend(rows)
            log(f"  {ch}: {len(rows)} сирих постів")
        # Вікно сховища, не весь сирий шар. Сире лежить із листопада 2025,
        # опубліковане сховище починається з 2026-04-18 — і це рішення
        # оператора (аудит 3 вересня 2026): архів до цієї дати нічого не дає
        # свіжим даним, а жар цілей від нього зсувається. Без запобіжника
        # перебудова 9 вересня 2026 мовчки створила 160 діб, яких у
        # репозиторії нема, і жар порахувався разом із ними.
        first = st.dates()
        if first and not a.all_dates:
            first = first[0]
            n0 = len(posts)
            posts = [p for p in posts
                     if datetime.fromisoformat(p["date"]).astimezone(ST.MSK)
                     .strftime("%Y-%m-%d") >= first]
            log(f"  вікно сховища з {first}: {len(posts)} постів "
                f"(відкинуто {n0 - len(posts)}; --all-dates, щоб узяти всі)")
        n = st.build(posts, cfg, gaz, log=log, targets=targets)
        log(f"\nрозібрано подій: {n}")
        aftermath(st, gaz, targets, log)
        return 0

    since = parse_since(a.since)
    log(f"збір із {since:%Y-%m-%d %H:%M} UTC")
    posts = S.scrape_many(a.channels, since, None, "data", log=log)
    log(f"постів у вікні: {len(posts)}")
    # Канал наслідків — окремо: у сховище подій він не йде. Збій його збору
    # не має зупиняти основний конвеєр.
    try:
        S.scrape_many(AFTERMATH, since, None, "data", log=log)
    except Exception as e:                      # noqa: BLE001
        log(f"  ! канал наслідків не зібрано: {e}")
    if posts:
        n = st.build(posts, cfg, gaz, log=log, targets=targets)
        log(f"\nоновлено подій: {n}")
    else:
        log("нових постів підльоту нема")
    aftermath(st, gaz, targets, log)
    return 0


def aftermath(st, gaz, targets, log):
    """Шар наслідків — щоразу цілком із сирого каналу (кілька секунд): так
    щогодинний прогін і `--rebuild` дають те саме побайтово. Лише ночі
    вікна сховища, як і події."""
    raw = AF.load_raw(Path("."))
    if not raw:
        return
    first = st.dates()
    since = first[0] if first else None
    # Шар будується щоразу з усього сирого, тож пост, на якому розбір
    # падає, валив би КОЖЕН прогін, доки не випаде з вікна збору, — без
    # сайту й коміту даних. Падіння тут лишає вчорашній шар і кричить у лог.
    try:
        incs = AF.build(raw, gaz, targets)
        ch = AF.write(incs, Path("."), since=since)
    except Exception as e:                       # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(f"::warning::шар наслідків не перебудовано: {e!r}")
        return
    shown = sum(1 for x in incs if x["hit"] and (not since or x["night"] >= since))
    log(f"наслідки: інцидентів {len(incs)}, на карту {shown}, змінено файлів ночей {ch}")


if __name__ == "__main__":
    sys.exit(main())
