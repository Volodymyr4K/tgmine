"""Сховище подій — єдине джерело правди для всіх видів.

Два шари:
  RAW      data/<channel>.jsonl      — сирі пости як їх віддав Telegram
  DERIVED  store/events/<дата>.jsonl — розібрані події: тип, сутності, координати

Розділення навмисне. Сирий шар незмінний і накопичується; похідний можна
перебудувати з нуля будь-коли (`rebuild`), коли зміниться конфіг, газетир чи
правила класифікації. Без цього кожна зміна регулярки означала б перезбір
даних із мережі.

Партиціювання по календарній даті (МСК): денний звіт і програвач ночі читають
один-два файли замість повного сканування.

Дублікати НЕ видаляються, а позначаються `dup_of`. Канали-дзеркала копіюють
одне одного, але сам факт «про це написали три канали» — це інформація про
підтвердженість, і викидати її не можна. Види вирішують самі: рахувати унікальні
події чи всі повідомлення.
"""
from __future__ import annotations

import collections
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import dedupe as D
from . import extract as E
from . import geocode as GC
from .atomic import atomic_write, write_text

MSK = timezone(timedelta(hours=3))

# Версія конвеєра. Якщо змінились правила розбору — підняти, і `sync` сам
# перебудує похідний шар, а не змішає старі й нові події в одному файлі.
# 9: near отримав tid — прив'язка до цілі за ідентифікатором, не за назвою.
# 11: near більше не ставиться на регіональні відкати координати.
PIPELINE_VERSION = 11

COUNT_N = re.compile(r"от\s+(\d+)\s*(?:БПЛА|бпла)", re.I)
GROUP_RE = re.compile(r"групп\w*", re.I)
TYPE_RE = re.compile(r"(Хорнет|Дартс|Лютый|Бабай|реактивн\w*)", re.I)

# КЛАСИФІКАЦІЯ — головне розрізнення в цих даних.
#
# «Тривога по Тульской области» і «Фиксация БПЛА над Коломной» — принципово
# різні повідомлення. Перше це адміністративне рішення по ЦІЛІЙ області, воно
# не означає, що дрон там є. Друге — конкретне спостереження в конкретній точці.
# Якщо малювати їх однаково, карта перетворюється на кашу однакових кружечків.
#
# Порядок важливий: перший збіг виграє, тому конкретніше йде раніше.
KIND = [
    ("вибух",    r"взрыв\w*|прилет\w*|попадани\w*"),
    ("збиття",   r"сбит\w*|уничтожен\w*"),
    ("ППО",      r"работа\s+ПВО|работает\s+ПВО|ПВО\s+по\s+БПЛА|работа\s+ВКС"),
    ("пуск",     r"\bпуск\w*"),
    ("фіксація", r"фиксаци\w*|пролет\w*|наблюда\w*|в\s+направлении|ударн\w*\s+БПЛА"),
    ("відбій",   r"отбой"),
    ("тривога",  r"тревога|опасность|внимание|угроза"),
]
KIND = [(k, re.compile(v, re.I)) for k, v in KIND]

# Спостереження в точці vs стан по площі
POINT_KINDS = {"вибух", "збиття", "ППО", "фіксація", "пуск"}

BORDER = [(52.15, 31.79), (51.60, 34.30), (50.45, 36.30), (49.60, 38.30),
          (48.60, 39.70), (47.30, 38.30), (46.60, 35.30), (45.30, 32.60)]

# Пріоритет цілі при прив'язці. Спостереження — це центр НП, а не координата
# удару, тому «поблизу» орієнтовне. Цінні точкові обʼєкти (НПЗ, склад БК,
# аеродром) важать більше за розмиту «військову зону», яких тисячі й майже
# кожен НП має одну поруч. Радіус теж різний: точковий обʼєкт — ширше вікно.
#: Спосіб геокодування, який дає не місце події, а «десь у цій області».
#: Такі координати не годяться для привʼязки до цілі: центр області може
#: випадково опинитись за кілька кілометрів від аеродрому, і тоді той збирає
#: всю нерозвʼязану статистику регіону.
REGIONAL_FALLBACK = {"centroid", "region", "region-snap"}

TARGET_PRIORITY = {
    "refinery": (0, 18), "defense_plant": (0, 15), "chemical": (0, 15),
    "ammo_depot": (1, 15), "airfield": (1, 18), "naval": (1, 15),
    "fuel_depot": (2, 15), "military_base": (3, 7), "range": (3, 7),
}


def target_id(o: dict) -> str:
    """Стабільний ідентифікатор цілі. Виводиться з обʼєкта, не зберігається.

    Раніше події посилались на ціль **назвою**, і це роздувало статистику:
    назви генеруються автоматично як «категорія + найближчий НП», тож на 4659
    обʼєктів припадає лише 1983 унікальні імені. `rank_targets` робив
    `hits.get(o["name"])` — і кожен із 12 різних складів БК під Севастополем
    отримував ПОВНІ 143 попадання замість своєї частки. Виміряно: 13197
    роздано проти 4694 реальних, роздування 2.81×.

    `osm` унікальний для всіх 4623 обʼєктів з OSM (перевірено, 0 дублів).
    Куровані записи (`refineries.py`, 36 шт) osm не мають — для них ключем
    служать координати, ті самі, на яких `fetch_targets` робить дедуп.

    Не поле у файлі, а функція — щоб не тримати ще один стан, який може
    розʼїхатись, і щоб наявний targets.json не потребував міграції.
    """
    if o.get("osm"):
        return o["osm"]
    return f"c:{o.get('cat','')}:{o.get('lat')}:{o.get('lon')}"


class TargetIndex:
    """Просторовий індекс по сітці 0.25°. Без нього прив'язка 6800 подій до
    4659 обʼєктів — це 31 млн haversine; із сіткою кожна подія дивиться лише
    у свою й сусідні комірки."""
    CELL = 0.25

    def __init__(self, objects):
        self.grid = collections.defaultdict(list)
        for o in objects:
            if o.get("lat") is None:
                continue
            k = (int(o["lat"] / self.CELL), int(o["lon"] / self.CELL))
            self.grid[k].append(o)

    def nearest(self, lat, lon):
        ci, cj = int(lat / self.CELL), int(lon / self.CELL)
        best = None
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for o in self.grid.get((ci + di, cj + dj), ()):
                    d = GC.haversine((lat, lon), (o["lat"], o["lon"]))
                    prio, rad = TARGET_PRIORITY.get(o["cat"], (4, 8))
                    if d > rad:
                        continue
                    # tid у ключі — щоб нічия розвʼязувалась однаково завжди.
                    # Без нього вигравав той, хто раніше у targets.json, а цей
                    # порядок перетасовує rank_targets (сортує за -imp). Сусідні
                    # будівлі одного обʼєкта (w1088757379/…80) на рівній відстані
                    # перекидались між запусками. Раніше це було непомітно, бо
                    # nearest() віддавав лише cat/name/km — у близнюків однакові.
                    score = (prio, round(d, 1), target_id(o))
                    if best is None or score < best[0]:
                        best = (score, o, d)
        if not best:
            return None
        _, o, d = best
        # tid — для звʼязку з targets.json, name — лише для показу людині.
        # Приєднуватись за name не можна: назви не унікальні (див. target_id).
        return {"tid": target_id(o), "cat": o["cat"], "name": o["name"],
                "km": round(d, 1)}


def strip_promo(text, cfg):
    """Прибирає рекламні РЯДКИ, а не весь пост.

    Пости часто змішані: «Движение по Крымскому мосту перекрыто. … Чтобы
    получать информацию, подписывайтесь на канал». Перекриття мосту — цінний
    сигнал (його закривають саме через загрозу), а фільтр по цілому посту
    викидав і його разом із рекламним хвостом.

    Повертає (очищений_текст, скільки_рядків_викинуто). Якщо після чистки
    не лишилось нічого змістовного — пост справді був суто рекламним.
    """
    if not cfg.noise:
        return text, 0
    lines = [l.strip() for l in re.split(r"\n|\s+/\s+", text) if l.strip()]
    keep = [l for l in lines if not cfg.noise.search(l)]
    return " / ".join(keep), len(lines) - len(keep)


# Заперечення, що стоїть БЕЗПОСЕРЕДНЬО перед тригером: «Ложные фиксации» — це
# спростування, канал каже «не зараховуйте», а класифікатор бачив «фиксации» й
# записував повноцінне точкове спостереження.
#
# Чому саме впритул, а не «є десь у тексті»: у корпусі 28 повідомлень зі словом
# «ложн*», але лише 3 — справжні спростування. Решта — довгі аналітичні зведення
# («#Сводка на утро…»), де слово трапляється мимохідь, а сама подія реальна.
# Виміряно: у спростуваннях відстань до тригера = 1 символ, у зведеннях —
# від 239 до 2275. Розділення чисте, поріг підбирати не довелось. Правило «є
# заперечення будь-де» зіпсувало б 11 коректно розібраних подій.
NEG_BEFORE = re.compile(r"(?:ложн|фейков|ошибочн)\w*\s*$", re.I)


def kind_of(text):
    for n, rx in KIND:
        # finditer, а не search: якщо перший збіг заперечений, а далі є
        # незаперечений — тип усе одно чинний.
        if any(not NEG_BEFORE.search(text[max(0, m.start() - 24):m.start()])
               for m in rx.finditer(text)):
            return n
    return "інше"


def depth_km(pt):
    return min(GC.haversine(pt, b) for b in BORDER)


class Store:
    def __init__(self, root="store"):
        self.root = Path(root)
        self.ev = self.root / "events"
        self.ev.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "state.json"
        self.state = (json.loads(self.state_path.read_text(encoding="utf-8"))
                      if self.state_path.exists() else
                      {"version": PIPELINE_VERSION, "channels": {}, "updated": None})

    # ---- читання ----------------------------------------------------------
    def dates(self):
        return sorted(p.stem for p in self.ev.glob("*.jsonl"))


    def window(self, start: datetime, end: datetime):
        """Події за довільне вікно часу — читає лише потрібні дні."""
        days = {(start + timedelta(days=i)).strftime("%Y-%m-%d")
                for i in range((end.date() - start.date()).days + 2)}
        out = []
        for d in sorted(days):
            f = self.ev / f"{d}.jsonl"
            if not f.exists():
                continue
            for line in f.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                e = json.loads(line)
                if start <= datetime.fromisoformat(e["t"]) < end:
                    out.append(e)
        return sorted(out, key=lambda e: e["t"])

    def stat(self):
        rows = []
        for d in self.dates():
            evs = [json.loads(l) for l in
                   (self.ev / f"{d}.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
            uniq = [e for e in evs if not e.get("dup_of")]
            pts = [e for e in uniq if e["scope"] == "точка"]
            rows.append({"date": d, "all": len(evs), "uniq": len(uniq),
                         "points": len(pts),
                         "drones": sum(e.get("drones") or 0 for e in uniq),
                         "geo": sum(1 for e in pts if e.get("lat"))})
        return rows

    # ---- запис ------------------------------------------------------------
    def build(self, posts, cfg, gaz, log=print, targets=None):
        """Перетворює сирі пости на події й розкладає по датах."""
        posts = sorted(posts, key=lambda p: p["date"])
        posts = E.enrich(posts, cfg)
        # коди областей виводяться раз на збірку — це прохід по ~112 записах
        # ADM1, а не по газетиру
        GC.geocode_posts(posts, gaz, cfg.geo, aliases=cfg.geo_aliases,
                         region_a1=gaz.region_codes(cfg.entities.get("регіон", {}),
                                                    cfg.geo))
        self._tidx = TargetIndex(targets["objects"]) if targets else None

        # дублікати: однаковий нормалізований текст у вікні 10 хв
        seen = {}
        for p in posts:
            key = D.norm(p["text"])
            t = datetime.fromisoformat(p["date"])
            prev = seen.get(key)
            if prev and (t - prev[1]).total_seconds() <= 600:
                p["_dup_of"] = prev[0]
            else:
                seen[key] = (f"{p['channel']}/{p['id']}", t)

        by_date = collections.defaultdict(list)
        for p in posts:
            e = self._event(p, cfg)
            by_date[e["date_msk"]].append(e)

        for d, evs in by_date.items():
            f = self.ev / f"{d}.jsonl"
            old = {}
            if f.exists():
                for line in f.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        o = json.loads(line)
                        old[o["id"]] = o
            for e in evs:
                old[e["id"]] = e            # ідемпотентно: перезапис, не дубль
            # Похідний шар відновлюється з data/, але обрубок тут ламає геть усе
            # читання: read()/window()/stat() йдуть по всіх днях і падають на
            # першому битому рядку — тобто одна аварія кладе весь store.
            with atomic_write(f) as fh:
                for _, e in sorted(old.items(), key=lambda kv: kv[1]["t"]):
                    fh.write(json.dumps(e, ensure_ascii=False) + "\n")
            log(f"  {d}: {len(old)} подій")

        self.state["version"] = PIPELINE_VERSION
        self.state["updated"] = datetime.now(timezone.utc).isoformat()
        for p in posts:
            ch = p["channel"]
            cur = self.state["channels"].get(ch, {})
            cur["last_id"] = max(cur.get("last_id", 0), p["id"])
            cur["last_date"] = max(cur.get("last_date", ""), p["date"])
            self.state["channels"][ch] = cur
        # state.json читає КОЖНА точка входу (sync, site, raid) у Store.__init__
        # без try/except — обрубок тут робить непрацездатним увесь конвеєр.
        write_text(self.state_path,
                   json.dumps(self.state, ensure_ascii=False, indent=2))
        return sum(len(v) for v in by_date.values())

    def _event(self, p, cfg):
        dt = datetime.fromisoformat(p["date"]).astimezone(MSK)
        clean, dropped = strip_promo(p["text"], cfg)
        pts = [e for e in p.get("entities", [])
               if "lat" in e and e.get("geo_conf") != "centroid"]
        best = max(pts, key=lambda e: e.get("geo_pop", 0), default=None)
        if best is None:
            best = next((e for e in p.get("entities", [])
                         if e["type"] == "регіон" and "lat" in e), None)
        # класифікуємо ОЧИЩЕНИЙ текст: інакше «…ПВН ПВО…» у рекламному рядку
        # робить із оголошення про набір подію типу «збиття»
        k = kind_of(clean)
        # Реклама й збори. Раніше умовою було «після чистки не лишилось нічого
        # змістовного» (len(clean) < 25), і цього виявилось замало: типовий
        # заклик на 10 рядків втрачає 3 на патернах, а решта 145 символів
        # проходить як звичайна подія. Так на сторінку «Що зараз» потрапив
        # банер зі збором коштів для російського каналу.
        #
        # Латати патерни під кожне формулювання марно: той банер не спіймався
        # лише через порядок слів («Радару требуется ваша поддержка» проти
        # «поддержка радара»). Тому ознака інша: хоч один промо-рядок І жоден
        # бойовий тег не спрацював. Пост зі справжнім спостереженням має kind
        # відмінний від «інше», тож правило не може сховати спостереження —
        # лише те, що й так ні в які підрахунки не входить.
        #
        # Виміряно на корпусі: 229 -> 1059 подій, тобто 0.2% -> 1.0%.
        noise = dropped > 0 and (len(clean) < 25 or k == "інше")
        m = COUNT_N.search(clean)
        ty = TYPE_RE.search(clean)
        region = next((e["value"] for e in p.get("entities", [])
                       if e["type"] == "регіон"), None)
        lat = best["lat"] if best else None
        lon = best["lon"] if best else None
        # Санітарна перевірка: НП не може бути за 1000 км від власної області.
        # Такі точки — помилка розвʼязання омоніма (Орловська -> Орськ,
        # Богородський ГО -> нижегородський Богородськ). Замість того щоб
        # тягнути брехню в метрики глибини, відкочуємось на центр області.
        rc = cfg.geo.get(region) if region else None
        if lat and rc and GC.haversine((lat, lon), rc) > 400:
            lat, lon = rc
            # Окрема позначка, а не мовчазна підміна: точка тут не розвʼязана,
            # а відкочена до центру області. Раніше вона виглядала в сховищі
            # так само, як чесно знайдений НП.
            best = {"value": region, "geo_name": region, "geo_conf": "region-snap"}
        return {
            "id": f"{p['channel']}/{p['id']}",
            "t": dt.isoformat(),
            "date_msk": dt.strftime("%Y-%m-%d"),
            "channel": p["channel"],
            "url": p["url"],
            "kind": k,
            "scope": "точка" if k in POINT_KINDS else "область",
            "place": (best or {}).get("geo_name") or (best or {}).get("value"),
            "lat": lat, "lon": lon,
            # Як саме знайдено координату. Рахувалось у geocode й викидалось:
            # у сховищі точка, підтверджена областю з того ж поста, виглядала
            # так само, як вгадана за населенням. Значення: region (є область),
            # consensus (топоніми поста зійшлись), global (фолбек «найбільший
            # однойменний» — найслабше), alias (ручне), city-marker/centroid
            # (подія по області), region-snap (відкат за санітарною межею).
            # Поле присутнє ЗАВЖДИ, зокрема None: test_schema_is_uniform
            # вимагає однаковий набір ключів у всіх рядках.
            "geo_conf": (best or {}).get("geo_conf"),
            "depth": round(depth_km((lat, lon))) if lat else None,
            "region": region,
            "drones": int(m.group(1)) if m else None,
            "group": bool(GROUP_RE.search(p["text"])),
            "utype": ty.group(1).capitalize() if ty else None,
            "dup_of": p.get("_dup_of"),
            # Привʼязка до цілі — ЛИШЕ для координат, які справді вказують на
            # місце. Регіональні відкати (centroid/region/region-snap) означають
            # «десь у цій області», а область — це десятки тисяч кв. км. Ставити
            # їм найближчу ціль означає вигадувати точність, якої в даних нема.
            #
            # Виміряно, і це не дрібниця: 64% усіх привʼязок (8182 з 12800)
            # стояли на такій координаті. Перекіс нерівномірний, тому й рейтинг
            # брехав — ціль біля центру області збирала всі нерозвʼязані події
            # цієї області, ціль осторонь не збирала нічого. Аеродром Клокове
            # був №1 із 572 привʼязками, з яких 71% — центр Тули за 5 км, куди
            # падали «Ясногорский район» і «Чернский район» за 50-80 км звідти.
            # Авіабаза Гвардійське 94%, Аеродром (Belgorod) 94%, Смоленськ —
            # Північний 91%; для порівняння Джанкой 6%, Севастополь 0%.
            "near": (self._tidx.nearest(lat, lon)
                     if getattr(self, "_tidx", None) and lat
                     and (best or {}).get("geo_conf") not in REGIONAL_FALLBACK
                     else None),
            "noise": noise,
            "promo_lines": dropped,
            "text": clean if clean else p["text"].replace("\n", " / "),
        }
