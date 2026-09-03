"""Сховище подій: класифікація, ідентифікатори цілей, межа доби."""
import json
import unittest
from datetime import datetime, timedelta, timezone

from tests.helpers import ROOT, load_script, needs_gazetteer, needs_store
from tgmine import geocode as GC
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


class TestYoNormalisation(unittest.TestCase):
    """«пролёт» — те саме слово, що «пролет», і те саме спостереження.

    Патерни KIND написані без «ё», тому пости з нею падали в «інше» й губили
    scope="точка": на карту не йшли, у жар цілей не рахувались. Виміряно на
    корпусі — 2942 події міняють тип, з них 2690 «інше» -> «фіксація»; на
    останніх повних добах це +15.2% точкових спостережень, бо locatorru
    пише саме з «ё».

    Тексти взято дослівно з `data/` — перевірено `grep -F`. Вигаданий приклад
    тут коштує дорого: розбір залежить від сусідніх слів у рядку, і на
    придуманій фразі тест тримає не те правило, яке працює на корпусі.
    """

    def test_yo_trigger_is_a_sighting(self):
        for text in [
            "Папино, Жуковский район, Калужская область - пролёт от 5 БПЛА "
            "в сторону Московской области",
            "От Верхнесадовое на юг возможно пролёт БПЛА",
            "Никольское, Троснянский район, Орловская область - ещё пролёт "
            "1 БПЛА в сторону Орла или Змиёвка.",
        ]:
            with self.subTest(text=text):
                self.assertEqual(ST.kind_of(text), "фіксація")

    def test_yo_sighting_is_a_point(self):
        """Тип без scope нічого не дає: сенс правки саме в точковому шарі."""
        self.assertIn(ST.kind_of("Брянская область - массовый пролёт БПЛА"),
                      ST.POINT_KINDS)

    def test_negation_survives_normalisation(self):
        """Заміна «ё» не має відкривати спростування як спостереження."""
        self.assertEqual(
            ST.kind_of("По ракетной были ложные цели. Прилётов нет. / "
                       "📡 / Локатор России - / @locatorru"), "інше")

    def test_explosion_stays_on_raw_text(self):
        """«прилёт» у ё-формі — це переказ, а не подія.

        Перевірено поіменно всі 16 подій корпусу, які нормалізація перевела б
        у «вибух»: зведення «#Сводка», попередження «возможны прилёты»,
        звернення до підписників і удар по Одесі. Жодного справжнього вибуху.
        Клас «вибух» у корпусі 89 подій, тож 16 хибних — це +18% до єдиного
        класу про наслідки.
        """
        for text in ["Множественные прилёты в окраины Одессы",
                     "По ЛБС, ДНР высокая активность РСЗО! возможны прилёты.",
                     "В разгар тревог, прилётов и сбитий — пост добра"]:
            with self.subTest(text=text):
                self.assertNotEqual(ST.kind_of(text), "вибух")

    def test_explosion_without_yo_untouched(self):
        """Звуження не має погасити те, що працювало."""
        self.assertEqual(ST.kind_of("Мелитополь - взрыв / Тревога по БПЛА"),
                         "вибух")
        self.assertEqual(
            ST.kind_of("Внимание, Козинка! / Объявлена опасность сбросов "
                       "с «Бабы-Яги», будьте бдительны, так же прилеты "
                       "в районе мапа / Белгород"), "вибух")


class TestMovementFallback(unittest.TestCase):
    """«Апарат названий і сказано, куди він іде» — це фіксація.

    Такі пости лежали в «іншому» зі `scope="область"`, тобто не бачила ні
    карта, ні жар цілей: 1709 подій по сховищу, 84 за 15 діб, 82 зі 84 з
    координатою.

    Чому фолбеком, а не тригером у KIND: додати «в сторону» просто до
    «фіксації» — виміряно — перекидає 127 ТРИВОГ у точкові спостереження
    («опасность по БПЛА и в сторону Саратов»). Це те саме змішування тривоги
    зі спостереженням, від якого карта стає безінформативною.

    Тексти дослівні з `data/`.
    """

    def test_movement_without_trigger_word(self):
        self.assertEqual(
            ST.kind_of("От Светлодарска в сторону Дебальцево группа БПЛА\nДНР"),
            "фіксація")

    def test_alarm_with_direction_stays_an_alarm(self):
        """Саме цих 127 подій правка не має чіпати."""
        self.assertEqual(ST.kind_of(
            "Елань, Рудня, Жирновск, Волгоградская область - опасность по "
            "БПЛА и в сторону Саратов, Энгельс, Саратовской области.\n📡\n"
            "Локатор России -\n@locatorru"), "тривога")

    def test_explicit_trigger_still_wins(self):
        self.assertEqual(ST.kind_of(
            "Сельцо, Брянская область - пролёт БПЛА в сторону Калужской "
            "области.\n📡\nЛокатор России -\n@locatorru"), "фіксація")

    def test_movement_without_drone_is_not_a_sighting(self):
        """Рух без апарата — не спостереження."""
        self.assertEqual(ST.kind_of("Движение автотранспорта по Крымскому "
                                    "мосту возобновлено."), "інше")


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

    def test_drones_of_defined_once(self):
        """Раніше тест вимагав, щоб такої функції не було ніде.

        Причина була в тому, що витяг числа жив прямо в `raid.py` окремою
        копією. Тепер він один і в `store.py` — а вимога лишається та сама:
        рівно одне визначення. Число апаратів іде у видах числом, і дві
        версії правила означали б два різні «найбільша група» на сайті.
        """
        found = self._definitions_of("drones_of")
        self.assertEqual(len(found), 1, f"копії витягу числа: {found}")
        self.assertTrue(found[0].startswith("store.py:"), found)


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


class TestDirectionTargetIsNotThePlace(unittest.TestCase):
    """Куди летить — не там, де спостерігають.

    Координата події береться як топонім із найбільшим населенням, і саме
    тому в крапку перетворювалась ЦІЛЬ РУХУ: місто, куди летить, майже завжди
    більше за село, звідки дивляться. Виміряно на 15 добах — 286 із 8414
    координат (3.4%). Напрямки й так витягує `vectors.py` окремо.

    Тексти дослівні з `data/`. Координати й населення — літерали, щоб тест
    ішов без газетира (132 МБ, у .gitignore); що вони СПРАВЖНІ, стереже
    `TestDirectionFixtureMatchesGazetteer` нижче. Першу версію цього тесту я
    написав із памʼяті, і шість констант із семи були вигадані — «Белгорода»
    відрізнялось у чотири рази, бо газетир на цей запит віддає Бєлгородську
    ОБЛАСТЬ (1.5 млн, 72 км від міста), а не місто.
    """

    #: (запит, lat, lon, населення) — найвагоміший кандидат вузького набору.
    GAZ = {
        "Тыловое": (44.44134, 33.73228, 573),
        "Севастополь": (44.60795, 33.52134, 547820),
        "Трубчевск": (52.58031, 33.76574, 16100),
        "Брянск": (53.27096, 34.32143, 427236),
        "Приморско-Ахтарск": (46.04847, 38.17899, 33102),
        "Томаровки": (50.68337, 36.23443, 7916),
        "Белгорода": (50.83333, 37.54167, 1549876),
        "Почепский": (52.91488, 33.4993, 38742),
        "Жуковку": (53.53381, 33.73075, 19690),
    }

    def _post(self, text, names):
        """Пост із розвʼязаними топонімами; позиції беруться з самого тексту."""
        return {"text": text, "entities": [
            {"type": "нп", "match": n, "pos": text.index(n),
             "lat": self.GAZ[n][0], "lon": self.GAZ[n][1],
             "geo_pop": self.GAZ[n][2], "geo_conf": "region"}
            for n in names]}

    def test_origin_wins_over_destination(self):
        p = self._post("Тыловое БПЛА в направлении Севастополь",
                       ["Тыловое", "Севастополь"])
        self.assertEqual(ST.point_entity(p)["match"], "Тыловое")

    def test_further_in_direction_also_counts(self):
        p = self._post("Трубчевск и далее в направлении Брянск тревога по БПЛА",
                       ["Трубчевск", "Брянск"])
        self.assertEqual(ST.point_entity(p)["match"], "Трубчевск")

    def test_lone_destination_is_kept(self):
        """Як не лишається нічого — краще неточна крапка, ніж втрата події."""
        p = self._post("В направлении Приморско-Ахтарск через Азовское море "
                       "крылатая ракета ПКР Нептун или реактивный БПЛА",
                       ["Приморско-Ахтарск"])
        self.assertEqual(ST.point_entity(p)["match"], "Приморско-Ахтарск")

    def test_enumeration_after_the_preposition(self):
        """Прийменник стоїть лише перед першою назвою переліку.

        Без цього кроку правило ловило перший пункт, а крапка переїжджала на
        другий: заміряно 168 постів із 1026 (16%).
        """
        p = self._post("Почепский район и далее на Жуковку, Брянск "
                       "опасность по БПЛА",
                       ["Почепский", "Жуковку", "Брянск"])
        self.assertEqual(ST.point_entity(p)["match"], "Почепский")

    def test_from_is_a_place_not_a_direction(self):
        """«От X» — це місце спостереження, і воно таким лишається."""
        p = self._post("От Томаровки в сторону Белгорода группа БПЛА.",
                       ["Томаровки", "Белгорода"])
        self.assertEqual(ST.point_entity(p)["match"], "Томаровки")


@needs_gazetteer
class TestDirectionFixtureMatchesGazetteer(unittest.TestCase):
    """Літерали в TestDirectionTargetIsNotThePlace мають бути справжніми.

    Перша версія тих тестів була написана з памʼяті: шість констант із семи
    не збігались із газетиром, а «Белгорода» відрізнялось у чотири рази.
    Тест на вигаданих числах перевіряє не той відбір, що працює на даних.
    """

    def test_fixture_is_real(self):
        from tests.helpers import GAZ as GAZDIR
        gaz = GC.Gazetteer.load(GAZDIR / "RU.txt", GAZDIR / "UA.txt")
        for q, (lat, lon, pop) in TestDirectionTargetIsNotThePlace.GAZ.items():
            with self.subTest(query=q):
                cands = gaz.candidates(q, GC.THEATER)
                self.assertTrue(cands, f"{q}: газетир не дає кандидатів")
                best = max(cands, key=lambda c: c["pop"])
                self.assertEqual(best["pop"], pop)
                self.assertLess(GC.haversine((lat, lon),
                                             (best["lat"], best["lon"])), 1.0)


class TestDroneCount(unittest.TestCase):
    """Число апаратів — єдине число, яке йде у видах як число.

    `declared()["largest"]` друкується на сторінці, тому ціна хибного збігу
    тут найвища в проєкті. Стара регулярка `от\\s+(\\d+)\\s*БПЛА` брала 67.1%
    постів, де число взагалі є; решту locatorru пише інакше — «Фиксация 2
    БПЛА» (402), «пролёт 2 БПЛА» (328), «ещё 2 БПЛА» (34). Стало 83.4%.

    Заміряно на 15 добах: `largest` не змінився ЖОДНОЇ ночі — нове ловить
    лише дрібні числа (медіана 2), а `with_count` виріс (25 -> 51 за добу).

    Тексти дослівні з `data/`.
    """

    def test_locatorru_phrasings(self):
        for text, want in [
            ("Бабынинский район\nКалужская область\nФиксация 2 БПЛА", 2),
            ("Серпейск, Мещовский район, Калужская область - пролёт 2 БПЛА "
             "на северо-восток.\n📡\nЛокатор России -\n@locatorru", 2),
            ("Мигулинская, Верхнедонской район, Ростовская область - ещё "
             "2 БПЛА на Вешенская.\n📡\nЛокатор России -\n@locatorru", 2),
        ]:
            with self.subTest(text=text[:40]):
                self.assertEqual(ST.drones_of(text), want)

    def test_old_phrasing_still_works(self):
        self.assertEqual(ST.drones_of(
            "Шумячи, Смоленская область - фиксация от 2 БПЛА на север.\n📡\n"
            "Локатор России -\n@locatorru"), 2)

    def test_ministry_digest_is_not_a_sighting(self):
        """1629 збігів «N БПЛА» у корпусі — це саме такі зведення."""
        self.assertIsNone(ST.drones_of(
            "За прошедшую ночь силами противовоздушной обороны было "
            "уничтожено 76 БПЛА:\n🔺\n33 БПЛА над Саратовской областью;\n🔺\n"
            "17 БПЛА над акваторией Чёрного моря;"))

    def test_analytic_prose_is_not_a_sighting(self):
        """Ця фраза й показала, що тригеру потрібні межі слова.

        Без `\\b` тригер «от» збігався всередині «сосредот-от-очить», і
        аналітичний абзац зі зведення віддавав 1600 — тобто «найбільша група»
        тієї ночі стала б у дванадцять разів більшою за реальний максимум
        корпусу (130).
        """
        self.assertIsNone(ST.drones_of(
            "киевские дроны летят в таком количестве, что и тактическая "
            "ядерка им не нужна, если сосредоточить 1600 БПЛА "
            "(подтвержденный антирекорд, кстати) на узком тыловом участке"))

    def test_ban_words_must_touch_the_number(self):
        """Широка заборона зʼїдала спостереження — заміряно, 3 пости.

        «Приготовиться к сбитию» і «Всего от …» це не зведення, а звичайні
        повідомлення; слово зведення має стояти ВПРИТУЛ перед числом
        («было уничтожено 76 БПЛА»), а не будь-де у вікні.
        """
        self.assertEqual(ST.drones_of(
            "Кстово\nНижегородская область\nПриготовиться к сбитию\n"
            "Меры безопасности\nФиксация от 3 БПЛА в вашем направлении"), 3)
        self.assertEqual(ST.drones_of(
            "Всего от Днепропетровска вылетело от 15 БПЛА"), 15)

    def test_largest_number_of_the_post_wins(self):
        """Постів із двома валідними числами 12, у двох перше не найбільше."""
        self.assertEqual(ST.drones_of(
            "Бетлица — Хвастовичи\nИ далее в тыл\nКалужская область\n"
            "Фиксация 8 БПЛА\nЕще от 20 БПЛА в вашу сторону\n"
            "Соблюдаем меры безопасности!"), 20)

    def test_no_number_no_count(self):
        self.assertIsNone(ST.drones_of("Брянская область\nТревога по БПЛА"))
