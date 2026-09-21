"""Геокодування: розвʼязання омонімів. Потребує газетира (132 МБ)."""
import collections
import json
import unittest

from tests.helpers import GAZ, needs_gazetteer
from tgmine import extract as E, geocode as GC, store as ST
from tests.helpers import ROOT

CFG = ROOT / "configs" / "ru-monitor.yaml"


@needs_gazetteer
class TestRegionCodes(unittest.TestCase):
    """Регіон конфіга -> код admin1 у GeoNames.

    Належність вгадувалась за відстанню до центроїда області, а область
    300-500 км завширшки. «Дмитровский район / Орловская область» ставав
    однойменним районом Москви за 339 км.
    """

    @classmethod
    def setUpClass(cls):
        cls.cfg = E.Config.load(CFG)
        cls.gaz = GC.Gazetteer.load(GAZ / "RU.txt", GAZ / "UA.txt")
        cls.codes = cls.gaz.region_codes(cls.cfg.entities["регіон"], cls.cfg.geo)

    def test_every_region_resolves_to_a_code(self):
        missing = set(self.cfg.entities["регіон"]) - set(self.codes)
        self.assertEqual(missing, set(), "область без коду admin1")

    def test_known_codes(self):
        """Три з них помилявся б підхід «найближчий ADM1 до центроїда»."""
        for reg, want in [("Ростовська", {("RU", "61")}),
                          ("Орловська", {("RU", "56")}),
                          ("Костромська", {("RU", "37")}),
                          ("Татарстан", {("RU", "73")}),
                          ("Ленінградська", {("RU", "42")}),
                          # округи за Уралом: центроїд стоїть не в столиці,
                          # і збіг має йти за назвою, не за відстанню
                          ("ХМАО", {("RU", "32")}),
                          ("ЯНАО", {("RU", "87")})]:
            with self.subTest(region=reg):
                self.assertEqual(set(self.codes[reg]), want)

    def test_regions_covering_two_subjects(self):
        """Крим = АРК + Севастополь, Московська = область + місто.

        Один код на регіон мовчки вимикав фільтр для двох НАЙБІЛЬШИХ регіонів
        набору: у Криму 811 точкових спостережень, у Московській 754.
        """
        self.assertEqual(set(self.codes["Крим"]), {("UA", "11"), ("UA", "20")})
        self.assertEqual(set(self.codes["Московська"]), {("RU", "47"), ("RU", "48")})

    def test_no_region_shares_a_code_with_another(self):
        seen = {}
        for reg, codes in self.codes.items():
            for code in codes:
                if code in seen:
                    self.fail(f"{reg} і {seen[code]} мають спільний код {code}")
                seen[code] = reg


@needs_gazetteer
class TestHomonyms(unittest.TestCase):
    """Еталони, зібрані з реальних постів і перевірені вручну."""

    #: (запит, регіон із того ж поста, очікувані координати, допуск км)
    GOLD = [("Дмитровский", "Орловська", (52.50, 35.13), 60),
            ("Богородицкий", "Тульська", (53.77, 38.13), 60),
            ("Никольское", "Бєлгородська", (50.60, 36.60), 80),
            ("Ольховатский", "Воронезька", (50.28, 39.29), 40),
            ("Войково", "Крим", (45.38, 36.44), 40),
            # назва ОБЛАСТІ має лишатись областю, а не ставати однойменним
            # селом усередині регіону-якоря
            ("Харьковская", "Бєлгородська", (49.62, 36.50), 60),
            ("Николаевской", "ТОТ_Херсон", (46.97, 32.00), 60)]

    @classmethod
    def setUpClass(cls):
        cls.cfg = E.Config.load(CFG)
        cls.gaz = GC.Gazetteer.load(GAZ / "RU.txt", GAZ / "UA.txt")
        cls.codes = cls.gaz.region_codes(cls.cfg.entities["регіон"], cls.cfg.geo)

    def test_gold_set(self):
        for query, reg, gold, tol in self.GOLD:
            with self.subTest(query=query, region=reg):
                hit = self.gaz.lookup(query, near=self.cfg.geo[reg],
                                      max_km=400, near_a1=self.codes.get(reg))
                self.assertIsNotNone(hit, "не розвʼязано взагалі")
                d = GC.haversine(gold, (hit["lat"], hit["lon"]))
                self.assertLessEqual(d, tol,
                                     f"{hit['name']} за {d:.0f} км від очікуваного")

    def test_region_filter_actually_changes_the_answer(self):
        """Контроль: без коду області ці запити резолвляться інакше."""
        differing = 0
        for query, reg, _, _ in self.GOLD:
            a = self.gaz.lookup(query, near=self.cfg.geo[reg], max_km=400)
            b = self.gaz.lookup(query, near=self.cfg.geo[reg], max_km=400,
                                near_a1=self.codes.get(reg))
            if a and b and (a["lat"], a["lon"]) != (b["lat"], b["lon"]):
                differing += 1
        self.assertGreater(differing, 0, "фільтр admin1 ні на що не впливає")

    def test_oblast_only_for_adjectival_form(self):
        """Область називають прикметником; родовий відмінок села — ні.

        «Харьковская» -> область (правильно). «Николаевки» -> село в Криму,
        а не Миколаївська область за 350 км: до області воно дотягується лише
        через стем, і виняток для ADM1 на нього не поширюється.
        """
        obl = self.gaz.lookup("Харьковская", near=self.cfg.geo["Бєлгородська"],
                              max_km=400, near_a1=self.codes.get("Бєлгородська"))
        self.assertEqual(obl["fcode"], "ADM1")
        vil = self.gaz.lookup("Николаевки", near=self.cfg.geo["Крим"],
                              max_km=400, near_a1=self.codes.get("Крим"))
        self.assertNotIn(vil["fcode"], ("ADM1", "ADM1H"),
                         f"родовий відмінок села дав {vil['name']}")

    def test_out_of_theater_names_are_rejected(self):
        """Сибірський тезка за 4000 км — це помилка, не ціль."""
        hit = self.gaz.lookup("Ангарск", near=self.cfg.geo["Крим"], max_km=400)
        self.assertIsNone(hit)

    def test_far_region_unlocks_far_cities(self):
        """Рамка THEATER діє лише без області. З областю в пості шукається
        навколо неї: інакше Новий Уренгой (76.6° сх.) не знаходився взагалі,
        а «Сургут» без області і далі має лишатись самарським селом — так
        рамка й задумана."""
        for name, reg, want in [("Новый Уренгой", "ЯНАО", (66.08, 76.63)),
                                ("Сургут", "ХМАО", (61.26, 73.42)),
                                ("Нижневартовск", "ХМАО", (60.93, 76.55)),
                                ("Ноябрьск", "ЯНАО", (63.19, 75.44)),
                                ("Тюмень", "Тюменська", (57.15, 65.53)),
                                ("Екатеринбург", "Свердловська", (56.86, 60.62))]:
            with self.subTest(name=name):
                hit = self.gaz.lookup(name, near=self.cfg.geo[reg], max_km=400,
                                      near_a1=self.codes.get(reg))
                self.assertIsNotNone(hit, f"{name} при {reg} не знайдено")
                self.assertAlmostEqual(hit["lat"], want[0], delta=0.05)
                self.assertAlmostEqual(hit["lon"], want[1], delta=0.05)
                # «Тюмень» — ще й альт-назва області в GeoNames; місто має
                # перемагати субʼєкт
                self.assertNotIn(hit["fcode"], ("ADM1", "ADM1H"))
        # без області рамка лишається: за нею вибирає населення, і воно б
        # завжди брало сибірського тезку
        far = self.gaz.lookup("Сургут")
        self.assertTrue(GC.in_box(far["lat"], far["lon"]))


@needs_gazetteer
class TestConsensus(unittest.TestCase):
    """Пост без назви області: топоніми перевіряють одне одного.

    Раніше тут лишався фолбек «найбільший однойменний за населенням», і він
    кидав точки за сотні кілометрів. Гірше — якірний прохід дозволяв
    неоднозначному топоніму стати якорем САМОМУ СОБІ, і та сама помилка
    виходила вже з conf="region", ніби її підтвердив контекст: 713 розвʼязань
    у корпусі мали таку позначку з єдиного топоніма в пості.

    Всі пости тут — справжні, з data/*.jsonl.
    """

    #: (текст поста, запит, очікувані координати, допуск км)
    GOLD = [
        # Красногвардійський район КРИМУ, а не однойменний район Пітера за
        # 1639 км. Точний збіг назви веде лише в Пітер — кримський варіант
        # лежить під ключем «красногвардейское» і видимий тільки широкому
        # набору кандидатів.
        ("Красногвардейский район в направлении Белогорск фиксации БПЛА "
         "Пойдут на трассу Таврида или Таврическую ТЭС",
         "Красногвардейский", (45.50, 34.30), 45),
        ("Красногвардейский район в направлении Белогорск фиксации БПЛА "
         "Пойдут на трассу Таврида или Таврическую ТЭС",
         "Белогорск", (45.06, 34.60), 20),
        # Мирне Каланчацької громади (pop 1880) проти Мирного під
        # Сімферополем (pop 9284) за 147 км: населення програє сусідству.
        ("Каланчак, Мирное тревога по БПЛА носителю ФПВ",
         "Мирное", (46.25, 33.47), 30),
        # Три кримські назви поспіль; жодного спільного скупчення деінде.
        ("Желябовка, Советский, Кировское и близлежащие, тревога по БпЛА",
         "Советский", (45.34, 34.92), 25),
        ("Желябовка, Советский, Кировское и близлежащие, тревога по БпЛА",
         "Кировское", (45.23, 35.20), 30),
        # Міллеровський район Ростовської, а не однойменний у Саратовській.
        ("От Новоайдар в сторону Миллеровский район и Чертковский район "
         "фиксации БПЛА", "Миллеровский", (48.93, 40.40), 40),
        # Красноярузький р-н Бєлгородщини, а не Красноярський у Самарській.
        ("Ракитянский район, Борисовский район, Краснояружский район "
         "и близлежащие Тревога по УАБ", "Краснояружский", (50.82, 35.54), 25),
    ]

    @classmethod
    def setUpClass(cls):
        cls.cfg = E.Config.load(CFG)
        cls.gaz = GC.Gazetteer.load(GAZ / "RU.txt", GAZ / "UA.txt")
        cls.a1 = cls.gaz.region_codes(cls.cfg.entities["регіон"], cls.cfg.geo)

    def _resolve(self, text, query):
        posts = E.enrich([{"channel": "t", "id": 1, "text": text,
                           "date": "2026-07-01T10:00:00+00:00"}], self.cfg)
        GC.geocode_posts(posts, self.gaz, self.cfg.geo,
                         aliases=self.cfg.geo_aliases, region_a1=self.a1)
        for e in posts[0].get("entities", []):
            if e["type"] == "нп" and (e.get("match") or e.get("value")) == query:
                return e
        return None

    def test_gold_set(self):
        for text, query, gold, tol in self.GOLD:
            with self.subTest(query=query):
                e = self._resolve(text, query)
                self.assertIsNotNone(e, "сутність не витягнулась")
                self.assertIsNotNone(e.get("lat"), "не розвʼязано взагалі")
                d = GC.haversine(gold, (e["lat"], e["lon"]))
                self.assertLessEqual(
                    d, tol, f"{e.get('geo_name')} за {d:.0f} км від очікуваного")

    def test_wide_set_sees_morphological_variant_despite_exact_homonym(self):
        """Точний збіг більше не замикає пошук накоротко.

        Це корінь помилки з Пітером: by_name["красногвардейский"] непорожній
        (район Пітера), тому стем-гілка не виконувалась, і кримський Курман
        у список кандидатів не потрапляв ЖОДНОГО разу — його неможливо було
        обрати за жодного відбору.
        """
        narrow = self.gaz.candidates("Красногвардейский")
        wide = self.gaz.candidates("Красногвардейский", wide=True)
        crimean = lambda cs: [c for c in cs if (c["cc"], c["a1"]) == ("UA", "11")]
        self.assertEqual(crimean(narrow), [], "вузький набір раптом бачить Крим")
        self.assertTrue(crimean(wide), "широкий набір не бачить кримського тезки")

    def test_only_exact_name_match_may_anchor(self):
        """Якір із морфологічного здогаду тягне за собою весь пост.

        «Островское Первомайский» точного збігу не має, зате через основу
        дотягується до Островського району Псковщини — і, ставши якорем, тягне
        сусіднє «Гвардейское» під Виборг за 1775 км від кримського.

        Слід малий: після узгодження вимога міняє всього 3 рядки корпусу (воно
        перехоплює більшість таких постів раніше), і виграш чистий лише в
        цьому. Лишена тому, що якір із морфологічного здогаду — це не якір, а
        та сама вгадайка, тільки з позначкою «підтверджено».
        """
        e = self._resolve("Островское Первомайский район и далее в направлении "
                          "Гвардейское тревога по БПЛА", "Гвардейское")
        self.assertIsNotNone(e.get("lat"))
        d = GC.haversine((45.12, 34.02), (e["lat"], e["lon"]))
        self.assertLessEqual(d, 30, f"{e.get('geo_name')} за {d:.0f} км від Криму")

    def test_support_comes_from_the_weightiest_twin_not_the_nearest(self):
        """Підтверджує пару найвагоміший тезка в колі, а не найближчий.

        «Сары Баш, Войково и далее на Гвардейское»: за найближчим кримська
        пара трималась на хуторі Гвардійське (pop 772) за 15 км і програвала
        дніпровській; за найвагомішим — селищі Гвардійське (pop 12 589) за
        45 км — виграє з запасом.
        """
        e = self._resolve("Сары Баш, Войково и далее на Гвардейское, "
                          "в том числе трасса тревога по БПЛА", "Гвардейское")
        self.assertIsNotNone(e.get("lat"))
        d = GC.haversine((45.12, 34.02), (e["lat"], e["lon"]))
        self.assertLessEqual(d, 30, f"{e.get('geo_name')} за {d:.0f} км від Криму")

    def test_single_toponym_post_keeps_the_old_fallback(self):
        """Стеля методу, виміряна до написання коду.

        Постів без регіону з ≥2 резолвними топонімами — 778 із 3379 (23%).
        Решта перевіряти нема чим, і там свідомо лишається «найбільший за
        населенням». Тест фіксує саме це, щоб межу не переплутали з вадою.
        """
        e = self._resolve("Гуляйполе уаб", "Гуляйполе")
        self.assertEqual(e["geo_conf"], "global")


@needs_gazetteer
class TestHomonymFixture(unittest.TestCase):
    """Повний розмічений набір: tests/data/homonyms.jsonl, 113 випадків.

    Навіщо окремим файлом, а не сімкою прикладів у коді. Вибір розвʼязувача
    двічі робився за набором на 7 випадків, і обидва рази ламав те, чого в
    наборі не було. Сім прикладів не набір, а ілюстрація: вони підтверджують
    задум і мовчать про побічну шкоду.

    Вибірка не з голови: 40 випадкових УНІКАЛЬНИХ постів без регіону з ≥2
    резолвними топонімами (seed=7) плюс топ-60 найчастіших неоднозначних
    запитів корпусу. Тексти постів вкладено дослівно з data/ разом із
    переносами рядків — вони впливають на розбір, і плаский переказ дає інші
    сутності (на цьому я вже спіймався).

    Мітки:
      guard   — було правильно; зміна тут це регресія
      fixed   — було неправильно, полагоджено узгодженням топонімів
      ceiling — відомо, що не працює й чому; тест вимагає, щоб воно НЕ
                проходило, інакше про покращення ніхто не дізнається
    """

    @classmethod
    def setUpClass(cls):
        cls.cfg = E.Config.load(CFG)
        cls.gaz = GC.Gazetteer.load(GAZ / "RU.txt", GAZ / "UA.txt")
        a1 = cls.gaz.region_codes(cls.cfg.entities["регіон"], cls.cfg.geo)
        cls.rows = [json.loads(l) for l in
                    (ROOT / "tests/data/homonyms.jsonl").read_text(
                        encoding="utf-8").splitlines() if l.strip()]
        texts = sorted({r["text"] for r in cls.rows})
        posts = E.enrich([{"channel": "fixture", "id": i, "text": t,
                           "date": "2026-07-01T10:00:00+00:00"}
                          for i, t in enumerate(texts)], cls.cfg)
        GC.geocode_posts(posts, cls.gaz, cls.cfg.geo,
                         aliases=cls.cfg.geo_aliases, region_a1=a1)
        cls.by_text = {p["text"]: p for p in posts}

    def _hit(self, row):
        """(відстань у км до еталона, підпис) або (None, причина)."""
        for e in self.by_text[row["text"]].get("entities", []):
            if e["type"] != "нп":
                continue
            if (e.get("match") or e.get("value")) != row["query"]:
                continue
            if e.get("lat") is None:
                return None, "не розвʼязано"
            d = GC.haversine((row["lat"], row["lon"]), (e["lat"], e["lon"]))
            return d, f'{e.get("geo_name")} conf={e.get("geo_conf")}'
        return None, "сутність не витягнулась"

    def test_guard_and_fixed_cases(self):
        for row in self.rows:
            if row["status"] == "ceiling":
                continue
            with self.subTest(status=row["status"], query=row["query"]):
                d, what = self._hit(row)
                self.assertIsNotNone(d, what)
                self.assertLessEqual(
                    d, row["tol_km"], f'{what} за {d:.0f} км від еталона')

    def test_known_ceiling_cases_still_fail(self):
        """Ратчет у зворотний бік: полагодив — перенеси рядок у fixed.

        Стеля тут не абстрактна, кожен випадок має свою причину:

        «Берестовое» — другий топонім поста («Мальцевка») сам неоднозначний і
        весь із записів pop=0, зійтись нема на чому.

        «Первомайское» — сусід із друкарською помилкою каналу
        («Красногвадейское»), точного збігу нема, тож і голосувати нема кому.

        «Октябрьское» — чесна межа МЕТОДУ, а не недогляд: у пості «Красный
        Партизан, Красногвардейский район … Октябрьское» всі три назви мають
        пітерське прочитання, і воно взаємно узгоджене незгірш за кримське.
        Узгодженість тут просто не розрізняє; потрібен зовнішній сигнал
        (сусідні пости каналу за той самий наліт), а його ще не міряли.
        """
        for row in self.rows:
            if row["status"] != "ceiling":
                continue
            with self.subTest(query=row["query"]):
                d, what = self._hit(row)
                if d is not None and d <= row["tol_km"]:
                    self.fail(f'«{row["query"]}» тепер розвʼязується правильно '
                              f'({what}) — переведи рядок у status="fixed" '
                              f'у tests/data/homonyms.jsonl')

    def test_fixture_covers_both_directions(self):
        """Набір без guard-випадків міряв би лише те, що я хотів побачити."""
        n = collections.Counter(r["status"] for r in self.rows)
        self.assertGreaterEqual(n["guard"], 50, "замало охоронних випадків")
        self.assertGreaterEqual(n["fixed"], 10, "замало цільових випадків")


class TestNormalisation(unittest.TestCase):
    """Без газетира."""

    def test_yo_is_folded(self):
        self.assertEqual(GC.norm("Королёв"), GC.norm("Королев"))

    def test_case_and_punctuation(self):
        self.assertEqual(GC.norm("  Нижний  Новгород! "), "нижний новгород")

    def test_theater_box(self):
        self.assertTrue(GC.in_box(50.6, 36.6))      # Бєлгород
        self.assertFalse(GC.in_box(52.29, 104.30))  # Іркутськ
        self.assertFalse(GC.in_box(64.54, 40.52))   # Архангельськ, за 61°


if __name__ == "__main__":
    unittest.main()


@needs_gazetteer
class TestDistrictSuffix(unittest.TestCase):
    """«<Назва> район» — це район, і в газетирі він є під двослівним ключем.

    Слово «район» іде з малої літери, тому шаблон freeform його не бере, і в
    газетир летить сам прикметник. «Панинский» -> PPL у Рязанській за 214 км
    від Воронезької, тоді як «Панинский Район» ADM2 RU.86 лежить за 64 км.
    Заміряно на 15 добах: розвʼязань, що стоять поза ВСІМА областями, названими
    у їхньому ж пості, було 1627, стало 1057 (-35%); 574 переїхали ззовні
    всередину своєї області, 0 — навпаки, ще 469 розвʼязались уперше.

    Полігон області тут не рятує: серед 2055 фолбеків кандидат усередині
    полігону знайшовся лише в 4. Річ не у фільтрі, а в тому, що правильного
    запису серед кандидатів не було взагалі.

    Тексти дослівні з `data/`.
    """

    @classmethod
    def setUpClass(cls):
        cls.cfg = E.Config.load(CFG)
        cls.gaz = GC.Gazetteer.load(GAZ / "RU.txt", GAZ / "UA.txt")
        cls.a1 = cls.gaz.region_codes(cls.cfg.entities["регіон"], cls.cfg.geo)
        cls.polys = json.loads((ROOT / "regions.json").read_text(encoding="utf-8"))

    @staticmethod
    def _inside(lat, lon, rings):
        """Промінь праворуч. Кільця вже спрощені, тож межа з похибкою ~км."""
        ins = False
        for ring in rings:
            j = len(ring) - 1
            for i, (yi, xi) in enumerate(ring):
                yj, xj = ring[j]
                if (xi > lon) != (xj > lon):
                    if lat < (yj - yi) * (lon - xi) / (xj - xi) + yi:
                        ins = not ins
                j = i
        return ins

    def _resolve(self, text):
        posts = [{"channel": "t", "id": 1, "date": "2026-08-20T10:00:00+00:00",
                  "text": text}]
        posts = E.enrich(posts, self.cfg)
        GC.geocode_posts(posts, self.gaz, self.cfg.geo,
                         aliases=self.cfg.geo_aliases, region_a1=self.a1)
        return [e for e in posts[0]["entities"]
                if e["type"] == "нп" and "lat" in e]

    def test_district_lands_in_its_own_oblast(self):
        for text, reg in [
            ("Панинский район, Воронежская область - опасность по БПЛА.\n"
             "📡\nЛокатор России -\n@locatorru", "Воронезька"),
            ("Стародубский район, Погарский район, Брянская область - ещё "
             "фиксации БПЛА от госграницы.\n📡\nЛокатор России -\n@locatorru",
             "Брянська"),
            ("Рудовка, Пичаевский район, Тамбовская область - пролёт от 3 БПЛА "
             "в сторону Пичаево.\n📡\nЛокатор России -\n@locatorru",
             "Тамбовська"),
        ]:
            with self.subTest(text=text[:30]):
                got = self._resolve(text)
                self.assertTrue(got, "жодного НП не розвʼязано")
                rings = self.polys[reg]
                self.assertTrue(
                    any(self._inside(e["lat"], e["lon"], rings) for e in got),
                    f"жодна точка не в {reg}: "
                    f"{[(e.get('geo_name'), e['lat'], e['lon']) for e in got]}")

    def test_accented_district_is_found(self):
        """Район із наголосами в альт-назві — теж район.

        Тут був тест «району в газетирі нема» саме на «Урицкий район»: у
        GeoNames він записаний як «У́рицкий райо́н», і фільтр CYRILLIC відкидав
        назву цілком. Після `clean_alt` (21 вересня 2026) район є, і крапка
        має лягти в Орловську, а не на центр області.
        """
        self.assertTrue(self.gaz.by_name.get(GC.norm("Урицкий район")))
        got = self._resolve("п.Гагаринский, Урицкий район, Орловская область - "
                            "пролёт БПЛА на Нарышкино.\n📡\nЛокатор России -\n"
                            "@locatorru")
        self.assertTrue(got, "розбір не має ламатись")
        self.assertTrue(any(self._inside(e["lat"], e["lon"], self.polys["Орловська"])
                            for e in got))


@needs_gazetteer
class TestRegionNameIsNotACityMarker(unittest.TestCase):
    """Назва області маркером-містом бути не може.

    «Волгоградская область» через стем «волгоград» діставала МІСТО Волгоград
    (pop 1 013 533), сутність-регіон ставала точкою — і `store.point_entity`,
    який бере найбільший за населенням топонім, віддавав крапку їй замість
    розвʼязаного району того самого поста. «Урюпинский район / Волгоградская
    область» їхало на 301 км.

    Чому це вилізло саме там: `lookup` важить (pop+500)/(1+dist/50), і в решті
    областей виграє запис ADM1 (fclass A -> conf centroid, а centroid
    point_entity відкидає). Волгоград стоїть у дальньому кутку витягнутої
    області, тож центроїд ADM1 за 105 км програє місту за 1 км.
    """

    @classmethod
    def setUpClass(cls):
        cls.cfg = E.Config.load(CFG)
        cls.gaz = GC.Gazetteer.load(GAZ / "RU.txt", GAZ / "UA.txt")
        cls.a1 = cls.gaz.region_codes(cls.cfg.entities["регіон"], cls.cfg.geo)

    def test_region_name_is_recognised(self):
        for q, reg in [("Волгоградская", "Волгоградська"),
                       ("Волгоградской", "Волгоградська"),
                       ("Воронежской", "Воронезька"),
                       ("Астраханская", "Астраханська"),
                       ("Московской", "Московська")]:
            with self.subTest(q=q):
                self.assertTrue(
                    self.gaz.names_the_region(q, self.a1[reg]),
                    "прикметникова назва області має впізнаватись")

    def test_city_stays_a_marker(self):
        """Іменник — це місто, і крапку він дає. Тут легко зламати зайвим.

        Обидві сторони порівняння проходять через ту саму основу, тому
        «Волгоград» і «Волгоградом» маркерами лишаються, хоч корінь у них
        той самий, що в області.
        """
        for q, reg in [("Волгоград", "Волгоградська"),
                       ("Волгоградом", "Волгоградська"),
                       # місто Волжский — прикметникове за формою
                       ("Волжский", "Волгоградська"),
                       ("Камышин", "Волгоградська"),
                       ("Москве", "Московська"),
                       ("Ахтубинск", "Астраханська")]:
            with self.subTest(q=q):
                self.assertFalse(self.gaz.names_the_region(q, self.a1[reg]))

    def test_district_adjectives_are_not_region_names(self):
        """Прикметник сам по собі критерієм НЕ є — і це головна пастка.

        Прикметникових збігів, що давали city-marker, 8644, і більшість із них
        маркери чесні: центр району і є те саме місто.
        """
        for q, reg in [("Стародубский", "Брянська"),
                       ("Симферопольский", "Крим"),
                       ("Севастопольской", "Крим"),
                       ("Дзержинский", "Нижегородська"),
                       ("Железногорский", "Курська"),
                       ("Домодедовский", "Московська"),
                       ("Красноармейский", "Краснодарський"),
                       # село, а не Крим: основа «крым» коротша за поріг
                       ("Крымское", "Крим")]:
            with self.subTest(q=q):
                self.assertFalse(self.gaz.names_the_region(q, self.a1[reg]))

    def test_short_stems_never_match(self):
        """Поріг у 5 літер — запобіжник, а не косметика.

        «курская» -> «кур», «омская» -> «ом», «донецкая» -> «доне»: такі основи
        збігалися б із чужими назвами. Жодна область, де вада справді є,
        основи коротшої за 6 не має.
        """
        for reg in ("Курська", "Омська", "Тульська", "Липецька", "Тверська"):
            with self.subTest(reg=reg):
                self.assertEqual(self.gaz.self_roots(self.a1[reg]), set())

    def test_district_wins_over_the_region_city(self):
        """Вихідна скарга оператора, від тексту поста до крапки."""
        for text, want, tol in [
            ("Урюпинский район\nВолгоградская область\nФиксация БПЛА",
             (50.819, 41.863), 25),
            ("Кумылженский район\nВолгоградская область\nФиксация БПЛА",
             (49.833, 42.437), 25),
            ("Ахтубинский район\nАстраханская область\nОпасность по БПЛА",
             (48.28, 46.19), 40),
        ]:
            with self.subTest(text=text.split("\n")[0]):
                posts = E.enrich([{"channel": "t", "id": 1, "text": text,
                                   "date": "2026-07-01T10:00:00+00:00"}], self.cfg)
                GC.geocode_posts(posts, self.gaz, self.cfg.geo,
                                 aliases=self.cfg.geo_aliases, region_a1=self.a1)
                best = ST.point_entity(posts[0])
                self.assertIsNotNone(best, "крапки нема взагалі")
                d = GC.haversine((best["lat"], best["lon"]), want)
                self.assertLess(d, tol,
                                f"крапка на {best.get('geo_name')} за {d:.0f} км")

    def test_city_over_the_region_still_points_at_the_city(self):
        """Зворотний бік: пост НАЗВАВ місто — крапка має лишитись на ньому."""
        posts = E.enrich([{"channel": "t", "id": 1, "date": "2026-07-01T10:00:00+00:00",
                           "text": "Волгоград\nОпасность по БПЛА"}], self.cfg)
        GC.geocode_posts(posts, self.gaz, self.cfg.geo,
                         aliases=self.cfg.geo_aliases, region_a1=self.a1)
        best = ST.point_entity(posts[0])
        self.assertIsNotNone(best, "місто має лишатись крапкою")
        self.assertEqual(best.get("geo_conf"), "city-marker")


@needs_gazetteer
class TestWholeSubjectIsAreaNotPoint(unittest.TestCase):
    """Цілий субʼєкт має координату, але крапкою події не є.

    Принцип уже діяв під узгодженням; поза ним лишався, і видно це стало, коли
    назва області перестала бути маркером: у переліку «Астраханская область,
    Республика Калмыкия, Ставропольский край» Калмикії в конфізі нема, вона
    падає у freeform як НП, резолвиться в запис ADM1 і забирає крапку за 300 км
    від названої першою області.

    Відсівати такі розвʼязання геть НЕ можна: 1321 пост у вікні сховища
    лишився б без координат зовсім («Республика Чувашия — опасность по БПЛА»,
    «Пуски БПЛА Одесса» — місто лежить у газетирі під записом області).
    """

    @classmethod
    def setUpClass(cls):
        cls.cfg = E.Config.load(CFG)
        cls.gaz = GC.Gazetteer.load(GAZ / "RU.txt", GAZ / "UA.txt")
        cls.a1 = cls.gaz.region_codes(cls.cfg.entities["регіон"], cls.cfg.geo)

    def _post(self, text):
        posts = E.enrich([{"channel": "t", "id": 1, "text": text,
                           "date": "2026-07-01T10:00:00+00:00"}], self.cfg)
        GC.geocode_posts(posts, self.gaz, self.cfg.geo,
                         aliases=self.cfg.geo_aliases, region_a1=self.a1)
        return posts[0]

    def test_subject_keeps_coordinates(self):
        p = self._post("Республика Чувашия - опасность по БПЛА")
        sub = [e for e in p["entities"] if e["type"] == "нп" and "lat" in e]
        self.assertTrue(sub, "субʼєкт має лишитись із координатою")
        self.assertEqual(sub[0]["geo_conf"], "centroid", "це площа, не крапка")

    def test_subject_does_not_steal_the_point(self):
        """Перелік субʼєктів: крапка лишається в названій першою області."""
        p = self._post("Астраханская область, Республика Калмыкия, "
                       "Ставропольский край - опасность по БПЛА")
        self.assertIsNone(ST.point_entity(p),
                          "цілий субʼєкт не може бути крапкою події")

    def test_adjectival_subject_too(self):
        """Виняток для прикметникової форми тут НЕ діє — координата й так є.

        З ним крізь фільтр проходили «Чеченская» і «Чувашская», і в переліку
        республік крапку забирала Чечня на 1.2 млн.
        """
        p = self._post("Республика Дагестан, Республика Ингушетия, "
                       "Чеченская Республика - опасность по БПЛА")
        self.assertIsNone(ST.point_entity(p))


@needs_gazetteer
class TestDistrictEatenByTheRegionMarker(unittest.TestCase):
    """Маркер області зʼїдав прикметник району, і місце зникало взагалі.

    Маркери в конфізі — це назви МІСТ, і прикметник району від того самого
    міста вони ловлять теж: «Россош\\w*» бере «Россошанский», «Камышин\\w*» —
    «Камышинский». `freeform_of` вважав слово вже впізнаним і топоніма не
    створював, тож розвʼязувати було нічого — подія падала на центр області.
    Заміряно у вікні сховища: 8257 таких збігів, 3582 події на центрі області,
    у 2236 зсув понад 30 км (медіана 109).

    Правок три, бо поодинці кожна ламає інше:
      1. `extract` — збіг перед словом «район» не «зайнятий», топонім є;
      2. `geocode` — такий маркер не стає містом (інакше Бердянськ на 176 тис.
         переб'є свій же район);
      3. `store.point_entity` — площа не б'є крапку, а серед площ вирішує
         область поста й порядок, не населення.
    """

    @classmethod
    def setUpClass(cls):
        cls.cfg = E.Config.load(CFG)
        cls.gaz = GC.Gazetteer.load(GAZ / "RU.txt", GAZ / "UA.txt")
        cls.a1 = cls.gaz.region_codes(cls.cfg.entities["регіон"], cls.cfg.geo)

    def _point(self, text):
        posts = E.enrich([{"channel": "t", "id": 1, "text": text,
                           "date": "2026-07-01T10:00:00+00:00"}], self.cfg)
        GC.geocode_posts(posts, self.gaz, self.cfg.geo,
                         aliases=self.cfg.geo_aliases, region_a1=self.a1)
        return ST.point_entity(posts[0]), posts[0]

    def _assert_near(self, text, want, tol):
        best, _ = self._point(text)
        self.assertIsNotNone(best, "крапки нема взагалі")
        d = GC.haversine((best["lat"], best["lon"]), want)
        self.assertLess(d, tol, f"крапка на {best.get('geo_name')} за {d:.0f} км")

    def test_district_far_from_its_marker_city(self):
        """Ті, де зсув найбільший."""
        for text, want in [
                ("Россошанский район\nВоронежская область\nФиксация БПЛА", (50.20, 39.57)),
                ("Камышинский район\nВолгоградская область\nФиксация БПЛА", (50.25, 45.37)),
                ("Валуйский район\nБелгородская область\nФиксация БПЛА", (50.21, 38.10)),
                ("Морозовский район\nРостовская область\nФиксация БПЛА", (48.35, 41.82))]:
            with self.subTest(text=text.split("\n")[0]):
                self._assert_near(text, want, 30)

    def test_marker_that_is_a_real_city_does_not_win(self):
        """Бердянськ (176 тис.) не має перебивати Бердянський район.

        Саме через це самої правки в `extract` мало: маркер резолвився в
        місто, а місто за населенням билo район.
        """
        self._assert_near("Бердянский район\nЗапорожская область\nФиксация БПЛА",
                          (46.76, 36.79), 30)

    def test_safe_pairs_stay_put(self):
        """Район навколо СВОГО ж міста чіпати не можна — зсув там одиниці км."""
        for text, want in [
                ("Орловский район\nОрловская область\nФиксация БПЛА", (52.97, 36.07)),
                ("Мелитопольский район\nЗапорожская область\nФиксация БПЛА", (46.84, 35.36)),
                ("Белгородский район\nБелгородская область\nФиксация БПЛА", (50.60, 36.59))]:
            with self.subTest(text=text.split("\n")[0]):
                self._assert_near(text, want, 25)

    def test_city_marker_still_marks_the_city(self):
        """Зворотний бік: без слова «район» маркер лишається містом."""
        best, _ = self._point("Шебекино, Белгородская область - взрывы")
        self.assertEqual(best.get("geo_name"), "Shebekino")

    def test_settlement_beats_the_district(self):
        """Село, назване поруч із районом, точніше за центр району."""
        self._assert_near(
            "Староивановка, Волоконовский район, Белгородская область - пролёт БПЛА",
            (50.49, 37.86), 25)

    def test_own_region_outranks_the_object_class(self):
        """А ось СЕЛО З ЧУЖОЇ області району не б'є — і це не дрібниця.

        «Богучарский район, Воронежская область — фиксации на Шолоховский
        район, Ростовская»: Шолоховський розвʼязується селом на 10 тис. у
        Ростовській, Богучарський — районом у Воронезькій. Правило «крапка
        над площею» без перевірки області віддавало крапку селу за 100 км.
        """
        self._assert_near(
            "Богучарский район, Воронежская область - фиксации БПЛА "
            "на Шолоховский район, Ростовская область", (49.93, 40.55), 40)

    def test_among_districts_the_first_named_wins(self):
        """Серед площ вирішує порядок, не населення: рядок 1 — географія."""
        best, _ = self._point("Наро-Фоминский район, Троицкий АО, "
                              "Московская область - опасность по БПЛА")
        self.assertIn("Naro-Fominsk", str(best.get("geo_name")),
                      "має виграти перший названий район")


@needs_gazetteer
class TestLaunchesTellTheTruth(unittest.TestCase):
    """Пуск на карті: ЗВІДКИ і ЧИМ — правдиво (21 вересня 2026).

    Розбір 547 крапок-пусків: на джерелі стояли 219 (40%), решта — на цілі.
    Тут стережуться всі механізми, які цю брехню давали.
    """

    @classmethod
    def setUpClass(cls):
        cls.cfg = E.Config.load(CFG)
        cls.gaz = GC.Gazetteer.load(GAZ / "RU.txt", GAZ / "UA.txt")
        cls.a1 = cls.gaz.region_codes(cls.cfg.entities["регіон"], cls.cfg.geo)

    def _post(self, text):
        posts = E.enrich([{"channel": "t", "id": 1, "text": text,
                           "date": "2026-07-01T10:00:00+00:00"}], self.cfg)
        GC.geocode_posts(posts, self.gaz, self.cfg.geo,
                         aliases=self.cfg.geo_aliases, region_a1=self.a1)
        return posts[0]

    def _names(self, text):
        return {e.get("geo_name") for e in self._post(text)["entities"]}

    # ---- назви зброї й службові слова — не села ----

    def test_storm_shadow_is_not_a_village(self):
        """«Штормов» — ракета Storm Shadow, а не село Штормове в Криму (10 із 12)."""
        self.assertNotIn("Shtormovoye",
                         self._names("В воздухе носители Штормов!"))
        self.assertEqual(ST.utype_of("Возможны пуски Штормов"), "Storm Shadow / SCALP")
        self.assertEqual(ST.utype_of("Ещё Шторма Бердянск в море"), "Storm Shadow / SCALP")

    def test_real_villages_named_storm_survive(self):
        """«Штормовое» (105 згадок) — справжнє кримське село."""
        self.assertIn("Shtormovoye",
                      self._names("Донузлав, Мирный, Витино, Штормовое, Молочное"))
        self.assertIsNone(ST.utype_of("Донузлав, Мирный, Витино, Штормовое"))

    def test_compass_word_is_not_a_place(self):
        """«Юг Киевская область» — «юг» ставав селом Югський у Вологодській."""
        self.assertNotIn("Yugskiy", self._names("Юг Киевская область фиксация F-16 пары"))

    def test_named_oblast_is_the_whole_oblast(self):
        """«Киевская область» — Київська область, а не село Kiyevskaya за 1500 км.

        Те саме з субʼєктами РФ, яких нема в конфізі: «Архангельская область»
        була селом за 1977 км.
        """
        for text, want in (("Киевская область фиксация самолётов F16", "Kyiv Oblast"),
                           ("Урдома, Ленский район, Архангельская область - пролёт",
                            "Arkhangelsk Oblast")):
            with self.subTest(text=text):
                self.assertIn(want, self._names(text))

    def test_uab_plural_is_uab(self):
        """«УАБы», «УАБов» — 226 подій лишались без типу; «Кабардино» — не КАБ."""
        self.assertEqual(ST.utype_of("Уабы на Гуляйполе"), "УАБ")
        self.assertEqual(ST.utype_of("Изюм Харьковская область пуск УАБов"), "УАБ")
        self.assertNotEqual(ST.utype_of("Кабардино-Балкарская Республика"), "УАБ")

    # ---- місто не програє своїй області ----

    def test_city_beats_its_own_oblast(self):
        """«из-под Чернигова» — місто Чернігів, а не Чернігівська область."""
        self.assertIn("Chernihiv", self._names(
            "Ещё пуски БПЛА из-под Чернигова в направлении Брянской области."))

    def test_adjective_stays_the_oblast(self):
        """Прикметник — це і є область; «-цкой» теж прикметник («Липецкой»)."""
        self.assertIn("Chernihiv Oblast", self._names("Черниговская область фиксация"))
        p = self._post("Тульская область / Опасность по БПЛА от Липецкой области")
        self.assertFalse(any(e.get("geo_conf") == "city-marker" and
                             e.get("geo_name") == "Lipetsk" for e in p["entities"]),
                         "назва області не має ставати містом (перша версія: +2500 подій)")

    # ---- крапка пуску — на джерелі ----

    def test_launch_origin(self):
        cases = [
            ("Ещё пуски БПЛА из-под Чернигова в направлении Брянской области.", "Chernihiv"),
            ("Пуски БПЛА от Николаевской области\nХерсонская область РФ", "Mykolayiv Oblast"),
            ("Таирово, Одесская область - пуски БПЛА в акваторию Чёрного моря.", "Tayirove"),
            ("Славянск ещё пуски РСЗО", "Slovyansk"),
        ]
        for text, want in cases:
            with self.subTest(text=text):
                o = ST.launch_origin(self._post(text))
                self.assertIsNotNone(o, "джерело назване — має бути знайдене")
                self.assertEqual(o["geo_name"], want)

    def test_source_city_is_not_a_guess(self):
        """«от Одессы» — розвʼязання за граматикою, а не здогад за населенням.

        З позначкою «global» редактор малював Одесу-джерело кільцем «здогад».
        """
        o = ST.launch_origin(self._post("Пуски БПЛА от Одессы"))
        self.assertEqual((o or {}).get("geo_name"), "Odesa")
        self.assertEqual(o["geo_conf"], "source")

    def test_target_is_not_an_origin(self):
        """Ціль і пуск із літака В БІК місця — не джерело; РФ — не джерело."""
        for text in ["Суджанский район, Курская область - ракетная опасность! Пуски с авиации.",
                     "Ещё пуски ракет в направлении Белгородской области",
                     "Шебекинский район - пуски РСЗО"]:
            with self.subTest(text=text):
                self.assertIsNone(ST.launch_origin(self._post(text)))


class TestFreeformKeepsTheSecondWord(unittest.TestCase):
    """Пара слів, що зачепила маркер області, не губить друге слово.

    «Север Крыма Джанкойский район»: вікно ставало «Крыма Джанкойский», і збіг
    відкидався цілком — разом із районом. Та сама вада діяла для будь-якої
    пари «маркер області + назва» («Брянская Климово»).
    """

    def test_second_word_survives(self):
        cfg = E.Config.load(CFG)
        for text, want in (("Север Крыма Джанкойский район приготовиться", "Джанкойский"),
                           ("Поныри Курская область в стороны Липецка", "Поныри"),
                           ("Никольское Бгд / Ударный БПЛА", "Никольское"),
                           ("Климово Брянская область", "Климово")):
            with self.subTest(text=text):
                self.assertIn(want, [e["value"] for e in E.freeform_of(text, cfg)])

    def test_compound_names_and_junk_are_not_split(self):
        """Складену назву не ріжемо, службове слово й територію не беремо.

        Перша версія поділу дала: «Геническая Горка» -> село Gorka, «Новая
        Москва» -> Novaya, «Порт Крым» -> Port, «Республики Крым» -> Respublika,
        «Приазовье Краснодарского края» -> станиця Приазовська (145 подій).
        """
        cfg = E.Config.load(CFG)
        for text, bad in (("Геническая Горка и близлежащие", "Горка"),
                          ("Можайский район, Новая Москва", "Новая"),
                          ("Порт Крым и близлежащие", "Порт"),
                          ("над территориями Курской области, Республики Крым", "Республики"),
                          ("Приазовье Краснодарский край", "Приазовье")):
            with self.subTest(text=text):
                self.assertNotIn(bad, [e["value"] for e in E.freeform_of(text, cfg)])


class TestCleanAlt(unittest.TestCase):
    """Наголоси й латинські двійники в кириличних альт-назвах GeoNames.

    «Че́рнский райо́н», «Венëвский» фільтр CYRILLIC відкидав цілком — 149
    районів для геокода не існували (BACKLOG §3, «844 відсутні райони»).
    """

    def test_accents_and_homoglyphs(self):
        for raw, want in (("Че́рнский райо́н", "Чернский район"),
                          ("Венëвский Район", "Веневский Район"),
                          ("Чeрнянский Район", "Чернянский Район"),
                          ("Йошкар-Ола", "Йошкар-Ола")):
            with self.subTest(raw=raw):
                self.assertEqual(GC.clean_alt(raw), want)
                self.assertTrue(GC.CYRILLIC.match(GC.clean_alt(raw)))

    def test_latin_name_stays_latin(self):
        self.assertEqual(GC.clean_alt("Chernsky"), "Chernsky")


class TestLeadingFunctionWord(unittest.TestCase):
    """Службове слово чи класифікатор на початку не склеюється з назвою.

    «Через Валуйский район», «Стык Хомутовский район», «Трасса Чкалово»
    ставали одним двослівним НП, якого нема, і подія падала на центр області.
    """

    def test_word_is_skipped(self):
        cfg = E.Config.load(CFG)
        for text, want in (("Через Валуйский район, Белгородской области", "Валуйский"),
                           ("Весь Лабинский район, Краснодарского края", "Лабинский"),
                           ("Стык Хомутовский район с Рыльским", "Хомутовский"),
                           ("Трасса Чкалово опасность", "Чкалово"),
                           ("Между Маловидное и Бахчисараем", "Маловидное")):
            with self.subTest(text=text):
                vals = [e["value"] for e in E.freeform_of(text, cfg)]
                self.assertIn(want, vals)
                self.assertFalse([v for v in vals if " " in v and want in v], vals)

    def test_compound_names_survive(self):
        cfg = E.Config.load(CFG)
        for text, want in (("Белой Березки группа БПЛА", "Белой Березки"),
                           ("Арабатская Стрелка опасность", "Арабатская Стрелка")):
            with self.subTest(text=text):
                self.assertIn(want, [e["value"] for e in E.freeform_of(text, cfg)])


@needs_gazetteer
class TestMorphologyFallbacks(unittest.TestCase):
    """Три шляхи, якими назва з газетира не знаходилась (21 вересня 2026)."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = E.Config.load(CFG)
        cls.gaz = GC.Gazetteer.load(GAZ / "RU.txt", GAZ / "UA.txt")
        cls.a1 = cls.gaz.region_codes(cls.cfg.entities["регіон"], cls.cfg.geo)

    def _in(self, word, reg):
        return self.gaz.lookup(word, self.cfg.geo[reg], near_a1=self.a1.get(reg))

    def test_oblique_adjective_reaches_district(self):
        """§4: «Аннинским», «Погарского» — не лише називний відмінок."""
        for word, reg in (("Аннинским", "Воронезька"), ("Погарского", "Брянська"),
                          ("Валуйского", "Бєлгородська")):
            with self.subTest(word=word):
                hit = self._in(word, reg)
                self.assertTrue(hit)
                self.assertIn((hit["cc"], hit["a1"]), self.a1[reg])

    def test_far_exact_namesake_does_not_block_stem(self):
        """«Козельский» буквально є лише селом у Сибіру — район мав знаходитись."""
        for word, reg in (("Козельский", "Калузька"), ("Вяземский", "Смоленська"),
                          ("Шиловский", "Рязанська")):
            with self.subTest(word=word):
                hit = self._in(word, reg)
                self.assertTrue(hit)
                self.assertEqual(hit["fclass"], "A")
                self.assertIn((hit["cc"], hit["a1"]), self.a1[reg])

    def test_genitive_noun(self):
        """«Одессы» — місто Одеса, не область; загальні слова селами не стають."""
        for word, name in (("Одессы", "Odesa"), ("Анапы", "Anapa"), ("Орла", "Orël"),
                           ("Качи", "Kacha")):
            with self.subTest(word=word):
                hit = self.gaz.lookup(word, None, allow_far=True)
                self.assertTrue(hit)
                self.assertEqual(hit["name"], name)
        for word in ("Шарк", "Через", "Победы", "Силы"):
            with self.subTest(word=word):
                self.assertIsNone(self.gaz.lookup(word, None, allow_far=True))

    def test_single_word_does_not_reach_compound_name(self):
        """«Большая группа БПЛА … Симферополь» — не Велика Знамʼянка.

        Точні тезки «Большая» всі далеко, і обхід за основою діставав
        «Большая Знаменка» (Запоріжжя) — за першим словом складеної назви.
        Стереже `_FEM_ADJ`: жіночий рід обходу не вмикає.
        """
        for word in ("Большая", "Старая"):
            with self.subTest(word=word):
                self.assertIsNone(self._in(word, "Крим"))


@needs_gazetteer
class TestReviewFindings(unittest.TestCase):
    """Вади, знайдені рецензією 21 вересня 2026 на першій версії правок."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = E.Config.load(CFG)
        cls.gaz = GC.Gazetteer.load(GAZ / "RU.txt", GAZ / "UA.txt")
        cls.a1 = cls.gaz.region_codes(cls.cfg.entities["регіон"], cls.cfg.geo)

    def _in(self, word, reg):
        return self.gaz.lookup(word, self.cfg.geo[reg], near_a1=self.a1.get(reg),
                               prefer_seat=True)

    def _resolve(self, text):
        posts = [{"channel": "t", "id": 1, "date": "2026-08-20T10:00:00+00:00",
                  "text": text}]
        posts = E.enrich(posts, self.cfg)
        GC.geocode_posts(posts, self.gaz, self.cfg.geo,
                         aliases=self.cfg.geo_aliases, region_a1=self.a1)
        return posts[0]

    def test_cape_and_bay_stay_in_sevastopol(self):
        """«Мыс Херсонес» — не село Херсонес у ДНР за 370 км."""
        for text in ("Мыс Херсонес, Фиолент / Фиксации БПЛА",
                     "Бухты Казачья / Пролёт БПЛА / Севастополь"):
            with self.subTest(text=text):
                p = self._resolve(text)
                pt = ST.point_entity(p)
                self.assertTrue(pt)
                self.assertLess(GC.haversine((pt["lat"], pt["lon"]), (44.6, 33.5)), 20)

    def test_noun_is_a_town_not_its_district(self):
        """«от Старобельска» — місто, а не Старобільський район (площа)."""
        hit = self._in("Старобельска", "ТОТ_Луганськ")
        self.assertEqual(hit["fclass"], "P")

    def test_road_segment_takes_first_end(self):
        hit = self._in("Луганск-Лисичанск", "ТОТ_Луганськ")
        self.assertEqual(hit["name"], "Luhansk")

    def test_compound_name_in_oblique_case(self):
        for word, reg, name in (("Великую Лепетиху", "ТОТ_Херсон", "Velyka Lepetykha"),
                                ("Белой Березки", "Брянська", "Belaya Berëzka")):
            with self.subTest(word=word):
                self.assertEqual(self._in(word, reg)["name"], name)

    def test_rivers_and_common_nouns_are_not_villages(self):
        for word in ("Днепра", "Десны", "Волги", "Славы"):
            with self.subTest(word=word):
                self.assertIsNone(self.gaz.lookup(word, None, allow_far=True))

    def test_district_word_resolved_as_town_is_still_an_area(self):
        """«Розовка, Куйбышевский район» — Розівка, а не Більмак."""
        p = self._resolve("Розовка, Куйбышевский район / Фиксация БПЛА / "
                          "Запорожская область")
        dist = [e for e in p["entities"] if e["value"] == "Куйбышевский" and "lat" in e]
        for e in dist:
            self.assertTrue(e["geo_area"])

    def test_village_is_searched_in_its_named_district(self):
        """«Васильевка, Токаревский район» — Васильєвка цього району.

        Коли район почав знаходитись як площа, село шукалось по всій області
        й діставало тезку за 130 км (друга рецензія, арбітр «названий район»).
        """
        p = self._resolve("Васильевка, Токаревский район, Тамбовская область - "
                          "пролёт от 2 БПЛА в сторону Ржакса.")
        v = next(e for e in p["entities"] if e["value"] == "Васильевка")
        d = next(e for e in p["entities"] if e["value"] == "Токаревский")
        self.assertLess(GC.haversine((v["lat"], v["lon"]), (d["lat"], d["lon"])),
                        GC.DISTRICT_SCOPE_KM)

    def test_target_in_genitive_does_not_beat_named_place(self):
        """«Ершичи … в сторону Смоленска или Рославля» — Єршичі, не Рославль.

        Родовий «Рославля» знайдено фолбеком; пряма назва стоїть вище.
        """
        p = self._resolve("Ершичи / Фиксация БПЛА в сторону Смоленска или "
                          "Рославля / Смоленская область")
        pt = ST.point_entity(p)
        self.assertEqual(pt["value"], "Ершичи")

    def test_sea_is_not_a_village(self):
        """«над Азовским морем» — не станиця Азовська."""
        p = self._resolve("БПЛА над Азовским морем в направлении "
                          "Краснодарского края")
        self.assertFalse([e for e in p["entities"]
                          if e["type"] == "нп" and "lat" in e])

    def test_hyphen_is_not_cut_inside_one_name(self):
        for word, reg in (("Ай-Петри", "Крим"), ("Князе-Григоровка", "ТОТ_Херсон")):
            with self.subTest(word=word):
                hit = self._in(word, reg)
                self.assertTrue(hit is None or hit["name"] not in ("Petri",))

    def test_district_scope_needs_village_district_format(self):
        """Ціль напрямку біля району не переноситься на тезку."""
        p = self._resolve("Валуйский район - пролёты БПЛА в сторону Старый Оскол "
                          "/ Белгородская область")
        so = [e for e in p["entities"] if e["value"].startswith("Старый")]
        for e in so:
            self.assertLess(GC.haversine((e["lat"], e["lon"]), (51.30, 37.84)), 15)

    def test_genitive_region_marker_is_not_a_city(self):
        """«в направлении Москвы» — не крапка в Москві (маркер області)."""
        p = self._resolve("Вся южная часть Московской области и в направлении "
                          "Москвы - ракетная опасность!")
        self.assertFalse([e for e in p["entities"]
                          if e.get("geo_conf") == "city-marker"])


@needs_gazetteer
class TestThirdReview(TestReviewFindings):
    """Вади, знайдені третьою рецензією 21 вересня 2026."""

    def test_only_target_outside_region_falls_back_to_area(self):
        """«Курская область — в сторону Орла»: не крапка в Орлі."""
        p = self._resolve("Через Курскую область фиксации БПЛА в сторону Орла, Тулы")
        pt = ST.point_entity(p)
        self.assertTrue(pt is None or pt.get("geo_conf") == "centroid", pt)

    def test_district_list_is_one_target_chain(self):
        """«в сторону Шаблыкинского района, Сосковского района» — обидва цілі."""
        self.assertTrue(ST.ENUM_GAP.fullmatch(" района, "))
        self.assertFalse(ST.ENUM_GAP.fullmatch(" области, "))

    def test_sea_in_instrumental_keeps_the_place(self):
        """«Западнее Тарханкута морем» — Тарханкут, а «Азовским морем» — не НП."""
        p = self._resolve("Западнее Тарханкута морем фиксации БПЛА в направлении Евпатории")
        self.assertTrue([e for e in p["entities"]
                         if e["value"].startswith("Тарханкут") and "lat" in e])
        for text in ("Фиксации БПЛА в направлении акватории Чёрного моря",
                     "БПЛА над Азовским морем в направлении Бердянска"):
            with self.subTest(text=text):
                p = self._resolve(text)
                self.assertFalse([e for e in p["entities"] if e["type"] == "нп"
                                  and "lat" in e and e["value"][:3] in ("Чёр", "Азо")])

    def test_event_carries_area_flag(self):
        """Район, розвʼязаний своїм містом, — площа й у події (поле `area`)."""
        p = self._resolve("Шацкий район / Рязанская область / Фиксация БПЛА")
        pt = ST.point_entity(p)
        self.assertTrue(pt and pt.get("geo_area"), pt)

    def test_only_target_in_region_is_marked_aim(self):
        """«Ещё фиксации БПЛА в направлении Каланчак / Херсонская область РФ» —
        крапка на цілі, але подія знає, що це ціль (`aim`)."""
        p = self._resolve("Ещё фиксации БПЛА в направлении Каланчак / "
                          "Херсонская область РФ")
        pt = ST.point_entity(p)
        self.assertTrue(pt and pt.get("_aim"), pt)
        p = self._resolve("Каланчак / Фиксации БПЛА / Херсонская область РФ")
        pt = ST.point_entity(p)
        self.assertFalse(pt.get("_aim"))

    def test_observation_place_in_oblique_case_is_found(self):
        """Місце спостереження в непрямому відмінку, що раніше губилось і
        віддавало крапку цілі: дефіс, прикметник у родовому, пара з малої."""
        for text, lat, lon in (
                ("От Каменки-Днепровской опасность по БПЛА в направлении "
                 "Мелитополя / Запорожская область РФ", 47.50, 34.41),
                ("От Малой белозерки БПЛА в сторону Мелитополя", 47.24, 34.93),
                ("От Нижнего песочного в сторону Хомутовки фиксации БПЛА "
                 "Курская область", 51.88, 34.95),
                ("От Веселого в сторону Мелитополя БПЛА", 47.01, 34.92)):
            with self.subTest(text=text[:30]):
                pt = ST.point_entity(self._resolve(text))
                self.assertTrue(pt)
                self.assertLess(GC.haversine((pt["lat"], pt["lon"]), (lat, lon)), 10, pt)

    def test_unit_word_is_not_glued_as_second_word(self):
        """«Архангельская область» — не пара «назва + слово з малої»."""
        for w in ("область", "района", "край", "полуострова"):
            self.assertTrue(GC._UNIT_NEXT.match(w), w)
        for w in ("балки", "белозерки", "песочного", "горка"):
            self.assertFalse(GC._UNIT_NEXT.match(w), w)
        p = self._resolve("Архангельская область - опасность по БПЛА")
        self.assertFalse([e for e in p["entities"] if e["type"] == "нп"
                          and "lat" in e and e.get("geo_fcode") not in ("ADM1", "ADM1H")])

    def test_ukrainian_only_name_found_by_skeleton_in_region(self):
        """«Стрелковое», «Серогозы», «Бановка» — у GeoNames лише українською
        (Стрілкове, Сірогози, Банівка). Кістяк приголосних — лише з областю
        поста й за єдиного збігу: без області він давав сміття."""
        for word, reg, name in (("Стрелковое", "ТОТ_Херсон", "Strilkove"),
                                ("Серогозы", "ТОТ_Херсон", "Sirohozy"),
                                ("Бановка", "ТОТ_Запоріжжя", "Banivka")):
            with self.subTest(word=word):
                hit = self._in(word, reg)
                self.assertTrue(hit and hit["name"] == name, hit)
                self.assertTrue(hit["morph"])
        self.assertIsNone(self.gaz.lookup("Грабер", None, allow_far=True))
        self.assertIsNone(self._in("Скорость", "Крим"))
