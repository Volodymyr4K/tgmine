"""Офлайн-геокодування топонімів через дамп GeoNames.

Три проблеми, які тут вирішуються:
  1. Омоніми — «Троицкое» в РФ десятки штук. Розвʼязуємо контекстом: якщо в тому ж
     пості є регіон, беремо найближчий до нього НП; інакше — найбільший за населенням.
  2. Відмінки й прикметникові форми — «Шебекинский район» проти «Шебекино» в базі.
  3. Райони — «Крымский район» це не місто Крымск; шукаємо і серед адмінодиниць.
"""
from __future__ import annotations

import collections
import math
import re

# GeoNames: 1=name 3=alternatenames 4=lat 5=lon 6=class 7=code 8=country 14=population
NAME, ALT, LAT, LON, FCLASS, FCODE, CC, ADM1, POP = 1, 3, 4, 5, 6, 7, 8, 10, 14

# Навмисно БЕЗ і/ї/є/ґ, попри назву. Фільтр вирішує, які альтернативні назви з
# газетира взагалі потраплять в індекс, і для російськомовного корпусу вужчий
# індекс точніший.
#
# Перевірено на даних, а не на око: у 25 956 запитах НП з трьох каналів рівно 0
# містять українські літери — канали пишуть «Кривой Рог», не «Кривий Ріг».
# Розширення фільтра додає 21 989 ключів (41.9% альт-назв UA.txt) і змінює
# 19 з 25 956 прив'язок: 9 краще (Галициновка -250 км помилки), 3 гірше
# (сміттєві запити «Над Качей» починають резолвитись у вигадану точку за 500 км),
# 7 неоднозначних. Чистий ефект близький до нуля, тому лишаємо як є.
#
# Переглянути, якщо в конвеєр заведуть україномовний канал із розбором НП:
# configs/ua-air.yaml зараз витягує лише назви областей, а вони резолвляться
# через cfg.geo, не через газетир — тому й там фільтр не заважає.
CYRILLIC = re.compile(r"^[а-яё\s\-']+$", re.I)
PUNCT = re.compile(r"[^\w\s-]", re.UNICODE)

# прикметник -> ймовірна основа НП: "шебекинский" -> "шебекин"
ADJ_SUFFIX = re.compile(r"(ский|ская|ское|ские|цкий|цкая|цкое|ской|скому|ском)$")
CASE_SUFFIX = re.compile(r"(ого|ому|ыми|ами|ой|ей|ом|ым|ах|ях|у|е|а|ы|и|о)$")


def norm(s: str) -> str:
    s = PUNCT.sub(" ", s.lower().replace("ё", "е"))
    return re.sub(r"\s+", " ", s).strip()


def haversine(a, b):
    R = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = (math.sin((la2 - la1) / 2) ** 2 +
         math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(h))


# Театр дій: європейська частина РФ + ТОТ. За цією рамкою збіг назви майже
# завжди означає сибірського тезку, а не реальну ціль: Angarsk за 4400 км від
# кордону — це не удар, це помилка розвʼязання омоніма.
THEATER = (43.0, 61.0, 22.0, 60.0)   # lat_min, lat_max, lon_min, lon_max


def in_box(lat, lon, box=THEATER):
    return box[0] <= lat <= box[1] and box[2] <= lon <= box[3]


class Gazetteer:
    def __init__(self):
        self.by_name: dict[str, list[dict]] = collections.defaultdict(list)
        self.stems: dict[str, list[str]] = collections.defaultdict(list)
        self.adm1: list[dict] = []       # записи ADM1 — для region_codes()

    @classmethod
    def load(cls, *paths, min_pop: int = 0, classes=("P", "A")) -> "Gazetteer":
        g = cls()
        for path in paths:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    c = line.rstrip("\n").split("\t")
                    if len(c) < 15 or c[FCLASS] not in classes:
                        continue
                    if c[FCLASS] == "A" and not c[FCODE].startswith("ADM"):
                        continue
                    try:
                        pop = int(c[POP] or 0)
                        lat, lon = float(c[LAT]), float(c[LON])
                    except ValueError:
                        continue
                    if pop < min_pop and c[FCLASS] == "P":
                        pass  # дрібні села лишаємо: саме вони й згадуються
                    rec = {"name": c[NAME], "lat": lat, "lon": lon, "pop": pop,
                           "cc": c[CC], "fclass": c[FCLASS], "fcode": c[FCODE],
                           "a1": c[ADM1]}
                    names = {c[NAME]}
                    names.update(x for x in c[ALT].split(",") if CYRILLIC.match(x))
                    if c[FCODE] in ("ADM1", "ADM1H"):
                        g.adm1.append({**rec, "alts": list(names)})
                    for n in names:
                        n = norm(n)
                        if len(n) >= 3:
                            g.by_name[n].append(rec)
        for n in g.by_name:
            g.stems[_stem(n)].append(n)
        return g

    def region_codes(self, entities_region: dict, geo: dict) -> dict:
        """Регіон конфіга -> код admin1 у GeoNames, напр. Ростовська -> RU.61.

        Навіщо: досі належність до області вгадувалась за відстанню до її
        центроїда, а область — 300-500 км завширшки, тож відстань не відрізняє
        «всередині цієї області» від «одразу за межею в сусідній». Через це
        «Дмитровский район / Орловская область» ставав однойменним районом
        Москви за 339 км, а «Красносулинский / Ростовская» — Краснослободськом
        за 398 км. admin1 — це фактична належність, не проксі.

        Зіставляємо за КИРИЛИЧНИМИ альт-назвами ADM1-записів, використовуючи ті
        самі патерни регіонів, що вже є в конфізі — окрема ручна таблиця не
        потрібна й не розʼїдеться.

        Не «найближчий ADM1 до центроїда»: перевірено, так помиляється на 3 з 39
        (Костромська -> Іванівська, Татарстан -> Марій Ел, Ленінградська ->
        Санкт-Петербург, який є окремим субʼєктом). За назвою — 39 з 39.

        Повертає МНОЖИНУ кодів на регіон, бо два регіони конфіга покривають по
        два субʼєкти: Крим — це UA.11 плюс Севастополь UA.20, а Московська —
        RU.47 плюс місто Москва RU.48. Спершу тут був один код (найближчий), і
        це мовчки вимикало фільтр саме для двох НАЙБІЛЬШИХ регіонів набору:
        811 і 754 точкових спостережень.
        """
        out = {}
        for reg, rx in entities_region.items():
            hits = [a for a in self.adm1
                    if any(rx.search(x) for x in a["alts"]) or rx.search(a["name"])]
            if not hits:
                continue
            c = geo.get(reg)
            if c:
                hits.sort(key=lambda a: haversine(c, (a["lat"], a["lon"])))
                # Сусідній субʼєкт із тією ж назвою — так, далекий тезка — ні.
                # Найдальший потрібний випадок: Севастополь за 66 км від
                # центроїда Криму; найдальший коректний одиночний — Костромська
                # за 185 км. 300 км лишає запас і не тягне чужих.
                hits = [a for a in hits
                        if haversine(c, (a["lat"], a["lon"])) <= 300] or hits[:1]
            out[reg] = frozenset((a["cc"], a["a1"]) for a in hits)
        return out

    def lookup(self, query: str, near: tuple[float, float] | None = None,
               max_km: float = 400.0, allow_far: bool = False, near_a1=None,
               box=THEATER) -> dict | None:
        """Знаходить НП. `near` — центроїд регіону з того ж поста, для омонімів.

        Якщо регіон відомий, а жодного тезки в радіусі немає — повертає None.
        Інакше «Западное» при Кримі підхоплює однойменне село в Примор'ї за
        7800 км: назва збіглася, сенсу нуль.
        """
        q = norm(query)
        cands = list(self.by_name.get(q) or [])
        if not cands:                       # прикметник/відмінок -> основа
            for key in self.stems.get(_stem(q), []):
                cands += self.by_name[key]
        if box:
            cands = [c for c in cands if in_box(c["lat"], c["lon"], box)]
        if not cands:
            return None
        if near:
            scoped = [(haversine(near, (c["lat"], c["lon"])), c) for c in cands]
            scoped = [(d, c) for d, c in scoped if d <= max_km]
            # Якщо в самій області є тезка — беремо тільки з неї. Це відсікає
            # однойменні райони сусідніх регіонів ДО того, як їх порівнює
            # формула: населення в GeoNames — ненадійний сигнал (pop=0 стоїть у
            # 97% населених пунктів і означає «невідомо», а не «порожньо»),
            # тому мільйонне місто за 300 км завжди перемагало правильний район
            # під боком. Фолбек на всіх кандидатів, якщо в області нема жодного.
            if near_a1:
                # ADM1 (сама область) з фільтра виведена, але ЛИШЕ для
                # прикметникової форми запиту. Область російською називають
                # прикметником — «Харьковская область», «Николаевской области»;
                # без винятку «Харьковская» ставала однойменним селом під
                # Бєлгородом за 200 км.
                #
                # Форма й розрізняє: «Николаевки» — це родовий відмінок СЕЛА
                # («От Николаевки в направлении Севастополь»), і воно дотягується
                # до Миколаївської області лише через стем. З винятком для всіх
                # ADM1 така подія їхала за 350 км в іншу країну.
                #
                # Райони (ADM2/ADM3) винятку не мають узагалі — саме їх і треба
                # відсікати: «Дмитровский район» при Орловській це не однойменний
                # район Москви.
                adjectival = bool(ADJ_SUFFIX.search(q.split()[0])) if q else False
                same = [(d, c) for d, c in scoped
                        if (c.get("cc"), c.get("a1")) in near_a1
                        or (adjectival and c.get("fcode") in ("ADM1", "ADM1H"))]
                if same:
                    scoped = same
            if scoped:
                # Компроміс населення/відстань. Чиста максимізація населення
                # кидала "ГО Богородск, Московская область" у нижегородський
                # Богородск за 370 км: він більший, але не той. Чиста
                # мінімізація відстані навпаки чіпляє хутори-тезки під боком.
                def score(dc):
                    dist, c = dc
                    return (c["pop"] + 500) / (1 + dist / 50.0)
                best = max(scoped, key=score)
                return {**best[1], "dist_km": round(best[0]), "conf": "region"}
            if not allow_far:
                return None
        best = max(cands, key=lambda c: c["pop"])
        return {**best, "dist_km": None, "conf": "global"}


def _stem(s: str) -> str:
    w = s.split()[0] if s else s
    w = ADJ_SUFFIX.sub("", w)
    if len(w) > 6:
        w = CASE_SUFFIX.sub("", w)
    return w[:7]


def geocode_posts(posts: list[dict], gaz: Gazetteer, region_geo: dict,
                  entity_type: str = "нп", max_km: float = 400.0,
                  refine_regions: bool = True, aliases: dict | None = None,
                  region_a1: dict | None = None) -> dict:
    """Проставляє lat/lon сутностям.

    refine_regions: місто-маркер області ("Керчь" -> Крим) віддає власні
    координати замість центроїда регіону. Інакше вся Керч сидить у центрі Криму
    і метрика глибини втрачає сотні кілометрів точності.
    """
    stats = collections.Counter()
    for p in posts:
        regions = [e["value"] for e in p.get("entities", [])
                   if e["type"] == "регіон" and e["value"] in region_geo]
        near = region_geo[regions[0]] if regions else None
        # код області з ПЕРШОЇ згаданої: саме її бере store.py як region
        a1 = (region_a1 or {}).get(regions[0]) if regions else None
        if near is None:
            # Прохід 1: якір. Регіону з конфіга нема ("Республика Мордовия"),
            # але в тексті є однозначний топонім — адмінодиниця чи велике місто.
            # Без цього кроку "Дальний Валуйского района" ловить тезку за 1500 км.
            anchors = []
            for e in p.get("entities", []):
                q = e.get("match") or e.get("value") or ""
                hit = gaz.lookup(q, None, max_km)
                if hit and (hit["fclass"] == "A" or hit["pop"] >= 50000):
                    anchors.append((hit["pop"], (hit["lat"], hit["lon"])))
            if anchors:
                near = max(anchors)[1]
                stats["anchored"] += 1
        if refine_regions:
            for e in p.get("entities", []):
                if e["type"] != "регіон" or not e.get("match"):
                    continue
                base = region_geo.get(e["value"])
                hit = gaz.lookup(e["match"], base, max_km)
                if hit and hit["fclass"] == "P" and hit["pop"] >= 1000:
                    e["lat"], e["lon"] = hit["lat"], hit["lon"]
                    e["geo_name"], e["geo_pop"] = hit["name"], hit["pop"]
                    e["geo_conf"] = "city-marker"
                    stats["region_refined"] += 1
                elif base:
                    e["lat"], e["lon"] = base
                    e["geo_conf"] = "centroid"
                    stats["region_centroid"] += 1
        for e in p.get("entities", []):
            if e["type"] != entity_type:
                continue
            q = e.get("match") or e["value"]
            al = (aliases or {}).get(str(q).lower().strip())
            if al:                       # ручне виправлення має пріоритет
                hit = {"lat": al[0], "lon": al[1], "name": q, "pop": 0,
                       "fclass": "P", "conf": "alias", "dist_km": None}
            else:
                hit = gaz.lookup(q, near, max_km, near_a1=a1)
            if hit:
                e["lat"], e["lon"] = hit["lat"], hit["lon"]
                e["geo_name"] = hit["name"]
                e["geo_pop"] = hit["pop"]
                e["geo_conf"] = hit["conf"]
                e["geo_dist_km"] = hit["dist_km"]
                stats["ok"] += 1
                stats["ok_" + hit["conf"]] += 1
            else:
                stats["miss"] += 1
    return dict(stats)
