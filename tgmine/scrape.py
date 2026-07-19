"""Скрапер публічних Telegram-каналів через веб-превʼю t.me/s/<channel>.

Інкрементальний: тримає кеш у data/<channel>.jsonl, при повторному запуску
доваантажує лише нові пости. Без API-ключів і логіну.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from .atomic import atomic_write

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) tgmine/0.1"}
BASE = "https://t.me/s/{channel}"


@dataclass
class Post:
    channel: str
    id: int
    date: str
    url: str
    views: str
    text: str
    reply_to: str | None = None
    forwarded_from: str | None = None
    has_media: bool = False


def channel_name(ref: str) -> str:
    """Приймає @name, name, t.me/name, https://t.me/s/name — віддає name."""
    ref = ref.strip()
    if ref.startswith("@"):
        return ref[1:]
    if "t.me" in ref:
        parts = [p for p in urlparse(ref).path.split("/") if p and p != "s"]
        if parts:
            return parts[0]
    return ref


class Cache:
    def __init__(self, root: Path, channel: str):
        self.path = Path(root) / f"{channel}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.posts: dict[int, dict] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    p = json.loads(line)
                    self.posts[p["id"]] = p


    @property
    def min_id(self) -> int | None:
        return min(self.posts) if self.posts else None

    def add(self, posts: list[dict]) -> int:
        new = [p for p in posts if p["id"] not in self.posts]
        for p in new:
            self.posts[p["id"]] = p
        return len(new)

    def flush(self) -> None:
        # atomic_write, а не path.open("w"): цей файл не відновлюється з мережі,
        # а звичайне відкриття на запис ріже його ще до того, як щось записано.
        with atomic_write(self.path) as f:
            for _, p in sorted(self.posts.items()):
                f.write(json.dumps(p, ensure_ascii=False) + "\n")


def _get(channel: str, before: int | None, retries: int = 4) -> BeautifulSoup:
    params = {"before": before} if before else None
    delay = 2.0
    for attempt in range(retries):
        try:
            r = requests.get(BASE.format(channel=channel), headers=UA,
                             params=params, timeout=30)
            if r.status_code == 429:
                wait = float(r.headers.get("Retry-After", delay))
                time.sleep(wait)
                delay *= 2
                continue
            r.raise_for_status()
            return BeautifulSoup(r.text, "html.parser")
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


def _parse(soup: BeautifulSoup, channel: str) -> list[dict]:
    out = []
    for w in soup.select(".tgme_widget_message"):
        post = w.get("data-post")
        if not post:
            continue
        t = w.select_one(".tgme_widget_message_date time")
        body = w.select_one(".tgme_widget_message_text")
        views = w.select_one(".tgme_widget_message_views")
        reply = w.select_one(".tgme_widget_message_reply")
        fwd = w.select_one(".tgme_widget_message_forwarded_from a")
        mid = int(post.split("/")[1])
        out.append(asdict(Post(
            channel=channel,
            id=mid,
            date=datetime.fromisoformat(t["datetime"]).astimezone(timezone.utc).isoformat()
            if t else "",
            url=f"https://t.me/{channel}/{mid}",
            views=views.get_text(strip=True) if views else "",
            text=body.get_text("\n", strip=True) if body else "",
            reply_to=reply.get("href") if reply and reply.get("href") else None,
            forwarded_from=fwd.get_text(strip=True) if fwd else None,
            has_media=bool(w.select_one(
                ".tgme_widget_message_photo, .tgme_widget_message_video, "
                ".tgme_widget_message_document, .tgme_widget_message_voice")),
        )))
    return sorted(out, key=lambda p: p["id"])


def scrape(channel_ref: str, since: datetime, until: datetime | None = None,
           data_dir: str | Path = "data", polite: float = 0.6,
           max_pages: int = 2000, log=print) -> list[dict]:
    """Тягне пости каналу до `since`. Повертає пости в межах [since, until)."""
    ch = channel_name(channel_ref)
    cache = Cache(Path(data_dir), ch)
    known_floor = cache.min_id      # нижче цього кеш порожній
    before, pages, added = None, 0, 0

    while pages < max_pages:
        posts = _parse(_get(ch, before), ch)
        if not posts:
            break
        fresh = cache.add(posts)
        added += fresh
        oldest_id = min(p["id"] for p in posts)
        dates = [datetime.fromisoformat(p["date"]) for p in posts if p["date"]]
        oldest_dt = min(dates) if dates else None
        pages += 1
        log(f"  [{ch}] стор.{pages}: до id={oldest_id} {oldest_dt:%Y-%m-%d %H:%M}"
            f"  (+{added} нових)" if oldest_dt else f"  [{ch}] стор.{pages}")

        if oldest_dt and oldest_dt < since:
            break
        # Сторінка цілком із кешу, а since ще нижче. Обхід завжди йде згори вниз,
        # тож кеш суцільний на [min_id, max_id] — можна стрибнути одразу під дно
        # замість того, щоб перегортати десятки вже відомих сторінок.
        if fresh == 0 and known_floor is not None and oldest_id > known_floor:
            log(f"  [{ch}] кеш покриває до id={known_floor}, стрибок під дно")
            before = known_floor
            known_floor = None
            time.sleep(polite)
            continue
        before = oldest_id
        time.sleep(polite)

    cache.flush()
    return window(list(cache.posts.values()), since, until)


def window(posts: list[dict], since: datetime, until: datetime | None) -> list[dict]:
    out = []
    for p in posts:
        if not p.get("date"):
            continue
        d = datetime.fromisoformat(p["date"])
        if d >= since and (until is None or d < until):
            out.append(p)
    return sorted(out, key=lambda p: (p["channel"], p["id"]))


def scrape_many(refs: list[str], since: datetime, until: datetime | None = None,
                data_dir: str | Path = "data", log=print) -> list[dict]:
    all_posts = []
    for ref in refs:
        log(f"канал {channel_name(ref)}…")
        all_posts.extend(scrape(ref, since, until, data_dir, log=log))
    return sorted(all_posts, key=lambda p: p["date"])
