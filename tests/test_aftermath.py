"""Наслідки з каналу exilenova_plus: tgmine/aftermath.py.

Кожен випадок — пост, на якому правило колись помилялось (23.09.2026,
сліпа розмітка двома розмітниками й перегляд усіх 494 інцидентів).
"""
import json
import random
import unittest
from datetime import date, datetime, timedelta, timezone

from tests.helpers import GAZ, ROOT, needs_gazetteer
from tgmine import aftermath as A

MSK = timezone(timedelta(hours=3))


def post(i, when, text, reply=None):
    """Сирий пост; `when` — «YYYY-MM-DD HH:MM» за Москвою."""
    t = datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=MSK)
    return {"channel": A.CHANNEL, "id": i, "date": t.astimezone(timezone.utc).isoformat(),
            "url": f"https://t.me/{A.CHANNEL}/{i}", "text": text,
            "reply_to": f"https://t.me/{A.CHANNEL}/{reply}" if reply else None}


class TestText(unittest.TestCase):
    """Правила без газетира."""

    def test_skel_merges_ukrainian_and_russian(self):
        self.assertEqual(A.skel("Тольятті"), A.skel("Тольятти"))
        self.assertEqual(A.skel("Сизрань"), A.skel("Сызрань"))
        self.assertEqual(A.skel("Новоросійськ"), A.skel("Новороссийск"))

    def test_skel_keeps_digits(self):
        # «11 вересня» не має ставати «1 вересня»: склеювання подвоєних лише
        # для літер
        self.assertIn("11", A.skel("11 вересня"))

    def test_patterns_are_in_skeleton_form(self):
        # Шаблони шукають у кістяку (`skel`): «ь» там нема, «і» — «и», подвоєні
        # — одна. «сьогодни рик», «этой ночью», «попадания не было», «сообщ»
        # не спрацьовували ніколи (знайдено 23.09.2026).
        import re
        for name in ("HIT", "NOT_HIT", "NEG", "NEG_STRONG", "OFFICIAL", "OIL", "ANCHOR",
                     "LAST_NIGHT", "ATTACKW", "TACTICAL_RX", "RETRO", "ANNIV", "THIS_NIGHT", "RUINS", "_YESTERDAY",
                     "REPORTED", "NEXT_NOUN", "REGION_WORD", "ADJ_NAME", "TITLE", "ROUTE",
                     "FIRST_NAME", "_ADJ_LIST", "_OBJ_ANY"):
            src = getattr(A, name).pattern
            words = re.findall(r"[а-яёїієґэъ]+(?!\?)", src)
            self.assertEqual([w for w in words if A.skel(w) != w], [], name)
        self.assertTrue(A.THIS_NIGHT.search(A.skel("Цієї ночі уразили НПЗ")))
        self.assertTrue(A.THIS_NIGHT.search(A.skel("Этой ночью атаковали")))
        self.assertTrue(A.ANNIV.search(A.skel("Сьогодні рік, як «Павутина»")))

    def test_coordinates(self):
        self.assertEqual(A.coords_in("точка (55.644523,37.805698)"), [(55.64452, 37.8057)])
        self.assertEqual(A.coords_in("Координати: 50.094131° 43.237939°"), [(50.09413, 43.23794)])
        dms = A.coords_in('авіабазу: 47°16\'24.52"N 39°37\'56.20"E')
        self.assertAlmostEqual(dms[0][0], 47.2735, places=3)
        # точка знімання — не ціль
        self.assertEqual(A.coords_in('РОV: 47°15\'33.80"N 39°38\'33.20"E'), [])

    def _when(self, text, at):
        t = datetime.strptime(at, "%Y-%m-%d %H:%M").replace(tzinfo=MSK)
        return A._date_of(A.skel(text), t)

    def test_night_of_phrase(self):
        self.assertEqual(self._when("В ніч на 15-те вересня уразили НПЗ", "2026-09-22 18:14"),
                         ("night", date(2026, 9, 14)))
        self.assertEqual(self._when("У ніч проти 20 вересня Сили оборони вразили", "2026-09-20 10:25"),
                         ("night", date(2026, 9, 19)))

    def test_plain_and_numeric_dates(self):
        self.assertEqual(self._when("11 вересня десяток БПЛА прилетіло", "2026-09-15 07:09"),
                         ("day", date(2026, 9, 11)))
        self.assertEqual(self._when("Ураження ЗПК 09.09.2026", "2026-09-10 17:00"),
                         ("day", date(2026, 9, 9)))
        self.assertEqual(self._when("Руїни складів після удару 16.08", "2026-08-19 17:29"),
                         ("day", date(2026, 8, 16)))

    def test_numeric_night_of(self):
        # замір 23.09: «у ніч на 24.07.2026» йшло на ніч поста (24.07)
        self.assertEqual(self._when("У ніч на 24.07.2026 підтверджено ураження", "2026-07-24 19:56"),
                         ("night", date(2026, 7, 23)))
        self.assertEqual(self._when("У ніч з 18 на 19 квітня уразили кораблі", "2026-04-20 08:46"),
                         ("night", date(2026, 4, 18)))
        self.assertEqual(self._when("в ночь на 16.08 атакован", "2026-08-20 10:00"),
                         ("night", date(2026, 8, 15)))
        # крапка в кінці речення — не частина дати (пости 19850, 18886)
        self.assertEqual(self._when("Туапсе в ніч на 01.05.2026.", "2026-05-03 10:00"),
                         ("night", date(2026, 4, 30)))
        self.assertEqual(self._when("Супутниковий знімок 16.09.26.", "2026-09-20 10:00"),
                         ("day", date(2026, 9, 16)))
        # рік названо — давня історія, а не цей рік (Оленівка, пост 27343)
        self.assertEqual(self._when("У ніч з 28 на 29 липня 2022 року в Оленівці", "2026-07-28 07:06"),
                         ("old", None))
        self.assertEqual(self._when("У ніч на 24.07.2025 уражено", "2026-07-30 10:00"), ("old", None))

    def test_this_night_in_the_evening_is_ahead(self):
        # «цієї ночі» вдень — минула ніч, увечері — ніч, що попереду
        self.assertEqual(self._when("Цієї ночі уразили НПЗ у Тюмені", "2026-07-25 13:04"),
                         ("night", date(2026, 7, 24)))
        self.assertIsNone(self._when("Не нехтуйте тривогами цієї ночі.", "2026-07-29 20:40"))
        # «вночі» ввечері — так і лишається минулою ніччю
        self.assertEqual(self._when("Але вночі під час вибухів на складі була пожежа.", "2026-07-18 20:19"),
                         ("night", date(2026, 7, 17)))

    def test_last_night_in_the_afternoon(self):
        # «сьогодні вночі», написане о 13:35, — про ніч, що скінчилась
        self.assertEqual(self._when("Сьогодні вночі уразили аеродром", "2026-08-28 13:35"),
                         ("night", date(2026, 8, 27)))
        # уранці та сама фраза — поточна ніч, дати не треба
        self.assertIsNone(self._when("Сьогодні вночі уразили аеродром", "2026-08-28 06:10"))

    def test_hit_is_a_consequence_not_an_intent(self):
        hit = lambda t: bool(A.HIT.search(A.NOT_HIT.sub(" ", A.skel(t))))
        self.assertTrue(hit("На НПЗ у Саратові розгоряється пожежа."))
        self.assertTrue(hit("Момент прилета в Тольятти."))
        self.assertTrue(hit("Заявлено як наслідки нічної роботи СОУ."))
        self.assertTrue(hit("Всё, что осталось от склада Wildberries"))
        self.assertFalse(hit("стає дедалі складнішою та дорожчою для ураження"))
        self.assertFalse(hit("Тюмень, НПЗ, вибухи в промзоні."))
        self.assertFalse(hit("У Ростові лунають вибухи."))
        # інфінітив — теж пожежа (замір повноти 24.09: серія Нижньокамська)
        self.assertTrue(hit("В Нижньокамську продовжує горіти НПЗ"))
        self.assertTrue(hit("В Нижнекамске продолжает гореть НПЗ"))
        self.assertFalse(hit("Будет гореть еще 3-4 дня"))
        # майбутнє — побажання, не звіт
        self.assertFalse(hit("ще більше гаражів у Донецьку буде уражено Орєшніком"))

    def test_denials(self):
        for t in ("зафіксованих об'єктивним контролем влучань не було",
                  "Москва. Ще одна законна ціль для ураження",
                  "Одна з ракет не дійшла до цілі",
                  "упало 2 беспилотника, но без возгорания",
                  "Аварія на установці піролізу",
                  "о прилетах ничего не известно",
                  "Челябінськ, пожежа не пов’язана з БПЛА",
                  "Никаких серьезных „прилетов“ нет, это я вам заявляю официально"):
            self.assertTrue(A.NEG.search(A.skel(t)), t)

    def test_night_window(self):
        self.assertEqual(A.night_of(datetime(2026, 9, 22, 1, 41, tzinfo=timezone.utc)), "2026-09-21")
        self.assertEqual(A.night_of(datetime(2026, 9, 9, 13, 51, tzinfo=timezone.utc)), "2026-09-09")


@needs_gazetteer
class TestPlaces(unittest.TestCase):
    """Місце з тексту: відмінки двох мов, прикметники, лапки, тезки."""

    @classmethod
    def setUpClass(cls):
        from tgmine import geocode as GC
        from tgmine import store as ST
        cls.gaz = GC.Gazetteer.load(GAZ / "RU.txt", GAZ / "UA.txt")
        tg = ROOT / "targets.json"
        cls.targets = json.loads(tg.read_text(encoding="utf-8")) if tg.exists() else None
        cls.P = A.Places.load(cls.gaz, cls.targets)
        cls.ST = ST

    def names(self, text, context=()):
        a = A.analyse({"id": 1, "date": "2026-09-16T22:33:00+00:00", "text": text},
                      self.P, self.ST.point_region, context, self.ST.depth_km)
        return [x["rec"]["name"] for x in a["places"]]

    def test_cases_of_both_languages(self):
        self.assertEqual(self.names("У Ростові лунають вибухи."), ["Rostov-on-Don"])
        self.assertEqual(self.names("Також що то горит в Капотне."), ["Kapotnya"])
        self.assertEqual(self.names("Щойно атакували Метафракс у Губасі, Пермський край."), ["Gubakha"])
        self.assertEqual(self.names("У Таганрозі продовжує горіти резервуарний парк."), ["Taganrog"])

    def test_city_adjective_before_object(self):
        self.assertEqual(self.names("Момент атаки на Московський НПЗ."), ["Moscow"])
        self.assertEqual(self.names("Горить Саратовский Озон."), ["Saratov"])
        self.assertEqual(self.names("Куйбишевський НПЗ у Самарі відспіваний."), ["Samara"])
        # «Ударні БПЛА» — прикметник, а не селище Ударный
        self.assertEqual(self.names("Ударні БПЛА Сил Оборони завдали ураження по НПЗ."), [])

    def test_capitalised_words_that_are_not_places(self):
        self.assertEqual(self.names("Сили Оборони уразили хімзавод у Березниках."), ["Berezniki"])
        self.assertEqual(self.names("Добрий ранок, читачі."), [])
        self.assertEqual(self.names("Республіка Татарстан, вибухи."), [])

    def test_oblast_adjectives_are_not_towns(self):
        # «у Донецькій, Луганській областях» — не селище Донецький,
        # «у Ярославському регіоні» — не Ярославський під Москвою
        self.assertEqual(self.names("уразили логістику у Донецькій, Луганській областях та на території рф"), [])
        self.assertEqual(self.names("Також ми досягли НПЗ у Ярославському регіоні."), [])
        # але місто в місцевому, за ним область у родовому — місто
        self.assertEqual(self.names("уразили «Комбинат Каменский» у Каменськ-Шахтинському Ростовської області"),
                         ["Kamensk-Shakhtinsky"])
        self.assertIn("Stanytsya-Luhanska",
                      self.names("Станица Луганская, Луганская область. Была атакована инфраструктура."))
        # «Берегова інфраструктура» — не Берегове, але саме село — так
        self.assertEqual(self.names("Берегова інфраструктура: зафіксовано декілька уражень."), [])
        self.assertTrue(self.names("Береговое, Крым - прилет, горит."))
        # однина після прикметника — місто і його область
        self.assertEqual(self.names("Атакована нефтебаза в станице Тацинской Ростовской области, пожар."),
                         ["Tatsinskaya"])
        self.assertEqual(self.names("Уражено НПЗ у Ярославському, Московському, Тверському та Курському регіонах."), [])

    def test_city_before_republic_abbreviation(self):
        # іменник перед «Респ.», «(Республіка …)» — місто, а не назва регіону
        self.assertEqual(self.names("Уфа, Респ. Башкортостан. Було уражено один з нафтових обʼєктів."), ["Ufa"])
        self.assertEqual(self.names("Уражені частини НПЗ у Нижньокамську (Республіка Татарстан)."), ["Nizhnekamsk"])
        # прикметник у будь-якому відмінку перед «областю/краєм» — регіон
        self.assertEqual(self.names("Уражено мости між Кримом і Херсонською областю."), [])
        self.assertEqual(self.names("Глава Краснодарского края заявил, что горит мазут."), [])

    def test_ukrainian_region_adjective(self):
        # «Ростовська область» (кістяк «ростовска») — регіон, а не селище
        self.assertEqual(self.names("Уражені танкери в порту міста Азов, Ростовська область."), ["Azov"])

    def test_port_name_in_quotes_is_a_place(self):
        self.assertIn("Perm", self.names("Є візуальне підтвердження пожежі на резервуарах ЛДПС «Пермь»."))

    def test_quotes_are_names_not_places(self):
        # «Ангара» — ракета (альт-назва Перевального в Криму)
        self.assertEqual(self.names("двигунів для ракет «Ангара»"), [])
        # але назва аеродрому в лапках — місце
        self.assertEqual(self.names("уразили склад ПММ на аеродромі «Борисоглєбськ»"),
                         ["Borisoglebsk"])

    def test_route_is_not_a_target(self):
        self.assertEqual(self.names("НПС, що забезпечує експорт нафти через порт Приморськ"), [])

    def test_compound_names(self):
        self.assertEqual(self.names("родовищ Надим-Пур-Тазовського регіону"), [])
        self.assertEqual(self.names("уразили НПЗ у Слов'янську-на-Кубані"), ["Slavyansk-na-Kubani"])
        self.assertEqual(self.names("Горить НПЗ у Ростові-на-Дону."), ["Rostov-on-Don"])

    def test_sea_adjective_is_not_a_town(self):
        self.assertEqual(self.names("пожар в Азовском море в районе Керчи"), ["Kerch"])

    def test_region_in_the_sentence_picks_the_namesake(self):
        # не калінінградський Гвардейськ
        self.assertEqual(self.names("пожары на аэродроме в Гвардейском, Крым"), ["Hvardiyske"])

    def test_common_words_named_like_towns(self):
        # «ступінь» — не Ступіно; «Нова Пошта» — не Поштове; «Північному
        # Кавказі» — не Північне; «Крим буде Українським» — не Українка
        self.assertEqual(self.names("Показуємо Московський НПЗ, ступінь ураження висока."), ["Moscow"])
        self.assertEqual(self.names("Вчора Нова Пошта відновила роботу після атаки."), [])
        self.assertEqual(self.names("склад на Північному Кавказі уражено"), [])
        self.assertEqual(self.names("Крим буде Українським, мости уражено."), [])

    def test_sea_and_bridge_are_not_objects_of_the_city(self):
        self.assertEqual(self.names("28 суден уражено у Азовському морі"), [])
        self.assertEqual(self.names("Уражено ще одну ціль біля Кримського мосту"), [])

    def test_comparison_city_does_not_open_a_strike(self):
        a = A.analyse({"id": 1, "date": "2026-07-12T08:09:00+00:00",
                       "text": "Ураження Сизранського НПЗ удень 12.07.2026. Схожу установку "
                               "раніше показували на Омському НПЗ."},
                      self.P, self.ST.point_region, (), self.ST.depth_km)
        opened = [x["rec"]["name"] for x in a["places"] if x["anchored"]]
        self.assertEqual(opened, ["Syzran"])

    def test_coordinates_pick_the_namesake(self):
        a = A.analyse({"id": 1, "date": "2026-07-19T00:00:00+00:00",
                       "text": "Безпілотники уразили комплекс Wildberries у Коледіно "
                               "(Московська область). Координати: 55.386353° 37.586176°"},
                      self.P, self.ST.point_region, (), self.ST.depth_km)
        r = a["places"][0]["rec"]
        self.assertLess(A.hav((r["lat"], r["lon"]), (55.386, 37.586)), 30)

    def test_plant_abbreviation(self):
        self.assertEqual(self.names("У Самарській області кажуть, що КНПЗ гарно горить"), ["Samara"])


@needs_gazetteer
class TestIncidents(unittest.TestCase):
    """Серії, пояснення заднім числом, відповіді, межі."""

    @classmethod
    def setUpClass(cls):
        from tgmine import geocode as GC
        cls.gaz = GC.Gazetteer.load(GAZ / "RU.txt", GAZ / "UA.txt")
        tg = ROOT / "targets.json"
        cls.targets = json.loads(tg.read_text(encoding="utf-8")) if tg.exists() else None

    def build(self, posts):
        return [x for x in A.build(posts, self.gaz, self.targets) if x["hit"]]

    def test_series_with_replies_is_one_incident(self):
        ps = [post(1, "2026-09-22 04:41", "Еще кадры с Самары, где был атакован НПЗ."),
              post(2, "2026-09-22 04:44", "Еще Самара.", reply=1),
              post(3, "2026-09-22 05:03", "🤯", reply=2),
              post(4, "2026-09-22 05:18", "На Куйбышевском НПЗ в Самаре предварительно горит АВТ-5.")]
        out = self.build(ps)
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0]["place"], out[0]["night"], out[0]["t"], out[0]["n"]),
                         ("Samara", "2026-09-21", "04:41", 4))

    def test_retro_attaches_to_the_night_it_names(self):
        ps = [post(1, "2026-09-15 01:10", "Сизрань під атакою. На Сизранському НПЗ горять резервуари."),
              post(2, "2026-09-22 18:14", "В ніч на 15-те вересня Сили оборони уразили Сизранський НПЗ.")]
        out = self.build(ps)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["night"], "2026-09-14")
        self.assertEqual(out[0]["n"], 2)
        self.assertEqual(out[0]["conf"], "official")

    def test_retro_alone_opens_the_named_night_without_time(self):
        out = self.build([post(1, "2026-09-15 07:09",
                               "11 вересня десяток БПЛА успішно прилетіло по заводу у Губасі. Уражено установки.")])
        self.assertEqual([(x["place"], x["night"], x["t"]) for x in out],
                         [("Gubakha", "2026-09-10", "")])

    def test_confirmation_of_a_known_strike_does_not_open_a_new_one(self):
        ps = [post(1, "2026-09-21 07:51", "Ударні БПЛА Сил Оборони завітали до Уфи."),
              post(2, "2026-09-22 11:02", "Генштаб підтвердив учорашнє ураження НПЗ в Уфі.")]
        out = self.build(ps)
        self.assertEqual([(x["place"], x["night"], x["n"]) for x in out], [("Ufa", "2026-09-20", 2)])

    def test_reply_a_month_later_is_a_new_strike(self):
        ps = [post(1, "2026-07-18 20:19", "Котовськ, горить склад Wildberries після атаки."),
              post(2, "2026-08-25 04:24", "Знову горить склад після атаки дронів.", reply=1)]
        out = self.build(ps)
        self.assertEqual(sorted(x["night"] for x in out), ["2026-07-18", "2026-08-24"])

    def test_series_does_not_swallow_the_next_night(self):
        # пожежа, про яку пишуть щодесять годин, не має злити два удари
        ps = [post(1, "2026-06-15 07:37", "Капотня, горить НПЗ після атаки."),
              post(2, "2026-06-15 16:00", "Капотня, резервуари горять."),
              post(3, "2026-06-16 01:30", "Капотня, пожежа."),
              post(4, "2026-06-17 04:04", "Знову атака на НПЗ у Капотні, момент прилета.")]
        out = self.build(ps)
        self.assertEqual(sorted(x["night"] for x in out), ["2026-06-14", "2026-06-16"])

    def test_fire_without_a_strike(self):
        # пожежа без атаки на звичайному обʼєкті — не наслідок удару
        self.assertEqual(self.build([post(1, "2026-08-19 13:01", "У Чебоксарах горить підстанція.")]), [])
        # на НПЗ — наслідок, навіть без слова «атака»
        out = self.build([post(1, "2026-06-06 09:14", "В Тюмені горить Антипінський НПЗ.")])
        self.assertEqual(len(out), 1)

    def test_ukraine_controlled_territory_is_dropped(self):
        self.assertEqual(self.build([post(1, "2026-09-09 13:00", "У Києві після атаки горить склад.")]), [])

    def test_two_places_of_one_post_have_distinct_ids(self):
        out = self.build([post(1, "2026-09-07 07:33", "Сіріус і Сочі: після атаки горять нафтобази.")])
        ids = [x["id"] for x in out]
        self.assertEqual(len(ids), len(set(ids)))

    def test_retro_incident_does_not_swallow_a_new_strike(self):
        # рецензія 23.09: пояснення «11 вересня» відкриває ніч 10.09 без
        # часу, і живий удар за дві години мусить піти на свою ніч
        ps = [post(1, "2026-09-15 07:09", "11 вересня десяток БПЛА прилетіло по заводу у Губасі. Уражено установки."),
              post(2, "2026-09-15 09:30", "Губаха зараз під атакою, горить завод.")]
        self.assertEqual(sorted(x["night"] for x in self.build(ps)), ["2026-09-10", "2026-09-14"])

    def test_todays_date_is_not_retro(self):
        out = self.build([post(1, "2026-07-06 14:02", "Ураження Омського НПЗ 06.07.2026, горить установка.")])
        self.assertEqual([(x["night"], x["t"]) for x in out], [("2026-07-06", "14:02")])

    def test_series_does_not_replace_a_resolved_city(self):
        ps = [post(1, "2026-09-10 02:00", "Нижній Новгород, після атаки горить НПЗ."),
              post(2, "2026-09-10 04:00", "Великий Новгород, пожежа після атаки дронів.")]
        self.assertEqual(sorted(x["place"] for x in self.build(ps)), ["Nizhniy Novgorod", "Velikiy Novgorod"])

    def test_malformed_coordinates_do_not_crash(self):
        self.assertEqual(A.coords_in("44°56’36..5”N 34°13’12”E"), [])
        self.build([post(1, "2026-09-10 02:00", "Уражено склад 44°56’36..5”N 34°13’12”E після атаки")])

    def test_ruins_are_details_of_the_known_strike(self):
        # «Все що залишилося від хабу» наступного ранку — той самий удар, а не
        # новий інцидент на ніч поста (замір 23.09, Сімферополь)
        ps = [post(1, "2026-07-24 19:56", "У ніч на 24.07.2026 підтверджено ураження розподільчого "
                                          "центру Wildberries у м. Сімферополь, виникла масштабна пожежа."),
              post(2, "2026-07-25 10:19", "Все що залишилося від логістичного хабу Wildberries після "
                                          "атаки БПЛА в окупованому Сімферополі.", reply=1)]
        self.assertEqual([(x["night"], x["n"]) for x in self.build(ps)], [("2026-07-23", 2)])

    def test_anniversary_word_does_not_hide_a_fresh_strike(self):
        out = self.build([post(1, "2026-08-24 03:00", "У річницю Незалежності дрони уразили НПЗ у Саратові. Горять резервуари.")])
        self.assertEqual([x["place"] for x in out], ["Saratov"])
        out = self.build([post(1, "2026-06-01 09:14", "Сьогодні рік, як «Павутина». Аеродром Бєлая у вогні і диму.")])
        self.assertEqual(out, [])

    def test_old_dates_are_history(self):
        # давній пост — нічого; довідка з давньою датою не ховає свіжого удару
        self.assertEqual(self.build([post(1, "2026-07-21 10:00", "9 травня 2014 року. / Маріуполь. / "
                                               "БМП-2 проривається крізь барикади, горить.")]), [])
        out = self.build([post(2, "2026-07-14 14:22", "ВМС ЗС України знищили прикордонний корабель «Ізумруд» "
                                                  "неподалік Новоросійська. Саме «Ізумруд» 25 листопада 2018 "
                                                  "року брав участь у нападі в Керченській протоці.")])
        self.assertEqual([(x["place"], x["night"]) for x in out], [("Novorossiysk", "2026-07-14")])

    def test_old_sentence_and_old_reply(self):
        # давнє речення не дає свого міста, хоч решта поста — свіжий удар
        # (і не чіпляється поясненням до свіжого інциденту того міста)
        out = self.build([post(3, "2026-07-12 03:00", "Керч, після атаки горить нафтобаза."),
                          post(1, "2026-07-14 14:22", "ВМС знищили корабель «Ізумруд» неподалік Новоросійська. "
                                                  "Саме він 25 листопада 2018 року горів у Керчі після зіткнення.")])
        self.assertEqual(sorted((x["place"], x["n"]) for x in out), [("Kerch", 1), ("Novorossiysk", 1)])
        # давній пост-відповідь не йде в інцидент батька
        ps = [post(1, "2026-07-21 03:00", "Маріуполь, після атаки горить склад."),
              post(2, "2026-07-21 08:00", "9 травня 2014 року. БМП-2 проривається крізь барикади, вибухи.", reply=1)]
        self.assertEqual([x["n"] for x in self.build(ps)], [1])

    def test_coastal_in_small_places(self):
        out = self.build([post(1, "2026-08-12 18:21", "Новоросійськ 12.08. Уражено фрегати на базі ВМФ. "
                                                  "Берегова інфраструктура: зафіксовано декілька уражень.")])
        self.assertEqual([x["place"] for x in out], ["Novorossiysk"])

    def test_refinery_name_matches_the_city(self):
        self.assertTrue(A._names_city("Астраханський ГПЗ", ["астрахан"]))
        self.assertTrue(A._names_city("Куйбишевський НПЗ (Самара)", ["самара"]))
        self.assertFalse(A._names_city("Краснодарський НПЗ", ["красногвардеиское"]))
        self.assertFalse(A._names_city('Нефтеперерабатывающий завод "Роснефть"', ["нефтегорск"]))

    def test_refinery_stem_is_a_whole_name(self):
        # «нефте» з «Нефтеперерабатывающий» — не Нефтегорськ (57 км до Туапсе)
        out = self.build([post(1, "2026-08-22 05:19", "Нефтегорск, Краснодарский край: атака на НПЗ, пожар.")])
        self.assertEqual([x["refinery"] for x in out], [None])

    def test_continuing_fire_without_a_known_strike(self):
        # серія, де з першого поста «продолжает гореть» — удар таки був
        out = self.build([post(1, "2026-08-10 08:17", "В Нижнекамске продолжает гореть НПЗ после атаки.")])
        self.assertEqual([x["place"] for x in out], ["Nizhnekamsk"])

    def test_continuing_fire_joins_the_known_strike(self):
        ps = [post(1, "2026-06-28 03:00", "Слов'янськ-на-Кубані, після атаки горить НПЗ."),
              post(2, "2026-06-30 10:00", "У Слов'янську-на-Кубані продовжує горіти НПЗ.")]
        self.assertEqual([(x["night"], x["n"]) for x in self.build(ps)], [("2026-06-27", 2)])

    def test_reply_goes_to_its_root_not_to_the_series(self):
        # 19270 (23.04): відповідь без місця на самарський корінь — у Самару,
        # хоч останній пост каналу про Кстово
        ps = [post(1, "2026-04-23 02:39", "Самара, местные жители сообщают о взрывах."),
              post(2, "2026-04-23 04:30", "Кстово, горит НПЗ после атаки."),
              post(3, "2026-04-23 04:50", "Ураження зазнала установка, пожежа.", reply=1)]
        out = {x["place"]: sorted(int(s["u"].rsplit("/", 1)[1]) for s in x["src"]) for x in self.build(ps)}
        self.assertEqual(out, {"Samara": [1, 3], "Kstovo": [2]})
        # корінь без інциденту («Санкции в работе.») — відповідь усе одно не
        # стає продовженням чужої серії
        ps = [post(1, "2026-04-18 06:15", "Санкции в работе."),
              post(2, "2026-04-23 04:30", "Кстово, горит НПЗ после атаки."),
              post(3, "2026-04-23 04:50", "Ураження зазнала установка, пожежа.", reply=1)]
        self.assertEqual([x["n"] for x in self.build(ps)], [1])

    def test_placeless_post_continues_the_series(self):
        ps = [post(1, "2026-07-06 14:05", "Омськ, горить найбільший в рф НПЗ після атаки."),
              post(2, "2026-07-06 14:35", "Розгорівся."),
              # інша подія з нерозвʼязаною назвою — не продовження
              post(3, "2026-07-06 14:40", "Окупований Сокологірськ, Луганської обл., пожежа."),
              # довгий пост без місця — не продовження
              post(4, "2026-07-06 14:45", "Горить. " + "дуже багато слів про щось інше, не про серію взагалі. " * 3),
              # поза вікном серії
              post(5, "2026-07-06 16:00", "Горить.")]
        out = self.build(ps)
        self.assertEqual([sorted(int(s["u"].rsplit("/", 1)[1]) for s in x["src"]) for x in out], [[1, 2]])

    def test_series_needs_one_incident_with_a_consequence(self):
        # дві серії впереміш — не серія; інцидент без наслідку — не ціль
        ps = [post(1, "2026-04-23 04:00", "Самара, горить нафтохімічний завод після атаки."),
              post(2, "2026-04-23 04:05", "Кстово, горить НПЗ після атаки."),
              post(3, "2026-04-23 04:10", "Горить."),
              post(4, "2026-06-02 20:00", "Привет ПВОшникам с Валдая."),
              post(5, "2026-06-02 20:05", "Горит.")]
        out = self.build(ps)
        self.assertEqual(sorted(x["n"] for x in out), [1, 1])

    def test_ruins_without_a_known_strike_open_one(self):
        # руїни — перше повідомлення про удар: інцидент є, як і до правила
        out = self.build([post(1, "2026-08-04 10:00", "Все что осталось от склада ВБ в Алексине после атаки.")])
        self.assertEqual([(x["place"], x["night"]) for x in out], [("Aleksin", "2026-08-03")])

    def test_refinery_of_another_town_is_not_taken(self):
        # Чапаєвськ — не НПЗ Новокуйбишевська за 30 км
        out = self.build([post(1, "2026-08-22 05:19", "Чапаєвськ, після атаки горить НПЗ.")])
        self.assertEqual([x["refinery"] for x in out], [None])

    def test_named_plant_far_from_its_city(self):
        # Астраханський ГПЗ — у Аксарайському, за 53 км від Астрахані;
        # «газопереробний завод» — той самий обʼєкт, що й «ГПЗ»
        out = self.build([post(1, "2026-08-24 18:03", "Збройні Сили України успішно уразили "
                               "Астраханський газопереробний завод (АГПЗ).")])
        self.assertEqual([x["refinery"] for x in out], ["Астраханський ГПЗ"])
        self.assertGreater(out[0]["lat"], 46.7)

    def test_deterministic_and_order_independent(self):
        ps = [post(1, "2026-09-22 04:41", "Еще кадры с Самары, где был атакован НПЗ."),
              post(2, "2026-09-22 04:44", "Еще Самара.", reply=1),
              post(3, "2026-09-15 01:10", "Сизрань під атакою. На Сизранському НПЗ горять резервуари."),
              post(4, "2026-09-22 18:14", "В ніч на 15-те вересня Сили оборони уразили Сизранський НПЗ."),
              post(5, "2026-09-19 04:11", "Софьино, сообщают об атаке на складские помещения.")]
        a = A.build(ps, self.gaz, self.targets)
        random.Random(1).shuffle(ps)
        b = A.build(ps, self.gaz, self.targets)
        self.assertEqual(json.dumps(a, sort_keys=True, ensure_ascii=False),
                         json.dumps(b, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
