"""Розбір повідомлень і цілісність конфіга.

Кожен тест тут відповідає помилці, яка вже траплялась на реальних даних.
"""
import re
import unittest

import yaml

from tests.helpers import ROOT
from tgmine import extract as E

CFG = ROOT / "configs" / "ru-monitor.yaml"


class TestWordBoundaries(unittest.TestCase):
    """Патерн назви не має ловити середину чужого слова.

    До виправлення таких збігів було 1720 у 15 патернах: `Орск\\b` ловив
    «При|морск» і «Железног|орск» (Оренбурзька за 1500 км), `Казан\\w*` —
    звичайне слово «у|казан|иям», `Московск\\w*` — «Ново|московск» (Тульська).
    """

    @classmethod
    def setUpClass(cls):
        cls.cfg = E.Config.load(CFG)

    def regions(self, text):
        return [e["value"] for e in E.entities_of(text, self.cfg)
                if e["type"] == "регіон"]

    def test_midword_matches_are_not_entities(self):
        cases = [("Приморск обстановка", "Оренбурзька"),
                 ("Железногорск тревога", "Оренбурзька"),
                 ("даны указания по обстановке", "Татарстан"),
                 ("Новомосковск тревога", "Московська"),
                 ("Северодонецк и близлежащие", "ТОТ_Донецьк"),
                 ("Красногвардейское опасность", "Краснодарський"),
                 ("бухта Стрелецкая", "Липецька"),
                 ("Побережье до Гурзуфа", "Башкортостан")]
        for text, wrong in cases:
            with self.subTest(text=text):
                self.assertNotIn(wrong, self.regions(text),
                                 f"{wrong} впізнано з середини слова")

    def test_real_names_still_match(self):
        for text, want in [("Орск обстановка", "Оренбурзька"),
                           ("Ейск тревога", "Краснодарський"),
                           ("Казань фиксация", "Татарстан"),
                           ("Москва и область", "Московська"),
                           ("Донецк опасность", "ТОТ_Донецьк"),
                           ("Уфа тревога", "Башкортостан")]:
            with self.subTest(text=text):
                self.assertIn(want, self.regions(text))

    def test_correct_region_wins_where_it_used_to_lose(self):
        self.assertIn("ТОТ_Запоріжжя", self.regions("Приморск обстановка"))
        self.assertIn("Тульська", self.regions("Новомосковск тревога"))


class TestDirectionStoplist(unittest.TestCase):
    """Напрямок — не населений пункт.

    «Центральные районы Крыма» ставало селом Центральний на Донеччині за 354 км.
    Резолвились семеро з них, разом 90 згадок.
    """

    @classmethod
    def setUpClass(cls):
        cls.cfg = E.Config.load(CFG)

    def freeform(self, text):
        return [e["value"] for e in E.freeform_of(text, self.cfg)
                if e["type"] == "нп"]

    def test_bare_directions_are_dropped(self):
        for text in ["Центральные районы Крыма опасность по БПЛА",
                     "Запад Крыма тревога",
                     "Юго-Восток Московская область",
                     "Западные районы Брянская область",
                     "Северо-восточные районы Курская область"]:
            with self.subTest(text=text):
                got = self.freeform(text)
                first = text.split()[0]
                self.assertNotIn(first, got, f"{first!r} узято за назву НП")

    def test_real_places_with_same_root_survive(self):
        """Стоп-лист — точний збіг, тому справжні назви лишаються."""
        stop = self.cfg.freeform["нп"]["stoplist"]
        for name in ["северск", "северский", "северодонецк",
                     "северный кавказ", "северная осетия", "западнодвинский"]:
            with self.subTest(name=name):
                self.assertNotIn(name, stop)


class TestLeadingPrepositions(unittest.TestCase):
    """«От <місце>» — це МІСЦЕ спостереження, не чуже джерело.

    Перевірено на 692 постах: рядок завжди має вигляд «От <тут> у напрямку
    <туди> — що фіксують». Прийменник з'їдав вікно з двох слів, тому назва ще й
    усікалась: «От Белой» замість «Белой Березки».
    """

    @classmethod
    def setUpClass(cls):
        cls.cfg = E.Config.load(CFG)

    def freeform(self, text):
        return [e["value"] for e in E.freeform_of(text, self.cfg)
                if e["type"] == "нп"]

    def test_preposition_not_taken_as_name(self):
        for text, want in [("От Лобаново в направлении Джанкой", "Лобаново"),
                           ("От Соледар ДНР БПЛА на северо-восток", "Соледар"),
                           ("Севернее Нижнегорский тревога", "Нижнегорский"),
                           ("Западнее Целинное фиксации", "Целинное")]:
            with self.subTest(text=text):
                got = self.freeform(text)
                self.assertIn(want, got)
                self.assertFalse([g for g in got if g.startswith(("От ", "Севернее ",
                                                                 "Западнее "))],
                                 f"прийменник потрапив у назву: {got}")

    def test_two_word_name_survives(self):
        """Головне: назва не усікається до першого слова."""
        self.assertIn("Белой Березки", self.freeform("От Белой Березки группа БПЛА"))

    def test_ordinary_names_unaffected(self):
        self.assertIn("Отрадное", self.freeform("Отрадное фиксация БПЛА"))
        # двослівна назва, якої НЕМА серед патернів регіонів: «Нижний Новгород»
        # для цього не годиться — він розпізнається як Нижегородська й тому
        # свідомо не потрапляє у freeform
        self.assertIn("Белая Калитва", self.freeform("Белая Калитва тревога"))

    def test_word_starting_with_a_preposition_is_not_skipped(self):
        """`(?!От\\b)` вимагає межу слова, тож «Отрадное» не блокується."""
        for text, want in [("Отрадное фиксация", "Отрадное"),
                           ("Задонск тревога", "Задонск"),
                           ("Изюм опасность", "Изюм")]:
            with self.subTest(text=text):
                self.assertIn(want, self.freeform(text))


class TestConfigIntegrity(unittest.TestCase):
    """Те, що легко зламати правкою YAML."""

    @classmethod
    def setUpClass(cls):
        cls.raw = yaml.safe_load(CFG.read_text(encoding="utf-8"))
        cls.cfg = E.Config.load(CFG)

    def test_every_region_has_a_centroid(self):
        regions = set(self.raw["entities"]["регіон"])
        geo = set(self.raw["geo"])
        self.assertEqual(regions - geo, set(), "регіон без geo-центроїда")
        self.assertEqual(geo - regions, set(), "geo без регіону")

    def test_no_duplicate_region_definitions(self):
        """`Саратовська2` дублювала `Саратовську` з тим самим патерном."""
        seen = {}
        for name, pats in self.raw["entities"]["регіон"].items():
            key = tuple(sorted(pats))
            self.assertNotIn(key, seen,
                             f"{name} має ті самі патерни, що й {seen.get(key)}")
            seen[key] = name

    def test_no_numeric_suffix_regions(self):
        for name in self.raw["entities"]["регіон"]:
            self.assertFalse(re.search(r"\d$", name),
                             f"{name}: цифра в кінці зазвичай означає копію")

    def test_all_patterns_compile(self):
        for section in ("tags", "modifiers"):
            for key, pats in (self.raw.get(section) or {}).items():
                for p in pats:
                    with self.subTest(section=section, key=key, pattern=p):
                        re.compile(p)
        for etype, values in self.raw["entities"].items():
            for key, pats in values.items():
                for p in pats:
                    with self.subTest(entity=key, pattern=p):
                        re.compile(p)

    def test_centroids_are_inside_the_theater(self):
        from tgmine.geocode import in_box
        for name, (lat, lon) in self.raw["geo"].items():
            with self.subTest(region=name):
                self.assertTrue(in_box(lat, lon),
                                f"{name} {lat},{lon} поза THEATER — газетир її не віддасть")


if __name__ == "__main__":
    unittest.main()
