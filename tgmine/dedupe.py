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





# ---------------------------------------------------------------------------
# Нечіткі дублі ДЗЕРКАЛА. Точний збіг тексту ловить 59% постів kupolrussia,
# але дзеркало переписує не буквально: викидає рядок загрози («Опасность по
# БПЛА») або міняє його на область. Заміряно на 15 добах: 1220 пар, де
# жодна сторона не позначена, — 8.3% усіх «унікальних» подій, ≈81 на добу,
# тобто добові підсумки по областях роздуті на ~8%, а один голос рахується
# двічі. Точковий шар це майже не чіпає (59 із 1220 — точки).
#
# Правило навмисно вузьке: ТІЛЬКИ пара дзеркал, ±180 с (медіана лагу 23 с,
# 90-й перцентиль 45), той самий набір топонімів (Жаккар ≥ 0.6 або один
# набір вкладений в інший), та сама область поста, і типи або однакові, або
# один із них «інше» — бо саме рядок загрози дзеркало й губить. Різні типи
# (тривога проти відбою) з тими самими назвами — це два різні повідомлення,
# і вони не зливаються. На 20 випадкових злиттях, прочитаних очима, хибних 0.
MIRRORS = {frozenset(("lpr1_treugolnik", "kupolrussia"))}
MIRROR_WINDOW_S = 180
TOPO_STOP = {"области", "область", "республика", "край", "района", "район",
             "близлежащие", "тревога", "опасность", "отбой", "бпла", "ракетная",
             "внимание", "меры", "безопасности", "фиксация", "фиксации",
             "повторно", "сохраняется", "хорнет", "удар", "ударных", "группа",
             "городской", "округ", "срочно", "принять"}
# Слово з великої на початку речення («Переходим», «Соблюдаем») теж потрапляє в
# ключ і ЗМЕНШУЄ збіг — тобто заважає лише в бік обережності. Розширити
# стоп-список дієсловами перевірено: −5 злиттів на 5823, не варте рядка.
TOPO = re.compile(r"[А-ЯЁ][а-яё\-]{3,}")


def topo_key(text: str) -> frozenset:
    """Назви з великої літери мінус службові слова — «про що» пост."""
    return frozenset(w.lower() for w in TOPO.findall(text or "")
                     if w.lower() not in TOPO_STOP)


def same_story(a: frozenset, b: frozenset) -> bool:
    if not a or not b:
        return False
    if a <= b or b <= a:
        return min(len(a), len(b)) >= 2 or a == b
    return len(a & b) / len(a | b) >= 0.6


def mirror_dups(posts: list[dict], kind_of, region_of) -> int:
    """Проставляє `_dup_of` нечітким дублям між каналами-дзеркалами.

    `posts` уже впорядковані за датою; ті, що вже мають `_dup_of`, минаються.
    Дублем стає МЕНШ інформативний пост: якщо типи різні, «інше» іде в дубль
    незалежно від того, хто перший (інакше загроза з пізнішого поста зникала
    б із унікальних; таких 3 на 1576). Якщо типи однакові — пізніший.
    Повертає кількість позначених.
    """
    idx = [i for i, p in enumerate(posts)
           if not p.get("_dup_of") and any(p["channel"] in m for m in MIRRORS)]
    times = [datetime.fromisoformat(posts[i]["date"]) for i in idx]
    keys = [topo_key(posts[i]["text"]) for i in idx]
    kinds = [kind_of(posts[i]) for i in idx]
    regs = [region_of(posts[i]) for i in idx]
    used = set()
    n = 0
    for a in range(len(idx)):
        if a in used or not keys[a]:
            continue
        pa = posts[idx[a]]
        for b in range(a + 1, len(idx)):
            if times[b] - times[a] > timedelta(seconds=MIRROR_WINDOW_S):
                break
            if b in used or not keys[b]:
                continue
            pb = posts[idx[b]]
            if pa["channel"] == pb["channel"]:
                continue
            if frozenset((pa["channel"], pb["channel"])) not in MIRRORS:
                continue
            if regs[a] != regs[b] or not same_story(keys[a], keys[b]):
                continue
            ka, kb = kinds[a], kinds[b]
            if ka != kb and "інше" not in (ka, kb):
                continue
            # хто дубль: менш інформативний, інакше пізніший
            dup, orig = (pa, pb) if (ka == "інше" and kb != "інше") else (pb, pa)
            dup["_dup_of"] = f"{orig['channel']}/{orig['id']}"
            used.add(a); used.add(b); n += 1
            break
    return n
