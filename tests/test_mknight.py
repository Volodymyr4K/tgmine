"""Заготовки для редактора з даних ночі: mapper/mknight.py."""
import unittest

from tests.helpers import load_script


class TestBearings(unittest.TestCase):
    """Курси словами йдуть у ніч лише з точок у місці, згортаючись по місцю
    й курсу — так само, як позначки збиття."""

    @classmethod
    def setUpClass(cls):
        cls.mk = load_script("mapper/mknight.py")

    def _ev(self, lat, lon, bearing, conf="region", scope="точка", **kw):
        e = {"lat": lat, "lon": lon, "bearing": bearing, "scope": scope,
             "geo_conf": conf, "place": "Unecha", "hhmm": "01:15",
             "url": "https://t.me/locatorru/1", "kind": "фіксація"}
        e.update(kw)
        return e

    def test_groups_same_place_and_course(self):
        raid = {"events": [self._ev(52.85, 32.67, 0, url="https://t.me/a/1"),
                           self._ev(52.85, 32.67, 0, url="https://t.me/a/2"),
                           self._ev(52.85, 32.67, 90, url="https://t.me/a/3")]}
        out = self.mk.bearings(raid)
        self.assertEqual(sorted((b["deg"], b["n"]) for b in out), [(0, 2), (90, 1)])
        north = next(b for b in out if b["deg"] == 0)
        self.assertEqual([s["u"] for s in north["src"]],
                         ["https://t.me/a/1", "https://t.me/a/2"])
        self.assertEqual(north["place"], "Унеча")

    def test_only_located_points_with_a_course(self):
        raid = {"events": [self._ev(52.85, 32.67, None),
                           self._ev(52.85, 32.67, 45, conf="centroid"),
                           self._ev(52.85, 32.67, 45, conf="region-snap"),
                           self._ev(52.85, 32.67, 45, scope="область"),
                           self._ev(None, None, 45)]}
        self.assertEqual(self.mk.bearings(raid), [])

    def test_sightings_group_by_place_and_carry_times_and_kinds(self):
        """Фіксації ночі: одна крапка на місце, усі часи (для фільтра годин),
        склад за видами, найчастіший курс, центр району — позначений."""
        raid = {"events": [
            self._ev(52.85, 32.67, None, url="https://t.me/a/1", hhmm="23:40"),
            self._ev(52.85, 32.67, 45, url="https://t.me/a/2", hhmm="01:15", kind="ППО"),
            self._ev(52.85, 32.67, 45, url="https://t.me/a/3", hhmm="00:10"),
            self._ev(51.56, 34.68, None, place="Ryl’skiy Rayon", hhmm="02:00"),
            self._ev(50.60, 36.58, None, conf="global", hhmm="02:30"),
            self._ev(50.60, 36.58, None, conf="centroid", hhmm="02:31"),
            self._ev(50.60, 36.58, None, scope="область", hhmm="02:32"),
            self._ev(50.60, 36.58, None, kind="тривога", hhmm="02:33")]}
        out = self.mk.sightings(raid)
        self.assertEqual([(s["n"], s["area"]) for s in out],
                         [(3, ""), (1, "район"), (1, "здогад")])
        u = out[0]
        # ніч іде через північ: 23:40 раніше за 00:10
        self.assertEqual(u["ts"], ["23:40", "00:10", "01:15"])
        self.assertEqual((u["t0"], u["t1"]), ("23:40", "01:15"))
        self.assertEqual(u["kinds"], {"фіксація": 2, "ППО": 1})
        self.assertEqual(u["types"], {})            # без типу — порожньо, не None
        self.assertEqual(u["deg"], 45)
        self.assertEqual(u["place"], "Унеча")
        self.assertEqual(len(u["src"]), 3)

    def test_sightings_aim_only_when_every_message_is_a_target(self):
        """«Курс на X» — лише коли ВСІ повідомлення місця кажуть «туди летять»;
        хоч одне «тут бачили» робить його місцем."""
        raid = {"events": [
            self._ev(46.25, 33.29, None, aim=True, url="https://t.me/a/1"),
            self._ev(46.25, 33.29, None, aim=True, url="https://t.me/a/2"),
            self._ev(52.85, 32.67, None, aim=True, url="https://t.me/a/3"),
            self._ev(52.85, 32.67, None, url="https://t.me/a/4")]}
        out = {s["la"]: s["aim"] for s in self.mk.sightings(raid)}
        self.assertEqual(out, {46.25: True, 52.85: False})

    def test_alerts_onsets_muted_silent(self):
        """Старти тривог: кожна область із тексту, старт після ≥3 год тиші,
        «після відбою», німа область без фіксацій, суцільна — у muted."""
        def al(t, text, kind="тривога", url="https://t.me/a/1"):
            return {"scope": "область", "kind": kind, "t": f"2026-09-08T{t}:00+03:00",
                    "hhmm": t, "text": text, "url": url, "region": None}
        raid = {"events": [
            # Тамбовська й Липецька одним постом; нагадування через 40 хв
            # тримає тривогу чинною; 04:30 — через 3.5 год тиші, новий старт
            al("00:19", "Тамбовская область, Липецкая область - опасность по БПЛА"),
            al("01:00", "Тамбовская область - напоминаем, действует тревога"),
            al("04:30", "Тамбовская область - опасность по БПЛА", url="https://t.me/a/2"),
            # Пензенська: відбій між тривогами
            al("01:38", "Пензенская область - опасность по БПЛА"),
            al("03:00", "Пензенская область - отбой опасности", kind="відбій"),
            al("06:00", "Пензенская область - опасность по БПЛА"),
            # Курська: тривога з 12:00 щогодини всю ніч — суцільна
            *[al(f"{h % 24:02d}:00", "Курская область / Опасность по БПЛА")
              for h in range(12, 36)],
            # область після «от» — джерело, не старт: Ульяновська й
            # Самарська тут не тривожать
            al("02:00", "Республика Татарстан - опасность по БПЛА от Ульяновской "
                        "и Самарской областей."),
            # нагадування як ПЕРШЕ повідомлення області — старт був до доби,
            # старту нема
            al("03:30", "Рязанская область - тревога по БПЛА сохраняется"),
            # фіксація в Пензенській — область не німа
            self._ev(53.2, 45.0, None, region="Пензенська", hhmm="01:50")]}
        out = self.mk.alerts(raid)
        rows = [(o["t"], o["reg"], o["silent"], o["otboy"]) for o in out["onsets"]
                if o["reg"] not in out["muted"]]
        self.assertEqual(rows, [("00:19", "Липецька", True, False),
                                ("00:19", "Тамбовська", True, False),
                                ("01:38", "Пензенська", False, False),
                                ("02:00", "Татарстан", True, False),
                                ("04:30", "Тамбовська", True, False),
                                ("06:00", "Пензенська", False, True)])
        self.assertNotIn("Ульяновська", out["cover"])
        self.assertNotIn("Самарська", out["cover"])
        self.assertNotIn("Рязанська", [o["reg"] for o in out["onsets"]])
        self.assertEqual(out["muted"], ["Курська"])
        self.assertGreaterEqual(out["cover"]["Курська"], 12)
        self.assertIn("Тамбовська", out["anchors"])
        tam = [o for o in out["onsets"] if o["reg"] == "Тамбовська"][1]
        self.assertEqual(tam["src"][0]["u"], "https://t.me/a/2")
        self.assertEqual(tam["name"], "Тамбовська обл.")

    def test_night_carries_bearings_key(self):
        """Ніч без курсів має порожній список, а не відсутній ключ: редактор
        читає `NIGHT.bearings` і рахує його в списку ночей."""
        import inspect
        src = inspect.getsource(self.mk.main)
        self.assertIn('"bearings": br', src)


if __name__ == "__main__":
    unittest.main()


class TestTypes(unittest.TestCase):
    """Тип засобу (store.utype) доходить до кожного шару ночі: без нього
    ракета на карті виглядала як дрон. Ніч 10→11 вересня 2026: 12 Фламінго
    на Ростовську й Волгоградську стояли як «фіксація» й «збиття»."""

    @classmethod
    def setUpClass(cls):
        cls.mk = load_script("mapper/mknight.py")

    def _ev(self, lat, lon, utype, kind="фіксація", **kw):
        e = {"lat": lat, "lon": lon, "bearing": None, "scope": "точка",
             "geo_conf": "city-marker", "place": "Volgograd", "hhmm": "03:35",
             "url": "https://t.me/locatorru/1", "kind": kind, "utype": utype}
        e.update(kw)
        return e

    def test_sightings_count_types_and_sources_carry_them(self):
        raid = {"events": [self._ev(48.71, 44.50, "Фламінго", url="https://t.me/a/1"),
                           self._ev(48.71, 44.50, "Фламінго", url="https://t.me/a/2"),
                           self._ev(48.71, 44.50, "ракета", url="https://t.me/a/3"),
                           self._ev(48.71, 44.50, None, url="https://t.me/a/4")]}
        s = self.mk.sightings(raid)[0]
        self.assertEqual(s["types"], {"Фламінго": 2, "ракета": 1})
        self.assertEqual([q["ty"] for q in s["src"]], ["Фламінго", "Фламінго", "ракета", None])

    def test_strikes_carry_types(self):
        raid = {"events": [self._ev(48.71, 44.50, "Фламінго", kind="збиття"),
                           self._ev(48.71, 44.50, "БпЛА", kind="ППО")]}
        st = self.mk.strikes(raid)
        self.assertEqual(len(st), 1)
        self.assertEqual(st[0]["types"], {"Фламінго": 1, "БпЛА": 1})
        self.assertEqual(st[0]["src"][0]["ty"], "Фламінго")

    def test_alert_onset_carries_type(self):
        raid = {"events": [
            {"scope": "область", "kind": "тривога", "t": "2026-09-11T03:35:00+03:00",
             "hhmm": "03:35", "utype": "крилата ракета", "region": None,
             "text": "Волгоградская область - ракетная опасность по крылатым ракетам!",
             "url": "https://t.me/locatorru/84693"}]}
        al = self.mk.alerts(raid)
        self.assertEqual(len(al["onsets"]), 1)
        self.assertEqual(al["onsets"][0]["ty"], "крилата ракета")
        self.assertEqual(al["onsets"][0]["src"][0]["ty"], "крилата ракета")


class TestAreaNameLatin(unittest.TestCase):
    """«Gorodskoy Okrug Chekhov», «Mikhaylovka Urban Okrug» — площа, не крапка."""

    def test_latin_unit_words(self):
        from mapper import mknight as MK
        for name in ("Gorodskoy Okrug Chekhov", "Mikhaylovka Urban Okrug",
                     "Kharkiv Oblast", "Kozel’skiy Rayon"):
            with self.subTest(name=name):
                self.assertTrue(MK.AREA_NAME.search(name))
        self.assertFalse(MK.AREA_NAME.search("Okhtyrka"))


class TestLabelsUk(unittest.TestCase):
    """Підписи місць у редакторі: родові слова — перекладом, кирилиця — як є."""

    def test_unit_words_are_translated(self):
        from mapper.labels import uk
        for name, want in (("Chernsky District", "Чернський район"),
                           ("Kromskoy Rayon", "Кромський район"),
                           ("Gorodskoy Okrug Chekhov", "міський округ Чехов"),
                           ("Kharkiv Oblast", "Харківська обл.")):
            with self.subTest(name=name):
                self.assertEqual(uk(name), want)

    def test_cyrillic_alias_keeps_its_name(self):
        """Аліас «Бельбек» транслітом ставав порожнім підписом."""
        from mapper.labels import uk
        self.assertEqual(uk("Бельбек"), "Бельбек")


class TestLinkedAlerts(unittest.TestCase):
    """Тривога в місці йде у свідчення, лише коли звʼязана з рухом."""

    @classmethod
    def setUpClass(cls):
        global MK
        MK = load_script("mapper/mknight.py")

    def _ev(self, kind, text, lat, lon, t, scope="область", conf="region"):
        return {"kind": kind, "text": text, "lat": lat, "lon": lon, "t": t,
                "scope": scope, "geo_conf": conf, "hhmm": t[11:16], "place": "X",
                "url": "u", "aim": False}

    def test_declared_movement_links(self):
        e = self._ev("тривога", "Кромы и далее на Орёл тревога по БПЛА", 52.69, 35.79,
                     "2026-07-28T01:04:00+03:00")
        self.assertIn(id(e), MK._linked_alerts([e]))

    def test_nearby_observation_links_far_one_does_not(self):
        fix = self._ev("фіксація", "Азов / фиксация", 47.10, 39.42,
                       "2026-07-28T04:10:00+03:00", scope="точка")
        near = self._ev("тривога", "Азов - опасность по БПЛА", 47.11, 39.43,
                        "2026-07-28T04:17:00+03:00")
        late = self._ev("тривога", "Азов - опасность по БПЛА", 47.11, 39.43,
                        "2026-07-28T06:17:00+03:00")
        far = self._ev("тривога", "Сальск - опасность по БПЛА", 46.47, 41.54,
                       "2026-07-28T04:17:00+03:00")
        got = MK._linked_alerts([fix, near, late, far])
        self.assertEqual(got, {id(near)})

    def test_bare_post_alert_never_links(self):
        """Голий пост-тривога (`kind_ctx`) у свідчення не йде навіть поруч зі
        спостереженням: цю ознаку заміряно й відкинуто (BACKLOG, v27)."""
        fix = self._ev("фіксація", "Азов / фиксация", 47.10, 39.42,
                       "2026-07-28T04:10:00+03:00", scope="точка")
        bare = dict(self._ev("тривога", "Азов / Ростовская область", 47.11, 39.43,
                             "2026-07-28T04:17:00+03:00"), kind_ctx="—")
        self.assertEqual(MK._linked_alerts([fix, bare]), set())

    def test_bare_post_alert_is_not_an_onset(self):
        """Одна голa тривога без відбою розтягувала покриття на всю ніч."""
        ev = {"scope": "область", "kind": "тривога", "t": "2026-09-11T13:54:00+03:00",
              "hhmm": "13:54", "region": None, "kind_ctx": "—",
              "text": "Ленинградская область / Санкт-Петербург", "url": "u"}
        self.assertEqual(MK.alerts({"events": [ev]})["onsets"], [])
        ev["kind_ctx"] = None
        self.assertEqual(len(MK.alerts({"events": [ev]})["onsets"]), 1)

    def test_region_centre_never_links(self):
        e = self._ev("тривога", "Курская область, далее на Орёл", 51.7, 36.2,
                     "2026-07-28T01:04:00+03:00", conf="centroid")
        self.assertEqual(MK._linked_alerts([e]), set())


class TestAlsoPlaces(unittest.TestCase):
    """Інші місця «тут» поста (`also`) — окремі свідчення."""

    @classmethod
    def setUpClass(cls):
        cls.mk = load_script("mapper/mknight.py")

    def test_each_also_place_is_a_sighting(self):
        e = {"kind": "фіксація", "scope": "точка", "lat": 51.73, "lon": 36.19,
             "geo_conf": "region", "place": "Kursk", "t": "2026-09-10T22:00:00+03:00",
             "hhmm": "22:00", "url": "u", "text": "Курск / Курчатов / Дмитриев / Фиксации",
             "also": [["Kurchatov", 51.66, 35.65, False], ["Dmitriyev", 52.13, 35.08, False]]}
        raid = {"events": [e], "_uk": type("N", (), {"place": lambda self, n, a, b: n})()}
        got = sorted(s["place"] for s in self.mk.sightings(raid))
        self.assertEqual(got, ["Dmitriyev", "Kurchatov", "Kursk"])


class TestTowardRegions(unittest.TestCase):
    """Жирна стрілка «звідси — на область» з ланок руху (`legs`)."""

    @classmethod
    def setUpClass(cls):
        cls.mk = load_script("mapper/mknight.py")

    def _raid(self, legs):
        ev = [{"legs": [g], "url": f"u{i}", "hhmm": "22:00", "kind": "фіксація"}
              for i, g in enumerate(legs)]
        return {"events": ev, "_uk": type("N", (), {"place": lambda self, n, a, b: n})()}

    def test_arrow_points_toward_region_and_stops_short(self):
        # Юдановка (Воронезька) -> Тамбовська
        r = self._raid([["Yudanovka", 51.2, 40.0, False, "Тамбовська", 52.7, 41.4, True]])
        a = self.mk.toward_regions(r)
        self.assertEqual(len(a), 1)
        self.assertTrue(0 < a[0]["deg"] < 90)         # на північний схід
        self.assertLessEqual(a[0]["km"], self.mk.TOWARD_KM)

    def test_tail_inside_target_region_gives_no_arrow(self):
        # старт у Криму, «…в направлении Крыма»
        r = self._raid([["Dzhankoy", 45.71, 34.39, False, "Крим", 45.3, 34.4, True]])
        self.assertEqual(self.mk.toward_regions(r), [])

    def test_area_tail_gives_no_arrow(self):
        r = self._raid([["Ростовська", 47.7, 40.7, True, "Волгоградська", 49.7, 44.0, True]])
        self.assertEqual(self.mk.toward_regions(r), [])

    def test_near_tails_to_same_region_merge(self):
        # два сусідні села Воронезької (≤30 км) -> Тамбовська
        g1 = ["A", 51.20, 40.00, False, "Тамбовська", 52.7, 41.4, True]
        g2 = ["B", 51.30, 40.15, False, "Тамбовська", 52.7, 41.4, True]
        a = self.mk.toward_regions(self._raid([g1, g2]))
        self.assertEqual([x["n"] for x in a], [2])

    def test_chain_tail_moves_to_the_observed_root(self):
        # «Юдановка … на Анна, далее на Тамбовскую область»: хвіст — Юдановка
        ev = {"url": "u", "hhmm": "22:00", "kind": "фіксація", "legs": [
            ["Yudanovka", 51.2, 40.0, False, "Anna", 51.48, 40.43, False],
            ["Anna", 51.48, 40.43, False, "Тамбовська", 52.7, 41.4, True]]}
        r = {"events": [ev], "_uk": type("N", (), {"place": lambda self, n, a, b: n})()}
        a = self.mk.toward_regions(r)
        self.assertEqual([(x["place"], x["la"]) for x in a], [("Yudanovka", 51.2)])

    def test_merged_arrow_spans_all_its_hours(self):
        g = ["A", 51.2, 40.0, False, "Тамбовська", 52.7, 41.4, True]
        ev = [{"url": f"u{i}", "hhmm": t, "kind": "фіксація", "legs": [g]}
              for i, t in enumerate(["23:10", "01:40", "22:05"])]
        r = {"events": ev, "_uk": type("N", (), {"place": lambda self, n, a, b: n})()}
        a = self.mk.toward_regions(r)[0]
        self.assertEqual((a["t"], a["t1"]), ("22:05", "01:40"))

    def test_cone_reaches_the_region_it_names(self):
        """Конус мусить ДІЙТИ до своєї області, хоч би як далеко вона була.

        Межа довжини 260 км лишала конус, який до названої області не
        доходив узагалі: замір 22.09.2026 на 122 конусах пʼяти ночей знайшов
        12 таких («→ Калузька» з Брянщини лежав у Брянській на 84%, у
        Калузькій на 0%). Тепер обмежена ПЛОЩА, а не довжина."""
        # область — квадрат 2°×2° за ~600 км на північ від вершини
        ring = [[56.0, 39.0], [56.0, 41.0], [58.0, 41.0], [58.0, 39.0], [56.0, 39.0]]
        cone = self.mk._cone(50.0, 40.0, [ring], (57.0, 40.0))
        arc = cone[1:]
        far = max(self.mk.RT.hav((50.0, 40.0), tuple(p)) for p in arc)
        near = min(self.mk.RT.hav((50.0, 40.0), (p[0], p[1])) for r in [ring] for p in r)
        self.assertGreaterEqual(far, near, "конус не дійшов до своєї області")

    def _cone_area(self, la, lo, cone):
        import math
        arc = cone[1:]
        rad = max(self.mk.RT.hav((la, lo), tuple(p)) for p in arc)
        half = abs(((self.mk.RT.bearing((la, lo), tuple(arc[-1]))
                     - self.mk.RT.bearing((la, lo), tuple(arc[0])) + 540) % 360) - 180) / 2
        return math.pi * rad * rad * (2 * half) / 360.0

    def test_far_wide_region_narrows_instead_of_covering_the_theatre(self):
        """Широка далека область дістає ВУЗЬКУ довгу стрілку.

        Стеля стоїть на площі: розхил у кутовий розмір області (до 30°) на
        700 км накрив би 130 тис. км² — пів театру однією підказкою."""
        wide = [[56.0, 33.0], [56.0, 48.0], [58.0, 48.0], [58.0, 33.0], [56.0, 33.0]]
        cone = self.mk._cone(50.0, 40.0, [wide], (57.0, 40.0))
        # Межа ЛІТЕРАЛОМ, а не з модуля: перша версія тесту звіряла зі
        # самою константою й мовчки проходила, коли стелю піднімали.
        self.assertLessEqual(self._cone_area(50.0, 40.0, cone), 30000.0)

    def test_chain_walk_stops_before_an_area_source(self):
        # «Тамбовская область … через Токарёвский район … на Рязанскую»
        ev = {"url": "u", "hhmm": "22:00", "kind": "фіксація", "legs": [
            ["Тамбовська", 52.7, 41.4, True, "Tokarevskiy", 51.9, 41.2, False],
            ["Tokarevskiy", 51.9, 41.2, False, "Рязанська", 54.4, 40.6, True]]}
        r = {"events": [ev], "_uk": type("N", (), {"place": lambda self, n, a, b: n})()}
        self.assertEqual([x["place"] for x in self.mk.toward_regions(r)], ["Tokarevskiy"])


class TestBridgedRouteFields(unittest.TestCase):
    """Зведений містком маршрут бере поля з УСІХ фрагментів."""

    def test_strongest_conf_and_named_type_win(self):
        mk = load_script("mapper/mknight.py")
        from tgmine import linker as LK
        old = LK.link_corridors
        LK.link_corridors = lambda rs, prior: [(0, 1, 5)]
        try:
            pt = lambda la, t: {"la": la, "lo": 40.0, "hhmm": t}
            rs = [{"pts": [pt(49.0, "22:00"), pt(50.0, "23:00")], "legs": ["seen"],
                   "conf": "weak", "u": "БпЛА", "k": "БПЛА", "km": 111, "t1": "23:00"},
                  {"pts": [pt(51.0, "23:40"), pt(52.0, "00:30")], "legs": ["seen"],
                   "conf": "strong", "u": "Дартс", "k": "БПЛА", "km": 111, "t1": "00:30"}]
            out = mk.with_bridges({"date": "2026-09-21"}, rs)
        finally:
            LK.link_corridors = old
        self.assertEqual(len(out), 1)
        m = out[0]
        self.assertEqual((m["conf"], m["u"], m["t1"]), ("strong", "Дартс", "00:30"))
        self.assertEqual(m["legs"], ["seen", "bridge", "seen"])
        self.assertEqual(m["bridges"], [{"at": 1, "nights": 5}])
