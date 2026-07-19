"""Геокодування: розвʼязання омонімів. Потребує газетира (132 МБ)."""
import collections
import json
import unittest

from tests.helpers import GAZ, needs_gazetteer
from tgmine import extract as E, geocode as GC
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
                          ("Ленінградська", {("RU", "42")})]:
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
