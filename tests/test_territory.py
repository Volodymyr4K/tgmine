"""Відсів українських обʼєктів із переліку цілей.

Тест стоїть по конкретній помилці, а не «про всяк випадок». У targets.json
лежало 182 українських обʼєкти: 60 у Києві, 15 навколо Чорнобаївки, серед них
вісім ярусу 1 — авіабаза Васильків, Краматорськ, п'ять записів «Аеродром
(Kherson)». Усі публікувались на карті з координатами, ярусом і лічильником
влучань, тобто у вигляді переліку цілей.

Пошук за назвою їх не бачив: у 178 із 182 у назві нема слова «Україна», вони
звуться «Військовий обʼєкт (Kyiv)» чи «Полігон». Тому перевірка геометрична.
"""
import json
import unittest

from tests.helpers import GAZ, ROOT
from tgmine.territory import Borders, UA_CONTESTED, depth_km, filter_objects, is_excluded

SHP = GAZ / "ne_10m_admin_1_states_provinces"
TARGETS = ROOT / "targets.json"


@unittest.skipUnless(SHP.with_suffix(".shp").exists(), "нема газетира")
class TestNoUkrainianTargets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.borders = Borders.load(SHP)

    @unittest.skipUnless(TARGETS.exists(), "нема targets.json")
    def test_published_set_has_no_ukrainian_controlled_objects(self):
        with TARGETS.open(encoding="utf-8") as fh:
            objs = json.load(fh)["objects"]
        bad = []
        for o in objs:
            a3, region = self.borders.locate(o["lat"], o["lon"])
            # Окуповані області лишаються свідомо: Мелітополь і Луганськ — це
            # рівно те, за чим проєкт і стежить. Усе інше в межах України — ні.
            if a3 == "UKR" and region not in UA_CONTESTED:
                bad.append(f'{o.get("osm")} {region} {o.get("name")}')
        self.assertEqual(bad, [], f"українські обʼєкти в переліку: {bad[:5]}")

    def test_filter_drops_kyiv_and_keeps_melitopol(self):
        # Мелітопольський аеродром — найчастіше згадувана ціль набору (211
        # влучань). Якщо фільтр колись почне різати за країною без огляду на
        # контроль, зникне саме він, і втрата буде мовчазною.
        kyiv = {"osm": "w1", "lat": 50.401, "lon": 30.452, "name": "Авіабаза Васильків"}
        melitopol = {"osm": "w146508255", "lat": 46.881, "lon": 35.307,
                     "name": "Melitopol Air Base"}
        kept = filter_objects([kyiv, melitopol], self.borders, log=lambda *a: None)
        self.assertEqual([o["osm"] for o in kept], ["w146508255"])

    def test_manual_exclusions_are_still_reachable(self):
        # EXCLUDE_OSM — знімок на дату, а не правило. Якщо перезбір змінить id,
        # список тихо перестане діяти, і Чорнобаївка повернеться на карту.
        from tgmine.territory import EXCLUDE_OSM

        if not TARGETS.exists():
            self.skipTest("нема targets.json")
        with TARGETS.open(encoding="utf-8") as fh:
            objs = json.load(fh)["objects"]
        live = {o.get("osm") for o in objs}
        self.assertEqual(EXCLUDE_OSM & live, set(),
                         "обʼєкт зі списку ручного відсіву присутній у targets.json")


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(SHP.with_suffix(".shp").exists(), "нема газетира")
class TestUnlocatedPoints(unittest.TestCase):
    """Точка, яку межі не впізнали, теж іде геть — але не наосліп.

    Правило проєкту для сумнівних — прибирати. `is_excluded` натомість
    ЛИШАВ обʼєкт, якщо `locate` повернув (None, None), тобто діяв рівно
    навпаки. Сьогодні це коштувало нуль (усіх таких 48, і всі російські чи
    окуповані), але діра відкривалась би після кожного перезбору targets.

    Прибирати нелокалізоване наосліп теж не можна: усі 48 — прибережні,
    максимум 4.5 км від контуру NE, і серед них Шесхаріс (жар 78) та склад
    БК Yany Kapu (жар 43). Тому спершу найближчий полігон у межах 10 км.
    """

    @classmethod
    def setUpClass(cls):
        cls.borders = Borders.load(SHP)

    def test_coastal_russian_objects_stay(self):
        """Причал за кілометр від контуру — це той самий берег."""
        for name, lat, lon in [("Шесхаріс (Новоросійськ)", 44.7, 37.8),
                               ("Склад БК (Yany Kapu)", 46.09676, 33.63691),
                               ("Нафтопорт Приморськ", 60.35, 28.68)]:
            with self.subTest(name=name):
                self.assertIsNone(
                    is_excluded({"lat": lat, "lon": lon, "name": name},
                                self.borders))

    def test_open_sea_is_dropped(self):
        """Ціль посеред Чорного моря — це або сміття, або не ціль."""
        why = is_excluded({"lat": 43.2, "lon": 32.0}, self.borders)
        self.assertIsNotNone(why)
        self.assertIn("не впізнали", why)

    def test_ukrainian_coast_is_dropped(self):
        """Саме той випадок, проти якого правило: берег під Одесою."""
        why = is_excluded({"lat": 46.35, "lon": 30.68}, self.borders)
        self.assertIsNotNone(why)
        self.assertIn("Одесская", why)

    def test_distance_is_to_the_segment_not_the_vertex(self):
        """Мілини Азова й Сиваша: контур там прокладено довгими прямими.

        Заміряно: у театрі 2348 відрізків контуру довші за 10 км, і в 12
        місцях точка за 2 км від такої прямої лежить далі 10 км від ОБОХ її
        кінців. Найгірше — Азов біля Криму: 20 км до вершини при 2 км до
        відрізка. За вершинами такий обʼєкт не знайшов би нічого й пішов би
        у відсів як «не впізнали», хоча це кримське узбережжя.
        """
        lat, lon = 45.5307, 35.2097
        self.assertEqual(self.borders.locate(lat, lon), (None, None),
                         "точка мала б лежати поза полігонами")
        self.assertEqual(self.borders.nearest(lat, lon)[0], "RUS")
        self.assertIsNone(is_excluded({"lat": lat, "lon": lon}, self.borders))

    def test_current_set_loses_nothing(self):
        """Правка не має нічого викидати з наявного переліку."""
        if not TARGETS.exists():
            self.skipTest("нема targets.json")
        objs = json.loads(TARGETS.read_text(encoding="utf-8"))["objects"]
        dropped = [o for o in objs if o.get("lat") is not None
                   and is_excluded(o, self.borders)]
        self.assertEqual(dropped, [], f"відсіялось зайве: {dropped[:3]}")


class TestDepthReference(unittest.TestCase):
    """«Глибина» — відстань до підконтрольної Україні території.

    Раніше — до найближчої з ВОСЬМИ точок ламаної, намальованої від руки, у
    трьох копіях. Держкордон як референс відкинуто числом: Мелітополь,
    Донецьк, Генічеськ за Natural Earth — Україна, 7.4% точкових подій мали б
    глибину 0, а «заходів» (<60 км) ставало б удвічі-втричі більше.
    Підконтрольна територія на рівні областей дає майже те саме, що ламана
    (медіана 248 проти 242, p90 661 проти 675), але з файлу і без аномалії в
    Криму. Файл `ukraine_controlled.json` — у репозиторії, шейпфайл не
    потрібен, тому тест іде і на чистому клоні.
    """

    def test_controlled_ukraine_is_zero(self):
        self.assertEqual(depth_km(49.99, 36.23), 0.0)      # Харків

    def test_occupied_south_is_not_ukraine_for_depth(self):
        """Саме те, на чому держкордон брехав би нулем."""
        for name, la, lo in [("Мелітополь", 46.85, 35.37), ("Донецьк", 48.0, 37.8),
                             ("Генічеськ", 46.17, 34.8)]:
            with self.subTest(name=name):
                self.assertGreater(depth_km(la, lo), 40)

    def test_crimea_is_measured_from_the_mainland(self):
        self.assertGreater(depth_km(44.6, 33.5), 200)      # Севастополь

    def test_known_distances(self):
        self.assertAlmostEqual(depth_km(55.75, 37.6), 447, delta=15)   # Москва
        self.assertAlmostEqual(depth_km(50.6, 36.6), 35, delta=8)      # Бєлгород

    def test_oblast_granularity_is_the_documented_price(self):
        """Запоріжжя-місто підконтрольне, але вся область рахується як ні.

        Тому глибина там не 0, а ~18 км — і саме це написано на сторінці.
        Якщо цей тест упав, бо стало 0 — хтось додав лінію зіткнення, чого
        CLAUDE.md прямо забороняє.
        """
        d = depth_km(47.84, 35.14)
        self.assertGreater(d, 5)
        self.assertLess(d, 60)


class TestOneDepthImplementation(unittest.TestCase):
    """Глибина рахується в одному місці. Було три копії ламаної й чотири
    функції (store.depth_km, raid.depth, routes.depth_of x2) — і всі від руки."""

    def test_no_hand_drawn_border_left(self):
        """Шукає перший вузол старої ламаної (52.15, 31.79), не імʼя змінної."""
        hits = []
        for p in sorted(ROOT.glob("*.py")) + sorted((ROOT / "tgmine").glob("*.py")):
            src = p.read_text(encoding="utf-8")
            if "52.15, 31.79" in src:
                hits.append(p.name)
        self.assertEqual(hits, [], f"ламана лишилась у: {hits}")

    def test_depth_defined_once(self):
        import ast
        found = []
        for p in sorted(ROOT.glob("*.py")) + sorted((ROOT / "tgmine").glob("*.py")):
            for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                if isinstance(n, ast.FunctionDef) and n.name in ("depth_km", "depth", "depth_of"):
                    found.append(f"{p.name}:{n.name}")
        # обгортки в store/raid/routes лишаються, але всі кличуть territory
        self.assertIn("territory.py:depth_km", found)
        for p in sorted(ROOT.glob("*.py")) + sorted((ROOT / "tgmine").glob("*.py")):
            src = p.read_text(encoding="utf-8")
            if p.name in ("store.py", "raid.py", "routes.py"):
                self.assertIn("T.depth_km(", src, f"{p.name} рахує глибину не через territory")
