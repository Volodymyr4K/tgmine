"""Сховище подій: класифікація, ідентифікатори цілей, межа доби."""
import json
import unittest
from datetime import datetime, timedelta, timezone

from tests.helpers import ROOT, load_script, needs_store
from tgmine import store as ST


class TestKindNegation(unittest.TestCase):
    """«Ложные фиксации» — це спростування, а не спостереження.

    Правило вимагає заперечення ВПРИТУЛ перед тригером. У корпусі 28 постів зі
    словом «ложн*», але лише 3 — справжні спростування; решта це довгі зведення,
    де слово трапилось мимохідь (відстань до тригера 239-2275 символів проти 1).
    Правило «є заперечення будь-де» зіпсувало б 11 коректно розібраних подій.
    """

    def test_retraction_is_not_a_sighting(self):
        for text in ["Пензенская область / Ложные фиксации",
                     "Владимирская область / Ложные фиксации",
                     "Ковровский район / Владимирская область / Ложные фиксации"]:
            with self.subTest(text=text):
                self.assertEqual(ST.kind_of(text), "інше")

    def test_plain_sighting_still_classified(self):
        self.assertEqual(ST.kind_of("Белгород фиксации БПЛА"), "фіксація")
        self.assertEqual(ST.kind_of("Сбит БПЛА над городом"), "збиття")
        self.assertEqual(ST.kind_of("Тревога по БПЛА"), "тривога")

    def test_distant_negation_does_not_suppress(self):
        """Слово «ложн» за 300 символів від тригера не стосується його."""
        text = ("#Сводка на утро: ночью сбито несколько БПЛА. " + "х" * 300 +
                " ложные сообщения в сети.")
        self.assertEqual(ST.kind_of(text), "збиття")

    def test_later_unnegated_match_still_counts(self):
        """Перший збіг заперечений, далі є справжній — тип чинний."""
        self.assertEqual(ST.kind_of("Ложные фиксации, но были фиксации БПЛА"),
                         "фіксація")


class TestNoDuplicateClassifier(unittest.TestCase):
    """Класифікація має жити в одному місці.

    `raid.py` тримав власну копію `kind_of` з часів, коли розбір робився там.
    Копія тихо розійшлась: після виправлення заперечення жива версія віддавала
    для «Ложные фиксации» тип «інше», а копія — «фіксація», тобто той самий баг.
    Ніхто її не викликав, але вона лишалась готовою пасткою.
    """

    def _definitions_of(self, *names):
        import ast
        out = []
        for p in sorted(ROOT.glob("*.py")) + sorted((ROOT / "tgmine").glob("*.py")):
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                if isinstance(n, ast.FunctionDef) and n.name in names:
                    out.append(f"{p.name}:{n.lineno} {n.name}")
        return out

    def test_kind_of_defined_once(self):
        found = self._definitions_of("kind_of")
        self.assertEqual(len(found), 1, f"копії класифікатора: {found}")
        self.assertTrue(found[0].startswith("store.py:"), found)

    def test_no_stale_copy_of_drones_of(self):
        self.assertEqual(self._definitions_of("drones_of"), [])


class TestTargetId(unittest.TestCase):
    """Прив'язка до цілі за ідентифікатором, не за назвою.

    На 4659 обʼєктів припадає лише ~1983 унікальні назви, тому join за назвою
    роздавав кожному тезці ПОВНИЙ лік імені: 13197 hits проти 4694 реальних.
    """

    def test_osm_id_is_the_identifier(self):
        o = {"osm": "w123", "cat": "airfield", "lat": 50.0, "lon": 36.0}
        self.assertEqual(ST.target_id(o), "w123")

    def test_curated_objects_fall_back_to_coordinates(self):
        o = {"osm": "", "cat": "refinery", "lat": 48.66, "lon": 44.42}
        self.assertEqual(ST.target_id(o), "c:refinery:48.66:44.42")

    def test_same_name_different_objects_get_different_ids(self):
        a = {"osm": "w1", "name": "Склад БК (Sevastopol)", "cat": "ammo_depot",
             "lat": 44.6, "lon": 33.5}
        b = {"osm": "w2", "name": "Склад БК (Sevastopol)", "cat": "ammo_depot",
             "lat": 44.5, "lon": 33.5}
        self.assertNotEqual(ST.target_id(a), ST.target_id(b))

    def test_nearest_returns_a_tid(self):
        idx = ST.TargetIndex([{"osm": "w1", "name": "Аеродром", "cat": "airfield",
                               "lat": 50.0, "lon": 36.0}])
        hit = idx.nearest(50.01, 36.01)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["tid"], "w1")

    def test_tie_break_is_independent_of_input_order(self):
        """Сусідні будівлі одного обʼєкта на рівній відстані перекидались між
        запусками, бо вигравав перший у targets.json, а rank_targets його
        пересортовує."""
        twins = [{"osm": "w1088757379", "name": "Склад БК", "cat": "ammo_depot",
                  "lat": 50.0, "lon": 36.0},
                 {"osm": "w1088757380", "name": "Склад БК", "cat": "ammo_depot",
                  "lat": 50.0, "lon": 36.0}]
        a = ST.TargetIndex(twins).nearest(50.0, 36.0)
        b = ST.TargetIndex(list(reversed(twins))).nearest(50.0, 36.0)
        self.assertEqual(a, b)


class TestDayWindow(unittest.TestCase):
    """Оперативна доба 12:00 -> 12:00 МСК, не календарна.

    Було 16:00 -> 12:00, і проміжок 12:00-16:00 не входив у жодне вікно.
    """

    @classmethod
    def setUpClass(cls):
        cls.site = load_script("site.py")

    def test_window_starts_and_ends_at_noon_msk(self):
        lo, hi = self.site.day_window("2026-07-17")
        self.assertEqual((lo.hour, hi.hour), (12, 12))
        self.assertEqual(hi - lo, timedelta(days=1))
        self.assertEqual(lo.utcoffset(), timedelta(hours=3))

    def test_consecutive_windows_touch_without_gap_or_overlap(self):
        _, hi = self.site.day_window("2026-07-17")
        lo2, _ = self.site.day_window("2026-07-18")
        self.assertEqual(hi, lo2, "між добами не має бути ні дірки, ні накладання")

    def test_night_raid_is_not_split(self):
        lo, hi = self.site.day_window("2026-07-17")
        MSK = timezone(timedelta(hours=3))
        for h in (22, 23, 0, 3, 5):
            day = 17 if h >= 12 else 18
            t = datetime(2026, 7, day, h, 30, tzinfo=MSK)
            with self.subTest(hour=h):
                self.assertTrue(lo <= t < hi, "нічний наліт розірвано межею доби")


@needs_store
class TestStoreInvariants(unittest.TestCase):
    """Інваріанти вже зібраного сховища."""

    @classmethod
    def setUpClass(cls):
        cls.events = []
        for f in sorted((ROOT / "store" / "events").glob("*.jsonl")):
            with f.open(encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        cls.events.append((f.stem, json.loads(line)))

    def test_ids_are_unique(self):
        ids = [e["id"] for _, e in self.events]
        self.assertEqual(len(ids), len(set(ids)), "дубльовані id подій")

    def test_event_lands_in_the_file_of_its_own_date(self):
        for day, e in self.events:
            self.assertEqual(e["date_msk"], day)

    def test_near_always_carries_a_tid(self):
        missing = [e["id"] for _, e in self.events
                   if e.get("near") and not e["near"].get("tid")]
        self.assertEqual(missing[:5], [],
                         "сховище зібране конвеєром < v9 — треба --rebuild")

    def test_coordinates_are_inside_the_theater(self):
        from tgmine.geocode import in_box
        bad = [(e["id"], e["lat"], e["lon"]) for _, e in self.events
               if e.get("lat") is not None and not in_box(e["lat"], e["lon"])]
        self.assertEqual(bad[:5], [])

    def test_schema_is_uniform(self):
        keys = {frozenset(e) for _, e in self.events}
        self.assertEqual(len(keys), 1, "рядки з різним набором полів")

    def test_event_carries_how_the_coordinate_was_found(self):
        """`geo_conf` рахувався в geocode й викидався перед записом.

        Через це в сховищі точка, підтверджена областю з того ж поста,
        виглядала точнісінько як вгадана за населенням, і жоден вид не міг їх
        розрізнити. Поле має бути в КОЖНОМУ рядку (навіть None — інакше
        падає test_schema_is_uniform) і мати осмислені значення.
        """
        KNOWN = {"region", "consensus", "global", "alias",
                 "city-marker", "centroid", "region-snap", None}
        seen = {e.get("geo_conf") for _, e in self.events}
        self.assertTrue(all("geo_conf" in e for _, e in self.events),
                        "подія без geo_conf")
        self.assertEqual(seen - KNOWN, set(), "невідома позначка впевненості")
        # Контроль, що поле не заповнене однією заглушкою: у сховищі мають
        # бути і слабкі розвʼязання, і підтверджені узгодженням.
        for want in ("region", "global", "consensus"):
            self.assertIn(want, seen, f"жодної події з geo_conf={want}")

    def test_coordinate_bearing_events_are_not_mostly_guesswork(self):
        """Точкове спостереження з координатою має спиратись на щось.

        Сторожа проти тихої деградації: якщо частка найслабшої гілки
        («найбільший однойменний за населенням») поповзе вгору, карта почне
        брехати рівно так, як брехала до узгодження. На момент введення
        порогу частка була 3.7% (315 з 8485).
        """
        pts = [e for _, e in self.events
               if e.get("scope") == "точка" and e.get("lat") is not None]
        self.assertGreater(len(pts), 100, "замало точкових подій для оцінки")
        guessed = sum(1 for e in pts if e.get("geo_conf") == "global")
        self.assertLess(guessed / len(pts), 0.10,
                        f"{guessed} з {len(pts)} точок вгадано за населенням")


if __name__ == "__main__":
    unittest.main()


class TestPromoIsNoise(unittest.TestCase):
    """Заклики про донати не мають потрапляти на публічні сторінки.

    Стояло правило «після чистки не лишилось нічого змістовного»
    (`len(clean) < 25`), і воно пропустило банер збору коштів російського
    каналу просто на сторінку «Що зараз»: із десяти рядків патерни зняли три,
    решта 145 символів пройшла як звичайна подія.

    Патерн не спрацював через порядок слів — «Радару требуется ваша
    поддержка» проти «поддержка радара». Латати формулювання марно, тому
    ознакою стало поєднання: є промо-рядок І жоден бойовий тег не спрацював.

    Текст укладено дослівно з data/vrv_radar.jsonl (пост 74180) РАЗОМ із
    переносами рядків: strip_promo працює порядково, плаский переказ дає інший
    результат.
    """

    PROMO = ("❤️\nРадару требуется ваша поддержка!\n"
             "Мы не размещаем рекламу и не зарабатываем на тревогах.\n"
             "Проект держится на поддержке подписчиков.\n🙌\n"
             "Если канал вам полезен —\nподдержите\nлюбой суммой.\n"
             "Даже небольшой донат помогает нам продолжать.\n👉\n"
             "https://pay.cloudtips.ru/p/01396e10")

    def setUp(self):
        from tgmine import extract as E
        self.cfg = E.Config.load(str(ROOT / "configs" / "ru-monitor.yaml"))

    def _event(self, text):
        st = ST.Store.__new__(ST.Store)      # без диска: потрібен лише розбір
        post = {"channel": "vrv_radar", "id": 1, "text": text,
                "date": "2026-07-19T18:02:00+00:00",
                "url": "https://t.me/vrv_radar/1", "entities": []}
        return ST.Store._event(st, post, self.cfg)

    def test_donation_banner_is_marked_noise(self):
        self.assertTrue(self._event(self.PROMO)["noise"],
                        "банер збору коштів пройшов як звичайна подія")

    def test_real_sighting_with_promo_line_survives(self):
        # Найнебезпечніший бік правила: спостереження з рекламним хвостом.
        # Бойовий тег спрацював, отже kind != «інше», отже подія лишається.
        text = ("Фиксация БПЛА в районе Клоково, курс на Тулу\n"
                "Подписывайтесь на наш канал")
        e = self._event(text)
        self.assertNotEqual(e["kind"], "інше")
        self.assertFalse(e["noise"], "справжнє спостереження позначено шумом")

    def test_clean_post_without_promo_is_not_noise(self):
        e = self._event("Фиксация БПЛА в районе Клоково, курс на Тулу")
        self.assertFalse(e["noise"])


class TestNearNeedsARealCoordinate(unittest.TestCase):
    """Привʼязка до цілі — лише для координат, які вказують на місце.

    Регіональні відкати (centroid/region/region-snap) означають «десь у цій
    області», а область це десятки тисяч кв. км. Ставити їм найближчу ціль —
    вигадувати точність, якої в даних нема.

    Виміряно до правки: 64% усіх привʼязок (8182 з 12800) стояли на такій
    координаті, і перекіс був нерівномірний, тому рейтинг брехав. Аеродром
    Клокове був №1 із 571 привʼязкою, з яких 71% — центр Тули за 5 км, куди
    падали «Ясногорский район» і «Чернский район» за 50-80 км звідти. Після
    правки він восьмий зі 167. Сума привʼязок 12759 -> 4629.
    """

    @needs_store
    def test_no_target_is_attached_to_a_regional_fallback(self):
        bad = []
        for f in sorted((ROOT / "store" / "events").glob("*.jsonl")):
            with f.open(encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    e = json.loads(line)
                    if e.get("near") and e.get("geo_conf") in ST.REGIONAL_FALLBACK:
                        bad.append((e["id"], e.get("geo_conf"), e["near"]["name"]))
        self.assertEqual(bad[:5], [],
                         "ціль привʼязана до центру області — жар цілей роздується")

    @needs_store
    def test_city_level_attribution_is_the_weakest_mode_left(self):
        """Межа методу, а не помилка — але вона має лишатись видимою.

        Після відсіву регіональних відкатів решта привʼязок спирається на
        `city-marker`: «БПЛА над Волгоградом» дає центр Волгограда, а звідти
        найближча ціль першого ярусу в радіусі 18 км — НПЗ. Це «увага до
        міста», а не влучання в обʼєкт, і сторінка цілей саме так і написана.

        Тест не забороняє такі привʼязки, а стежить, щоб вони не почали
        мовчки спиратись на щось слабше за рівень міста.
        """
        import collections
        modes = collections.Counter()
        for f in sorted((ROOT / "store" / "events").glob("*.jsonl")):
            with f.open(encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    e = json.loads(line)
                    if e.get("near") and e.get("scope") == "точка":
                        modes[e.get("geo_conf")] += 1
        weak = sum(v for k, v in modes.items() if k in ("global",))
        total = sum(modes.values()) or 1
        self.assertLess(weak / total, 0.10,
                        f"забагато привʼязок на здогадах за населенням: {modes}")


class TestDeclaredProfile(unittest.TestCase):
    """Профіль заявлених апаратів: чому сума не показується.

    Виміряно на корпусі: 50% подій із числом мають сусіда в межах 20 хв і
    200 км, тобто одну групу фіксують кілька районів поспіль. Сума складає її
    по два-три рази — «411 апаратів» у ніч на 24.07 це 58 повідомлень.
    Кластеризацію повторів пробували й відкинули: без межі діаметра ланцюг
    злипався через 874 км, з межею перевага над сирою сумою падала до шуму,
    а сама кількість груп на переборі 324 конфігурацій гуляла ±55%.
    Тому у видах — лише параметронезалежні числа.
    """

    def test_swarm_seen_in_three_districts_is_not_multiplied(self):
        """Той самий рій у трьох районах не має давати потрійне число."""
        swarm = [{"drones": 12, "place": p, "region": "Калузька"}
                 for p in ("Жиздра", "Людиново", "Сухиничі")]
        d = ST.declared(swarm)
        self.assertEqual(d["largest"], 12, "найбільша група — це 12, не 36")
        self.assertEqual(d["raw"], 36, "сира сума лишається доступною для звірки")
        self.assertEqual(d["with_count"], 3)

    def test_places_and_regions_are_deduplicated(self):
        """Замінник «кількості груп» рахує РІЗНІ місця, а не повідомлення."""
        evs = [{"drones": 2, "place": "Жиздра", "region": "Калузька"},
               {"drones": 3, "place": "Жиздра", "region": "Калузька"},
               {"drones": 4, "place": "Ржев", "region": "Тверська"}]
        d = ST.declared(evs)
        self.assertEqual(d["with_count"], 3)
        self.assertEqual(d["count_places"], 2)
        self.assertEqual(d["count_regions"], 2)

    def test_events_without_a_number_are_ignored(self):
        d = ST.declared([{"place": "Тула", "region": "Тульська"}])
        self.assertEqual(d, {"raw": 0, "largest": 0, "with_count": 0,
                             "count_places": 0, "count_regions": 0, "median": 0})

    def test_two_nights_differ_by_largest_group_not_by_volume(self):
        """Головна знахідка: ночі розрізняє маса групи, а не кількість подій.

        23.07 — 58 повідомлень, найбільша група 50, 9 областей.
        09.06 — 62 повідомлення, найбільша група 10, 18 областей.
        Обсяг майже однаковий, тактика протилежна. Сира сума це ховала.
        """
        concentrated = ([{"drones": 50, "place": "A", "region": "R1"}]
                        + [{"drones": 3, "place": f"p{i}", "region": "R1"}
                           for i in range(20)])
        dispersed = [{"drones": 3, "place": f"q{i}", "region": f"R{i}"}
                     for i in range(21)]
        a, b = ST.declared(concentrated), ST.declared(dispersed)
        self.assertEqual(a["with_count"], b["with_count"])
        self.assertGreater(a["largest"], b["largest"] * 4)
        self.assertGreater(b["count_regions"], a["count_regions"] * 4)
