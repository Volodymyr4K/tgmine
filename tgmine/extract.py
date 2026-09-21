"""Витяг тегів, сутностей і піднапрямків із текстів постів — керується YAML-конфігом.

Ключова ідея: жодних хардкоджених областей чи типів зброї. Конфіг описує
предметну область, код лишається універсальним.
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .geocode import DISTRICT_AFTER, GENERIC as _GENERIC_WORDS, LAUNCH_WORD


@dataclass
class Config:
    name: str = "default"
    tags: dict[str, re.Pattern] = field(default_factory=dict)
    entities: dict[str, dict[str, re.Pattern]] = field(default_factory=dict)
    modifiers: dict[str, re.Pattern] = field(default_factory=dict)
    modifier_scope: int = 30
    source_markers: re.Pattern | None = None
    segment_by: str | None = None      # тег, чий блок вирізати (напр. "КАБ")
    block_break: re.Pattern | None = None
    header_pattern: re.Pattern | None = None   # "- Запорізька область:" у зведенні
    anaphora: re.Pattern | None = None         # "на область" — відсилка до заголовка
    freeform: dict[str, dict] = field(default_factory=dict)  # витяг за шаблоном
    noise: re.Pattern | None = None                          # збори, реклама, вербування
    geo: dict[str, tuple[float, float]] = field(default_factory=dict)
    geo_aliases: dict[str, tuple[float, float]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        f = re.IGNORECASE

        def rx(pats):
            return re.compile("|".join(f"(?:{p})" for p in pats), f)

        def rx_word(pats):
            """Те саме, але кожна гілка прив'язана до початку слова.

            Без цього патерн назви ловив середину чужого слова, і пост діставав
            сутність, якої в ньому немає. Виміряно на корпусі: 1720 таких збігів
            у 15 патернах. Найгірші — "Орск\\b" у «При|морск», «Углег|орск»,
            «Железног|орск» (413 разів, Оренбурзька за 1500 км) і "Казан\\w*" у
            звичайному слові «у|казан|иям» (99). Ще: «Ново|московск» (Тульська)
            → Московська, «Северо|донецк» (Луганщина) → ТОТ_Донецьк.

            Робиться в коді, а не 100 правками в YAML: інакше праву межу легко
            забути в кожній наступній доданій області.

            Свідомо ТІЛЬКИ для сутностей, не для тегів. Для тегів той самий
            прийом виправив би 8 постів (тег «небезпека» ловив «без|опасность» —
            протилежний сенс), але зламав би 2: у джерелі трапляється друкарська
            помилка «близлежащиетревога» без пробілу, і межа втратила б
            справжню тривогу.
            """
            return re.compile("|".join(rf"\b(?:{p})" for p in pats), f)

        cfg = cls(name=raw.get("name", "default"))
        cfg.tags = {k: rx(v) for k, v in (raw.get("tags") or {}).items()}
        for etype, values in (raw.get("entities") or {}).items():
            cfg.entities[etype] = {k: rx_word(v) for k, v in values.items()}
        cfg.modifiers = {k: rx(v) for k, v in (raw.get("modifiers") or {}).items()}
        cfg.modifier_scope = raw.get("modifier_scope", 30)
        if raw.get("source_markers"):
            cfg.source_markers = rx(raw["source_markers"])
        cfg.segment_by = raw.get("segment_by")
        if raw.get("block_break"):
            cfg.block_break = rx(raw["block_break"])
        if raw.get("header_pattern"):
            cfg.header_pattern = re.compile(raw["header_pattern"][0] if isinstance(
                raw["header_pattern"], list) else raw["header_pattern"], f)
        if raw.get("anaphora"):
            cfg.anaphora = rx(raw["anaphora"])
        for etype, spec in (raw.get("freeform") or {}).items():
            cfg.freeform[etype] = {
                "pattern": re.compile(spec["pattern"]),
                "stoplist": {w.lower() for w in spec.get("stoplist", [])},
                "lines": spec.get("lines"),        # брати лише перші N рядків
                "min_len": spec.get("min_len", 3),
            }
        if raw.get("noise"):
            cfg.noise = rx(raw["noise"])
        cfg.geo = {k: tuple(v) for k, v in (raw.get("geo") or {}).items()}
        cfg.geo_aliases = {k.lower(): tuple(v)
                           for k, v in (raw.get("geo_aliases") or {}).items()}
        return cfg


def segment(text: str, cfg: Config) -> str:
    """Вирізає блок навколо цільового тегу — щоб не хапати сутності з інших блоків.

    Пости-зведення часто містять кілька загроз; без цього КАБ-рядок змішується
    з рядком про БпЛА і географія псується.
    """
    if not cfg.segment_by or cfg.segment_by not in cfg.tags:
        return text
    target, brk = cfg.tags[cfg.segment_by], cfg.block_break
    buf, take = [], False
    for line in (l.strip() for l in text.split("\n")):
        if target.search(line):
            take = True
            buf.append(line)
            continue
        if take:
            if brk and brk.match(line):
                break
            buf.append(line)
    return " ".join(x for x in buf if x) if buf else text


def tags_of(text: str, cfg: Config) -> set[str]:
    return {k for k, rx in cfg.tags.items() if rx.search(text)}


def _modifier(seg: str, m: re.Match, lo: int, cfg: Config) -> str | None:
    """Модифікатор перед сутністю ("на північ Харківщини") або після ("зі сходу").

    `lo` — кінець попередньої сутності: не дає модифікатору перетекти через
    "та" на наступну ("північний схід Харківщини та Донеччину").
    """
    before = seg[max(lo, m.start() - cfg.modifier_scope):m.start()]
    hits = _mods(before, cfg)
    if hits:
        return hits[-1][2]          # найближчий до сутності
    tail = re.split(r"[,.!;]| та | і ", seg[m.end():m.end() + cfg.modifier_scope])[0]
    hits = _mods(tail, cfg)
    return hits[0][2] if hits else None


def _mods(s: str, cfg: Config) -> list[tuple[int, int, str]]:
    """Збіги модифікаторів, без вкладених.

    "північний схід" матчиться і як складений, і як простий "схід"; складений
    довший і поглинає простий, інакше піднапрямок вироджується.
    """
    raw = [(mm.start(), mm.end(), name)
           for name, rx in cfg.modifiers.items() for mm in rx.finditer(s)]
    keep = [h for h in raw
            if not any(o is not h and o[0] <= h[0] and h[1] <= o[1] and
                       (o[1] - o[0]) > (h[1] - h[0]) for o in raw)]
    return sorted(keep)


def entities_of(text: str, cfg: Config) -> list[dict]:
    """[{type, value, modifier, pos}] — усі згадані сутності з піднапрямками."""
    seg = segment(text, cfg)
    src_spans = ([m.span() for m in cfg.source_markers.finditer(seg)]
                 if cfg.source_markers else [])
    out, seen = [], set()
    for etype, values in cfg.entities.items():
        spans = sorted(m.end() for rx in values.values() for m in rx.finditer(seg))
        for value, rx in values.items():
            for m in rx.finditer(seg):
                if any(s <= m.start() < e for s, e in src_spans):
                    continue          # це джерело, не ціль
                lo = max((e for e in spans if e <= m.start()), default=0)
                mod = _modifier(seg, m, lo, cfg)
                key = (etype, value, mod)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"type": etype, "value": value, "match": m.group(0),
                            "modifier": mod, "pos": m.start()})
    return sorted(out, key=lambda e: e["pos"])


#: Прикметник у називному/непрямому відмінку — для розпізнавання складених назв.
_ADJ_WORD = re.compile(r"(?:ая|яя|ый|ий|ой|ое|ее|ые|ие|ую|юю|ого|его|ому|ему|ым|им|ых|их)$", re.I)
#: Прикметник назви області: основа «-ск-/-цк-» («Курская», «Брянской»).
_REGION_ADJ = re.compile(r"(?:ск|цк)(?:ий|ая|ое|ие|ой|ую|ого|ому|ом|ою|их|им|ими|ых|ым|ей)$", re.I)


def freeform_of(text: str, cfg: Config) -> list[dict]:
    """Сутності, яких не перелічиш у конфізі — напр. сотні населених пунктів.

    Бере збіги за шаблоном (зазвичай — слова з великої літери), відкидає стоплист,
    службові слова й усе, що вже впізнано як тег або відома сутність.
    """
    out, seen = [], set()
    for etype, spec in cfg.freeform.items():
        scope = text if not spec["lines"] else "\n".join(
            text.split("\n")[:spec["lines"]])
        # Спани вже впізнаного — порівнюємо позиції, а не рядки: "Запорожская"
        # всередині "Запорожская область" належить регіону й не є окремим НП.
        taken = [m.span() for rx in cfg.tags.values() for m in rx.finditer(scope)]
        # Збіг, після якого стоїть «район/округ», «зайнятим» НЕ вважається.
        #
        # Маркери областей у конфізі — це назви міст, і прикметник району від
        # того самого міста вони ловлять теж: «Россош\w*» бере «Россошанский»,
        # «Камышин\w*» — «Камышинский», «Валуй\w*» — «Валуйский». Слово
        # вважалось упізнаним як ознака ОБЛАСТІ, топонім не створювався взагалі,
        # і подія падала на центр області: Россошанський район за 171 км від
        # Воронежа, Морозовський за 195 від Ростова, Камишинський за 182 від
        # Волгограда. Заміряно у вікні сховища: 8257 таких збігів, 3582 події
        # на центрі області, у 2236 зсув понад 30 км (медіана 109).
        #
        # Сутність-регіон при цьому ЛИШАЄТЬСЯ. Звузити патерни в конфізі не
        # можна: у 1680 із 3582 постів область упізнана САМЕ цим прикметником,
        # і без нього вони лишились би без області взагалі.
        taken += [m.span() for vals in cfg.entities.values()
                  for rx in vals.values() for m in rx.finditer(scope)
                  if not DISTRICT_AFTER.match(scope[m.end():])]
        def add(val, pos):
            low = val.lower()
            if len(val) < spec["min_len"] or low in spec["stoplist"] or low in seen:
                return
            out.append({"type": etype, "value": val, "match": val,
                        "modifier": None, "pos": pos})

        for m in spec["pattern"].finditer(scope):
            val = m.group(0).strip(" ,.:;!?-")
            if not any(a < m.end() and m.start() < b for a, b in taken):
                add(val, m.start())
                continue
            # Збіг із двох слів зачепив відому сутність — друге слово може бути
            # самостійним топонімом, і викидати його разом із першим не можна.
            # «Север Крыма Джанкойский район»: коли розбір почав перестрибувати
            # напрямки світу, вікно зсунулось на «Крыма Джанкойский», «Крыма» —
            # маркер області, і збіг відкидався цілком — разом із районом, де
            # усе відбувалось. Та сама вада діяла й раніше для будь-якої пари
            # «маркер області + назва». Слово, що саме нічого не зачіпає,
            # береться окремо.
            #
            # Але пара буває й СКЛАДЕНОЮ назвою, яку різати не можна. Правило
            # виведене з даних (перша версія без нього дала «Геническая Горка»
            # -> село Gorka, «Новая Москва» -> Novaya):
            #   прикметник ПЕРЕД назвою — складена назва («Геническая Горка»);
            #   маркер ПІСЛЯ місця, і це назва області чи скорочення («Поныри
            #   Курская», «Никольское Бгд», «Ялта Крым») — різати;
            #   місто-іменник після прикметника («Новая Москва») — не різати.
            words = list(re.finditer(r"\S+", m.group(0)))
            if len(words) == 2:
                (w1, w2) = words
                hit1 = any(a < m.start() + w1.end() and m.start() + w1.start() < b
                           for a, b in taken)
                if hit1:
                    compound = bool(_ADJ_WORD.search(w1.group(0)))
                else:
                    marker = w2.group(0).strip(" ,.:;!?-")
                    region_word = (bool(_REGION_ADJ.search(marker)) or len(marker) <= 4)
                    compound = not region_word and bool(_ADJ_WORD.search(w1.group(0)))
                if compound:
                    continue
            for w in words:
                a0, b0 = m.start() + w.start(), m.start() + w.end()
                if any(a < b0 and a0 < b for a, b in taken):
                    continue
                val = w.group(0).strip(" ,.:;!?-")
                if val.lower() in _GENERIC_WORDS:
                    continue      # «Порт Крым» -> не село Port
                add(val, a0)
    return out


#: Назва одразу після прийменника джерела: «от Одессы», «из-под Чернигова»,
#: «с района Днепра». Лише назва з великої — «пуски с авиации» сюди не йде.
#: БЕЗ re.I: з ним [А-ЯЁ] ловив і малі літери, і «Из-под под Чернигова»
#: (помилка в тексті) давало назву «под» -> село Pody. Регістр прийменника
#: задано явно.
_SRC_NAME = re.compile(
    r"(?:\b[Оо]т|\b[Ии]з-под|\b[Сс]о\s+стороны|\b[Сс]\s+района|\b[Ии]з\s+района"
    r"|\b[Ии]з|\b[Сс]о?)"
    r"\s+(?:г\.\s*|города\s+)?(?P<n>[А-ЯЁ][а-яё]+(?:-[А-ЯЁа-яё]+)*)")


def launch_sources(text: str, known: list[dict]) -> list[dict]:
    """Джерела пуску з УСІХ рядків поста — лише для постів про пуск.

    Звичайний розбір (freeform) читає перший рядок і має стоп-список, у якому
    з першого коміту стоять «Одессы» й «Николаева»: для фіксації «от Одессы»
    — джерело, яке НЕ є місцем події. Для пуску навпаки, і через це «Пуски
    БПЛА от Одессы» не мали жодної сутності, а оглядові пости («Ещё пуски: /
    От Чернигов в сторону Брянской / От Сумы в сторону Курской») — джерела,
    бо воно в другому рядку. Тут стоп-список свідомо не діє: назву після «от»
    у пості про пуск вибрано граматикою, а не шаблоном «слово з великої».

    Пропускається все, що вже впізнано на тій самій позиції.
    """
    if not LAUNCH_WORD.search(text):
        return []
    taken = [(e["pos"], e["pos"] + len(str(e.get("match") or e["value"])))
             for e in known if e.get("pos") is not None]
    out = []
    for m in _SRC_NAME.finditer(text):
        a, b = m.span("n")
        if any(x < b and a < y for x, y in taken):
            continue
        out.append({"type": "нп", "value": m.group("n"), "match": m.group("n"),
                    "modifier": None, "pos": a, "src": True})
        taken.append((a, b))
    return out


def header_entity(text: str, cfg: Config) -> dict | None:
    """Сутність із заголовка секції для анафори типу "КАБи на область".

    Зведення часто мають структуру "- Запорізька область:\n <загрози>";
    у самому рядку загрози назви немає, лише відсилка.
    """
    if not (cfg.header_pattern and cfg.segment_by):
        return None
    target = cfg.tags.get(cfg.segment_by)
    current = None
    for line in (l.strip() for l in text.split("\n")):
        h = cfg.header_pattern.match(line)
        if h:
            head = h.group(1) if h.groups() else h.group(0)
            for etype, values in cfg.entities.items():
                for value, rx in values.items():
                    if rx.search(head):
                        current = {"type": etype, "value": value,
                                   "modifier": None, "pos": 0}
                        break
                if current:
                    break
        if target and target.search(line) and current:
            return current
    return current


def enrich(posts: list[dict], cfg: Config) -> list[dict]:
    for p in posts:
        p["tags"] = sorted(tags_of(p["text"], cfg))
        p["entities"] = entities_of(p["text"], cfg)
        if not p["entities"] and cfg.anaphora and cfg.anaphora.search(segment(p["text"], cfg)):
            he = header_entity(p["text"], cfg)
            if he:
                p["entities"] = [he]
        if cfg.freeform:
            p["entities"] = p["entities"] + freeform_of(p["text"], cfg)
        p["entities"] = p["entities"] + launch_sources(p["text"], p["entities"])
        p["segment"] = segment(p["text"], cfg)
    return posts


def to_events(posts: list[dict], cfg: Config) -> list[dict]:
    """Розгортає пости в події [t, lat, lon, type, value, text, source].

    Один пост із двома областями дає дві події. Формат навмисне збігається
    з тим, що потрібен плеєру-карті.
    """
    events = []
    for p in posts:
        for e in p.get("entities", []):
            lat, lon = cfg.geo.get(e["value"], (None, None))
            events.append({
                "t": p["date"],
                "channel": p["channel"],
                "post_id": p["id"],
                "type": e["type"],
                "value": e["value"],
                "modifier": e["modifier"] or "",
                "tags": "|".join(p.get("tags", [])),
                "lat": lat,
                "lon": lon,
                "text": p.get("segment", p["text"]).replace("\n", " "),
                "source": p["url"],
            })
    return sorted(events, key=lambda e: e["t"])


def write(rows: list[dict], path: str | Path, fields: list[str] | None = None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".json":
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = fields or list(rows[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (v if not isinstance(v, (list, set)) else "|".join(map(str, v)))
                        for k, v in r.items()})
