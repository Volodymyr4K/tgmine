#!/usr/bin/env python3
"""Відновлення власного тексту відповідей у сирому шарі (вада скрапера до
22.09.2026: для відповіді зберігалась цитата батька, див. `scrape._parse`).

  python3 tools/repair_replies.py --report r.json            # пробний прогін
  python3 tools/repair_replies.py --report r.json --apply    # записати в data/

Для кожної відповіді без `reply_text` стягується сторінка t.me/s/ з цим
постом і розбирається ВИПРАВЛЕНИМ `_parse`. Рядок міняється, лише якщо:
  * пост знайдено і `reply_to` збігся зі збереженим;
  * збережений текст — це саме цитата батька (збігається з `reply_text`
    після нормалізації) — тобто вада підтверджена на цьому рядку.
Решта (пост видалено, текст уже власний, розбіжність) — лише у звіт.
Змінюються тільки поля `text` і `reply_text`; `date`, `views` та інше — ні.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tgmine import dedupe as D, scrape as S  # noqa: E402
import sync  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--channels", nargs="*", default=sync.CHANNELS)
    ap.add_argument("--report", required=True, help="куди писати звіт (поза репо)")
    a = ap.parse_args()
    report = {}
    for ch in a.channels:
        cache = S.Cache(ROOT / "data", ch)
        todo = sorted((i for i, p in cache.posts.items()
                       if p.get("reply_to") and "reply_text" not in p), reverse=True)
        fetched, stats, changed = {}, {"усього": len(todo)}, []
        for i in todo:
            if i not in fetched:
                soup = S._get(ch, i + 1)
                for q in S._parse(soup, ch):
                    fetched[q["id"]] = q
                time.sleep(0.7)
            old, new = cache.posts[i], fetched.get(i)
            if new is None:
                stats["не віддано"] = stats.get("не віддано", 0) + 1
                continue
            if new.get("reply_to") != old.get("reply_to"):
                stats["інший reply_to"] = stats.get("інший reply_to", 0) + 1
                continue
            if D.norm(old["text"]) == D.norm(new["text"]):
                stats["текст уже свій"] = stats.get("текст уже свій", 0) + 1
                old["reply_text"] = new.get("reply_text")
                changed.append(i)
                continue
            if D.norm(old["text"]) != D.norm(new.get("reply_text") or ""):
                stats["не цитата батька"] = stats.get("не цитата батька", 0) + 1
                report.setdefault(ch + ":розбіжності", []).append(
                    {"id": i, "stored": old["text"][:200], "own": new["text"][:200],
                     "quote": (new.get("reply_text") or "")[:200]})
                continue
            stats["відновлено"] = stats.get("відновлено", 0) + 1
            report.setdefault(ch + ":приклади", []).append(
                {"id": i, "було": old["text"][:160], "стало": new["text"][:160]})
            old["text"], old["reply_text"] = new["text"], new.get("reply_text")
            changed.append(i)
        report[ch] = stats
        print(ch, stats, flush=True)
        if a.apply and changed:
            cache.flush()
    out = Path(a.report)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("звіт ->", out, "(записано в data/)" if a.apply else "(пробний прогін, data/ не змінено)")


if __name__ == "__main__":
    main()
