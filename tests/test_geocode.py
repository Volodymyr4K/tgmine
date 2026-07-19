"""Геокодування: розвʼязання омонімів. Потребує газетира (132 МБ)."""
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
