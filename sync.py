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
from tgmine import extract as E, geocode as GC, scrape as S, store as ST

CHANNELS = ["lpr1_treugolnik", "kupolrussia", "vrv_radar"]
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
              f"{'з коорд.':>10}{'апаратів':>10}")
        for r in rows:
            print(f"{r['date']:12}{r['all']:>8}{r['uniq']:>8}{r['points']:>10}"
                  f"{r['geo']:>10}{r['drones']:>10}")
        tot = {k: sum(r[k] for r in rows) for k in ("all", "uniq", "points", "drones")}
        print(f"{'РАЗОМ':12}{tot['all']:>8}{tot['uniq']:>8}{tot['points']:>10}"
              f"{'':>10}{tot['drones']:>10}")
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
        n = st.build(posts, cfg, gaz, log=log, targets=targets)
        log(f"\nрозібрано подій: {n}")
        return 0

    since = parse_since(a.since)
    log(f"збір із {since:%Y-%m-%d %H:%M} UTC")
    posts = S.scrape_many(a.channels, since, None, "data", log=log)
    log(f"постів у вікні: {len(posts)}")
    if not posts:
        log("нема чого оновлювати")
        return 0
    n = st.build(posts, cfg, gaz, log=log, targets=targets)
    log(f"\nоновлено подій: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
