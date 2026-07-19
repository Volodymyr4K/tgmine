"""CLI: tgmine scrape | extract | analyze | run"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import analyze as A
from . import extract as E
from . import dedupe as D
from . import scrape as S


def parse_date(s: str) -> datetime:
    if s == "today":
        return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    if s.endswith("d"):  # "30d" = 30 днів тому
        return datetime.now(timezone.utc) - timedelta(days=int(s[:-1]))
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def mirror_groups(specs: list[str]) -> dict[str, str]:
    """--mirror a,b  ->  {a: "a", b: "a"} — канали одного кластера = один голос."""
    g = {}
    for spec in specs:
        chans = [c.strip() for c in spec.split(",") if c.strip()]
        for c in chans:
            g[c] = chans[0]
    return g


def load_posts(path: Path) -> list[dict]:
    if path.suffix == ".jsonl":
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv=None):
    ap = argparse.ArgumentParser("tgmine", description="Скрапінг і аналіз Telegram-каналів")
    ap.add_argument("--data", default="data", help="каталог кешу (default: data)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("scrape", help="зібрати пости каналів")
    sc.add_argument("channels", nargs="+", help="@name / t.me/name / name")
    sc.add_argument("--since", default="30d", help="ISO-дата, або 30d, або today")
    sc.add_argument("--until", default=None)
    sc.add_argument("-o", "--out", default="posts.json")

    ex = sub.add_parser("extract", help="теги + сутності + events.csv")
    ex.add_argument("posts")
    ex.add_argument("-c", "--config", required=True)
    ex.add_argument("--dedupe", action="store_true",
                    help="схлопнути крос-канальні дублікати в події")
    ex.add_argument("--mirror", action="append", default=[],
                    help="канали-дзеркала як один голос: --mirror a,b")
    ex.add_argument("--filter", default=None, help="лишити тільки пости з цим тегом")
    ex.add_argument("-o", "--out", default="enriched.json")
    ex.add_argument("--events", default="events.csv")

    an = sub.add_parser("analyze", help="звіт")
    an.add_argument("posts", help="enriched.json з кроку extract")
    an.add_argument("-c", "--config", required=True)
    an.add_argument("--tz", type=int, default=0, help="зсув годин для часової осі")
    an.add_argument("--focus", default=None, help="тег у фокусі (default: segment_by)")
    an.add_argument("-o", "--out", default=None, help="записати звіт у файл")

    rn = sub.add_parser("run", help="scrape + extract + analyze одним махом")
    rn.add_argument("channels", nargs="+")
    rn.add_argument("-c", "--config", required=True)
    rn.add_argument("--dedupe", action="store_true",
                    help="схлопнути крос-канальні дублікати в події")
    rn.add_argument("--mirror", action="append", default=[],
                    help="канали-дзеркала як один голос: --mirror a,b")
    rn.add_argument("--since", default="30d")
    rn.add_argument("--until", default=None)
    rn.add_argument("--tz", type=int, default=0)
    rn.add_argument("--filter", default=None)
    rn.add_argument("--outdir", default="out")

    a = ap.parse_args(argv)

    if a.cmd == "scrape":
        posts = S.scrape_many(a.channels, parse_date(a.since),
                              parse_date(a.until) if a.until else None, a.data)
        E.write(posts, a.out)
        print(f"\n{len(posts)} постів -> {a.out}")

    elif a.cmd == "extract":
        cfg = E.Config.load(a.config)
        posts = load_posts(Path(a.posts))
        if a.dedupe:
            raw = len(posts)
            posts = D.cluster(posts, groups=mirror_groups(a.mirror))
            D.report([0] * raw, posts)
        posts = E.enrich(posts, cfg)
        if a.filter:
            posts = [p for p in posts if a.filter in p["tags"]]
        E.write(posts, a.out)
        events = E.to_events(posts, cfg)
        E.write(events, a.events)
        print(f"{len(posts)} постів -> {a.out}\n{len(events)} подій -> {a.events}")

    elif a.cmd == "analyze":
        cfg = E.Config.load(a.config)
        posts = load_posts(Path(a.posts))
        buf = []
        A.report(posts, cfg, a.tz, a.focus, out=lambda s="": (buf.append(s), print(s))[1])
        if a.out:
            Path(a.out).write_text("\n".join(map(str, buf)), encoding="utf-8")
            print(f"\nзвіт -> {a.out}")

    elif a.cmd == "run":
        out = Path(a.outdir)
        out.mkdir(parents=True, exist_ok=True)
        cfg = E.Config.load(a.config)
        posts = S.scrape_many(a.channels, parse_date(a.since),
                              parse_date(a.until) if a.until else None, a.data)
        if len({p["channel"] for p in posts}) > 1:
            ov = D.overlap_matrix(posts)
            hi = [(k, v) for k, v in ov.items() if v > 0.3]
            if hi:
                print("\n! канали дублюють одне одного:")
                for (x, y), v in sorted(hi, key=lambda kv: -kv[1]):
                    print(f"    {v*100:5.1f}% постів {x} є і в {y}")
                if not a.dedupe:
                    print("  -> статистика буде подвоєна; додай --dedupe")
        if a.dedupe:
            raw = len(posts)
            posts = D.cluster(posts, groups=mirror_groups(a.mirror))
            D.report([0] * raw, posts)
        posts = E.enrich(posts, cfg)
        E.write(posts, out / "enriched.json")
        sel = [p for p in posts if not a.filter or a.filter in p["tags"]]
        E.write(sel, out / "posts.csv",
                ["channel", "id", "date", "url", "views", "tags", "segment", "text"])
        E.write(E.to_events(sel, cfg), out / "events.csv")
        buf = []
        A.report(posts, cfg, a.tz, a.filter, out=lambda s="": (buf.append(s), print(s))[1])
        (out / "report.txt").write_text("\n".join(map(str, buf)), encoding="utf-8")
        print(f"\n-> {out}/  (enriched.json, posts.csv, events.csv, report.txt)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
