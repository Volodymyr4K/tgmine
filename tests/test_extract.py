"""Розбір повідомлень і цілісність конфіга.

Кожен тест тут відповідає помилці, яка вже траплялась на реальних даних.
"""
import json
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

    def test_centroids_are_inside_their_own_region(self):
        """Центроїд області лежить у її ж полігоні з regions.json.

        Раніше тут стояла рамка THEATER, і вона забороняла Урал узагалі. Рамка
        тепер діє лише для пошуку без області, а центроїд має інший інваріант:
        від нього store._event міряє санітарні 400 км, тож центр поза власною
        областю мовчки відкочував би всі її точки. Для ХМАО і ЯНАО центр
        навмисно не адмінцентр (Салехард лежить на краю округу) — саме тому
        перевіряється полігон, а не збіг зі столицею.
        """
        from tgmine.geocode import haversine
        from tgmine.territory import _in_ring_latlon
        regions = json.loads((ROOT / "regions.json").read_text(encoding="utf-8"))
        for name, (lat, lon) in self.raw["geo"].items():
            with self.subTest(region=name):
                rings = regions.get(name)
                self.assertTrue(rings, f"{name}: нема полігону в regions.json — "
                                       "додати в MATCH у mkregions.py")
                inside = any(_in_ring_latlon(lat, lon, r) for r in rings)
                # Спрощений контур (Дуглас-Пекер) зрізає кути: центроїд
                # Херсонщини стоїть за 3 км від краю — тому допуск до вершини
                edge = min(haversine((lat, lon), tuple(v)) for r in rings for v in r)
                self.assertTrue(inside or edge <= 30,
                                f"{name} {lat},{lon} поза власним полігоном "
                                f"({edge:.0f} км до контуру)")


if __name__ == "__main__":
    unittest.main()


class TestKrasnoarmeysk(unittest.TestCase):
    """Однойменні місця в пʼятьох регіонах: іменник — Донеччина, решта — ні.

    `Красноармейск\\w*` стояв у ТОТ_Донецьк і згрібав усі форми. Заміряно на
    45 добах: область поста визначило це слово у 162 постах, і в 100 з них
    помилково. Розклад: «Красноармейск» 62 — Донеччина 62 з 62;
    «Красноармейский» 93 — Кубань 84, ще Волгоград і Саратов;
    «Красноармейское» 7 — Крим і Чувашія. Після правки 84 пости їдуть на
    Кубань, 5 у Волгоградську, 4 в Саратовську, 4 в Крим, а 62 донецькі
    лишаються донецькими.

    Тексти дослівні з `data/`.
    """

    @classmethod
    def setUpClass(cls):
        cls.cfg = E.Config.load(CFG)

    def first_region(self, text):
        rs = [e["value"] for e in E.entities_of(text, self.cfg)
              if e["type"] == "регіон"]
        return rs[0] if rs else None

    def test_noun_is_donetsk(self):
        for text in ["Красноармейск ДНР активность БПЛА Хорнет",
                     "Константиновка, Красноармейск, Артемовск и близлежащие "
                     "тревога по УАБ"]:
            with self.subTest(text=text):
                self.assertEqual(self.first_region(text), "ТОТ_Донецьк")

    def test_adjective_is_kuban(self):
        self.assertEqual(
            self.first_region("Чебургольская, Красноармейский район, "
                              "Краснодарский край - пролёт БПЛА.\n📡\n"
                              "Локатор России -\n@locatorru"),
            "Краснодарський")

    def test_namesake_districts_keep_their_own_oblast(self):
        """Волгоград і Саратов називають своє одразу після району."""
        self.assertEqual(
            self.first_region("Тракторный район, Волгоград\nБПЛА в направлении "
                              "Волжский/Красноармейский\nВолгоградская область"),
            "Волгоградська")
        self.assertEqual(
            self.first_region("Красноармейский район\nРовенский район\n"
                              "Саратовская область\nФиксация группы БПЛА"),
            "Саратовська")

    def test_neuter_form_is_not_donetsk(self):
        """«Красноармейское» — кримське село, а не Покровськ."""
        self.assertEqual(
            self.first_region("Красноармейское\nВишневка\nИсточное\nВоинка\n"
                              "Новопавловка\nИшунь и близлежащие\n"
                              "Республика Крым\nТревога по БПЛА"), "Крим")


class TestAdjectiveHomonyms(unittest.TestCase):
    """`\\w*` на назві-прикметнику склеює кілька регіонів.

    Той самий клас, що «Красноармейск» вище і «Ивановск»/«Ленинградск» у
    конфізі. Заміряно на 45 добах, скільки постів область отримувала хибно:
    «Крымский район» (Кубань) -> Крим 65; «Свердловская область» (Урал) і
    «Свердловский район» (Орловська) -> ТОТ_Луганськ 183; «Новотроицкое»
    (Херсонщина) -> Оренбурзька 77; «Дубенский район» (Тульська) ->
    Мордовія 23. Разом 348 постів, і кожен їхав за сотні кілометрів.

    Тексти дослівні з `data/`.
    """

    @classmethod
    def setUpClass(cls):
        cls.cfg = E.Config.load(CFG)

    def first_region(self, text):
        rs = [e["value"] for e in E.entities_of(text, self.cfg)
              if e["type"] == "регіон"]
        return rs[0] if rs else None

    def test_wrong_region_no_longer_wins(self):
        for text, wrong in [
            ("Темрюкский район | Крымский район | Северский район | "
             "Краснодарский край | Опасность по БПЛА", "Крим"),
            ("Свердловская область | Ракетная опасность", "ТОТ_Луганськ"),
            ("Свердловский район | Орловская область | Фиксация БПЛА",
             "ТОТ_Луганськ"),
            ("Новотроицкое и близлежащие | Херсонская область РФ",
             "Оренбурзька"),
            # Навіть називний відмінок — Херсонщина в 17 випадках із 25,
            # тому «Новотроицк\\w*» знято з Оренбурзької повністю.
            ("Новотроицк, Новоалексеевка, Геническ и близлежащие\n"
             "Опасность по БПЛА", "Оренбурзька"),
            ("Дубенский район | Тульская область | Фиксация от 2 БПЛА",
             "Мордовія"),
            # Уральські області додано 9 вересня 2026; ці тезки на них
            # спіймано збіркою архіву ще до коміту.
            ("Матвеево-Курганский район / Ростовская область / Работа ПВО",
             "Курганська"),
            ("Курганский район Краснодарский край - БПЛА противника",
             "Курганська"),
            ("Березники, Рыльский район / Опасность по БПЛА Дартс",
             "Пермський"),
            ("Красный Луч, Ровеньки ЛНР, Свердловск и близлежащие",
             "Свердловська"),
        ]:
            with self.subTest(text=text[:40]):
                self.assertNotEqual(self.first_region(text), wrong)

    def test_ural_regions_are_recognised(self):
        """До 9 вересня 2026 постів про Урал і Західний Сибір область не
        отримувала жодна: субʼєктів не було в конфізі, і «Новый Уренгой»
        лишався без координат, а «Сургут» ставав селом у Самарській."""
        for text, want in [
            ("Новый Уренгой / Ямало-Ненецкий автономный округ / Фиксации БПЛА",
             "ЯНАО"),
            ("Тюменская область и ХМАО Опасность по БПЛА", "Тюменська"),
            ("Сургут / Ханты-Мансийск", "ХМАО"),
            ("Свердловская область / Пермский край", "Свердловська"),
            ("г.Екатеринбург - меры предосторожности при БПЛА", "Свердловська"),
            ("Матвеево-Курганский район / Ростовская область", "Ростовська"),
            ("Курганская область - опасность по БПЛА от Тюменской области",
             "Курганська"),
            ("Омская область", "Омська"),
            ("Челябинская область / Отбой опасности по БПЛА", "Челябінська"),
        ]:
            with self.subTest(text=text[:40]):
                self.assertEqual(self.first_region(text), want)

    def test_luhanske_village_is_not_luhansk(self):
        """«Луганское» — село під Джанкоєм або під Дебальцевим, не Луганщина."""
        self.assertEqual(self.first_region(
            "Луганское / Новокрымское и близлежащие / Опасность по БПЛА / "
            "Республика Крым"), "Крим")
        self.assertEqual(self.first_region(
            "Еленовка, Луганское ДНР ещё группа БПЛА на восток, ю-в"),
            "ТОТ_Донецьк")
        self.assertEqual(self.first_region(
            "С запада фиксации БПЛА на Станица Луганская, ЛНР далее на "
            "Чертково, Миллерово"), "ТОТ_Луганськ")

    def test_the_real_place_still_matches(self):
        for text, want in [
            ("Керченский полуостров | Керчь | Крымский мост | Опасность по БПЛА",
             "Крим"),
            ("Налёт БПЛА на Крымский полуостров. Работает ПВО.", "Крим"),
            ("Свердловск и близлежащие опасность по БПЛА | ЛНР", "ТОТ_Луганськ"),
            # Оренбурзькі пости не втрачають нічого: всі називають свою
            # область або Орськ у тому ж тексті.
            ("Новотроицк, Оренбургская область - БПЛА на г.Орск.\n📡\n"
             "Локатор России -\n@locatorru", "Оренбурзька"),
        ]:
            with self.subTest(text=text[:40]):
                self.assertEqual(self.first_region(text), want)


class TestVolzhsk(unittest.TestCase):
    """Волжский (Волгоградська) і Волжск (Марій Ел) — різні місця за 600 км.

    `Волжск\\w*` брав обидва: 13 постів про Марій Ел їхали у Волгоградську, і
    через це «Волжск, Республика Марий Эл - пролёт в сторону Казань» шукав
    Казань біля Волгограда й не знаходив. Тексти дослівні з `data/`.
    """

    @classmethod
    def setUpClass(cls):
        cls.cfg = E.Config.load(CFG)

    def first_region(self, text):
        rs = [e["value"] for e in E.entities_of(text, self.cfg)
              if e["type"] == "регіон"]
        return rs[0] if rs else None

    def test_volzhsky_city_is_volgograd(self):
        self.assertEqual(self.first_region(
            "Волжский, Волгоградская область\nРабота ПВО по БПЛА"), "Волгоградська")

    def test_mari_el_is_not_volgograd(self):
        for text in ["Волжский район\nРеспублика Марий Эл\nФиксация БПЛА",
                     "Волжск, Республика Марий Эл - пролёт от 11 БПЛА в сторону "
                     "Казань, Зеленодольск."]:
            with self.subTest(text=text[:30]):
                self.assertNotEqual(self.first_region(text), "Волгоградська")
