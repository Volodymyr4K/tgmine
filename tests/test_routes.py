"""Зшивання маршрутів: кожен тест — по вже виправленій помилці.

Ланка тут — заявлений каналом вектор руху («від Х у напрямку Y»). Маршрут —
ланцюг таких ланок, що описує рух ОДНІЄЇ групи. Помилка зшивання не падає й
не помітна в числах: вона просто малює на карті шлях, якого не було.
"""
import unittest
from datetime import datetime, timedelta, timezone

from tgmine import routes as RT

MSK = timezone(timedelta(hours=3))
T0 = datetime(2026, 7, 27, 22, 0, tzinfo=MSK)


def vec(src, dst, minutes, src_name="Бірюч", dst_name="Олексіївка",
        text="Группа БПЛА в направлении Алексеевки"):
    return {"t": (T0 + timedelta(minutes=minutes)).isoformat(),
            "url": "https://t.me/x/1", "src": list(src), "dst": list(dst),
            "src_name": src_name, "dst_name": dst_name, "text": text,
            "hhmm": (T0 + timedelta(minutes=minutes)).strftime("%H:%M")}


def raid(vectors, events=()):
    return {"vectors": list(vectors), "events": list(events)}


class TestAreaEndpoints(unittest.TestCase):
    """Кінець ланки, геокодований в ОБЛАСТЬ, — не місце, а 30 тисяч кв. км.

    Через такі кінці ланцюг стрибав Бєлгородська -> Тамбовська за 402 км і
    видавав 688 км/год, тобто зшивав РІЗНІ групи через центри областей.
    """

    def test_oblast_endpoint_dropped(self):
        rs, meta = RT.build(raid([
            vec((50.6, 38.4), (51.7, 39.2), 0,
                "Belgorod Oblast", "Voronezh Oblast")]))
        self.assertEqual(meta["hops"], 0)
        self.assertEqual(rs, [])

    def test_district_endpoint_kept(self):
        """Район — це 40 км, з ним ланцюг ще має сенс і лишається."""
        rs, meta = RT.build(raid([
            vec((50.6, 38.4), (51.2, 39.0), 0,
                "Rovenskiy Rayon", "Ostrogozhskiy Rayon")]))
        self.assertEqual(meta["hops"], 1)


class TestNonsenseHops(unittest.TestCase):
    """Три види ланок, які виглядали рухом, але ним не були.

    Виміряно на чотирьох ночах (182 підказки): 25% ішли НАЗАД до кордону,
    частина кінців опинялась за сотні кілометрів від області, про яку сам
    пост, а окремі «маршрути» зʼєднували район із його ж центром.
    """

    def test_district_and_its_own_centre_is_not_movement(self):
        """«Киришський район -> Кириші» — те саме місце, названо двічі.

        Відстань тут не показник: у помилковому збігу «Ярославський район»
        (у Москві) -> «Ярославль» вона доходить до 237 км.
        """
        rs, meta = RT.build(raid([
            vec((59.4, 32.0), (59.9, 32.6), 0, "Kirishskiy Rayon", "Kirishi")]))
        self.assertEqual(meta["dropped"]["same"], 1)
        self.assertEqual(rs, [])

    def test_endpoint_far_from_post_region_is_dropped(self):
        """Кінець за 300+ км від області поста — майже завжди омонім.

        Так «Херсонес» (Севастополь) їхав на Херсонщину за 363 км, а
        «Саратовська» з Волгоградщини виявлялась станицею на Кубані.
        95% справжніх кінців лежать у межах 286 км від центру своєї області.
        """
        v = vec((48.7, 44.5), (47.2, 39.7), 0, "Volgograd", "Saratovskaya")
        r = raid([v])
        r["events"] = [{"url": v["url"], "region": "Волгоградська"}]
        r["region_geo"] = {"Волгоградська": [49.6, 44.0]}
        rs, meta = RT.build(r)
        self.assertEqual(meta["dropped"]["homonym"], 1)
        self.assertEqual(rs, [])

    def test_inland_hop_towards_border_is_weak(self):
        """У глибині країни рух назад до кордону — привід засумніватись."""
        rs, _ = RT.build(raid([
            vec((54.5, 36.3), (53.6, 35.2), 0, "Kaluga", "Khvastovichi")]))
        self.assertEqual(rs[0]["conf"], "weak")


class TestChainPhysics(unittest.TestCase):
    """Три обмеження продовження ланцюга, кожне з причини."""

    def test_reverse_turn_not_chained(self):
        """Без межі повороту ланцюг «вертався» по своїх слідах.

        У сирих даних це видно як Борисоглєбськ, що повторюється шість разів
        поспіль: те саме місце зшивалось саме з собою в обидва боки.
        """
        rs, _ = RT.build(raid([
            vec((51.0, 40.0), (51.5, 41.0), 0),
            vec((51.5, 41.0), (51.0, 40.0), 25),      # назад тим самим шляхом
        ]))
        self.assertTrue(all(r["n"] <= 2 for r in rs),
                        "ланка назад не має продовжувати маршрут")

    def test_impossible_speed_not_chained(self):
        """400 км за 10 хвилин — це 2400 км/год, ударний БпЛА так не літає."""
        rs, _ = RT.build(raid([
            vec((50.0, 36.0), (50.4, 36.6), 0),
            vec((50.4, 36.6), (53.5, 41.0), 10),
        ]))
        self.assertTrue(all(r["n"] <= 2 for r in rs))

    def test_plausible_continuation_is_chained(self):
        """Правдоподібне продовження зшивається в один маршрут."""
        rs, _ = RT.build(raid([
            vec((50.0, 36.0), (50.8, 36.8), 0),
            vec((50.8, 36.8), (51.6, 37.6), 40),
        ]))
        self.assertEqual(len(rs), 1)
        self.assertEqual(rs[0]["n"], 3)
        self.assertEqual(rs[0]["legs"], ["declared", "declared"])


class TestShortRoutes(unittest.TestCase):
    """Поріг довжини. Правило «маршрут це щонайменше дві ланки» викидало
    60-75% заявленого: на шести ночах одноланкових ланцюгів було 20-75 за
    ніч із медіаною довжини 60-125 км. Тобто зникав спостережений рух на
    сотню кілометрів між двома НАЗВАНИМИ місцями, і типова ніч виглядала
    порожньою.
    """

    def test_single_long_hop_is_a_route(self):
        rs, _ = RT.build(raid([vec((50.0, 36.0), (50.9, 37.2), 0)]))
        self.assertEqual(len(rs), 1)
        self.assertGreater(rs[0]["km"], RT.MIN_ROUTE_KM)

    def test_hop_in_place_dropped(self):
        """Ланка «на місці» — це повтор того самого повідомлення, не рух."""
        rs, meta = RT.build(raid([vec((50.0, 36.0), (50.02, 36.02), 0)]))
        self.assertEqual(meta["hops"], 0)
        self.assertEqual(rs, [])


class TestDeclaredMarking(unittest.TestCase):
    """Ланка треку, підтверджена вектором, має бути позначена як заявлена.

    Інакше на карті здогад (асоціація фіксацій за швидкістю й курсом) виглядав
    би так само, як пряме свідчення каналу про напрямок.
    """

    def _events(self):
        # крок ~83 км за 30 хв = 166 км/год: усередині смуги трекера
        # (130-220 км/год), інакше фіксації в трек не звʼязуються
        pts = [(50.0, 36.0), (50.6, 36.7), (51.2, 37.4)]
        out = []
        for i, (la, lo) in enumerate(pts):
            t = T0 + timedelta(minutes=30 * i)
            out.append({"t": t.isoformat(), "scope": "точка", "lat": la, "lon": lo,
                        "geo_conf": "region", "place": f"Місце {i}", "kind": "фіксація",
                        "url": "https://t.me/x/2", "depth": 100 + i,
                        "hhmm": t.strftime("%H:%M")})
        return out

    def test_leg_with_matching_vector_is_declared(self):
        rs, _ = RT.build(raid([vec((50.0, 36.0), (50.6, 36.7), 0)], self._events()))
        track = [r for r in rs if r["src"] == "трек"]
        self.assertTrue(track, "трек із трьох фіксацій має зібратись")
        self.assertEqual(track[0]["legs"][0], "declared")
        self.assertEqual(track[0]["legs"][1], "inferred")


class TestConfidence(unittest.TestCase):
    """Маршрут несе оцінку впевненості, бо підказки різні за силою.

    Мірка не з голови: ланка ВСЕРЕДИНІ зшитого ланцюга (рух, підтверджений
    кількома повідомленнями) має медіану 84 км і 95-й перцентиль 169 км на
    трьох ночах. Одноланкове твердження на 480 км нічим із цього не
    підтримане — його не викидають, а позначають слабким.
    """

    def test_chain_is_strong(self):
        rs, _ = RT.build(raid([
            vec((50.0, 36.0), (50.8, 36.8), 0),
            vec((50.8, 36.8), (51.6, 37.6), 40),
        ]))
        self.assertEqual(rs[0]["conf"], "strong")

    def test_short_single_hop_is_ok(self):
        rs, _ = RT.build(raid([vec((50.0, 36.0), (50.9, 37.2), 0)]))
        self.assertEqual(rs[0]["conf"], "ok")

    def test_overlong_single_hop_is_weak(self):
        """480 км однією ланкою — довше за будь-яку ланку зшитого ланцюга."""
        rs, _ = RT.build(raid([vec((48.5, 35.0), (44.9, 33.6), 0,
                                   "Dnipro", "Chornomorske")]))
        self.assertEqual(rs[0]["conf"], "weak")
        self.assertGreater(rs[0]["km"], RT.PLAUSIBLE_HOP_KM)


class TestDuplicateClaims(unittest.TestCase):
    """Той самий коридор від кількох каналів — один маршрут і лічильник.

    kupolrussia дзеркалить lpr1, тому «Киришський район -> Кириші» приходило
    тричі й малювалось трьома маршрутами один на одному. Це один рух і три
    згадки: свідчення сильніше, ліній не більше.
    """

    def test_same_corridor_merged_with_count(self):
        # Назви беремо РІЗНІ: «Киришський -> Кириші» тепер відсіюється як
        # район і його ж центр, а тут перевіряється саме злиття дублів.
        rs, _ = RT.build(raid([
            vec((52.4, 32.2), (53.0, 33.1), 0, "Klintsy", "Surazh"),
            vec((52.4, 32.2), (53.0, 33.1), 5, "Klintsy", "Surazh"),
            vec((52.4, 32.2), (53.0, 33.1), 9, "Klintsy", "Surazh"),
        ]))
        self.assertEqual(len(rs), 1, "три згадки одного коридору — один маршрут")
        self.assertEqual(rs[0]["claims"], 3)


class TestBackExtension(unittest.TestCase):
    """Маршрут добудовується назад лише РЕАЛЬНИМИ спостереженнями.

    Апарат не зʼявляється в глибині країни нізвідки, але домальовувати лінію
    до кордону не можна: перевірка «сховай першу точку й вгадай її з решти»
    дає кутову похибку 23° (медіана) і 43° на 90-му перцентилі, тобто на
    300 км це сектор ±280 км.

    Тому назад маршрут тягнеться тільки до тих фіксацій, які справді були, і
    лише в межах порогів, перевірених нуль-тестом (див. routes.py).
    """

    def _ev(self, la, lo, minutes, depth):
        t = T0 + timedelta(minutes=minutes)
        return {"t": t.isoformat(), "scope": "точка", "lat": la, "lon": lo,
                "geo_conf": "region", "place": "Місце", "kind": "фіксація",
                "url": "https://t.me/x/3", "depth": depth,
                "hhmm": t.strftime("%H:%M")}

    def _track(self):
        # три фіксації = трек углиб (перша ближча до кордону)
        return [self._ev(50.0, 36.0, 0, 200), self._ev(50.6, 36.7, 30, 280),
                self._ev(51.2, 37.4, 60, 360)]

    def test_associator_links_predecessor_itself(self):
        """Близького попередника асоціатор бере сам, добудова не потрібна.

        Раніше цей випадок ловила добудова назад — бо жадібний трекер його
        просто не зв'язував. Калман із глобальним призначенням зв'язує, і
        точка входить у трек як звичайна ланка, а не як припущення.
        """
        ev = self._track()
        ev.append(self._ev(49.4, 35.3, -40, 120))     # 40 хв раніше, позаду
        rs, meta = RT.build(raid([], ev))
        track = [r for r in rs if r["src"] == "трек"][0]
        self.assertEqual(track["n"], 4)
        self.assertEqual(meta["extended"], 0)
        self.assertFalse(any(p.get("back") for p in track["pts"]))

    def test_far_predecessor_needs_back_extension(self):
        """Попередник за межею вікна трекера (розрив 45 хв) — робота добудови."""
        ev = self._track()
        ev.append(self._ev(48.9, 34.6, -75, 90))
        rs, meta = RT.build(raid([], ev))
        track = [r for r in rs if r["src"] == "трек"][0]
        self.assertEqual(meta["extended"], 1)
        self.assertTrue(track["pts"][0].get("back"))
        self.assertEqual(track["legs"][0], "inferred",
                         "добудована ланка це асоціація, а не заявлений напрямок")

    def test_predecessor_deeper_inland_is_ignored(self):
        """Крок «вглиб» не є приходом: напрямок має бути від кордону."""
        ev = self._track()
        ev.append(self._ev(49.4, 35.3, -40, 500))     # далі від кордону
        _, meta = RT.build(raid([], ev))
        self.assertEqual(meta["extended"], 0)

    def test_too_far_predecessor_is_ignored(self):
        """400 км назад за 40 хв — це 600 км/год, не БпЛА."""
        ev = self._track()
        ev.append(self._ev(47.0, 33.0, -40, 60))
        _, meta = RT.build(raid([], ev))
        self.assertEqual(meta["extended"], 0)


class TestWeaponClass(unittest.TestCase):
    """Клас засобу визначається з тексту: у сховищі його нема."""

    def test_classes(self):
        self.assertEqual(RT.klass("Тревога по БПЛА"), "БПЛА")
        self.assertEqual(RT.klass("Ракетная опасность"), "ракета")
        self.assertEqual(RT.klass("Угроза применения КАБ"), "УАБ")
        self.assertEqual(RT.klass("Работа РСЗО"), "РСЗО")
        self.assertEqual(RT.klass("Взрывы в городе"), "невідомо")

    def test_guided_bomb_is_not_a_missile(self):
        """«Авиационная ракетно бомбовая опасность» — це УАБ, і воно не має
        вмикати ще й клас «ракета»: інакше кореляція УАБ/ракета фіктивна."""
        self.assertEqual(RT.klass("Авиационная ракетно бомбовая опасность"), "УАБ")


if __name__ == "__main__":
    unittest.main()


class TestRouteType(unittest.TestCase):
    """`u` — найточніша назва засобу зі сховища (store.utype), найчастіша по
    вузлах маршруту; вузли без типу не голосують; `k` (клас) лишається."""

    def _events(self, utypes):
        pts = [(50.0, 36.0), (50.6, 36.7), (51.2, 37.4)]
        out = []
        for i, ((la, lo), u) in enumerate(zip(pts, utypes)):
            t = T0 + timedelta(minutes=30 * i)
            out.append({"t": t.isoformat(), "scope": "точка", "lat": la, "lon": lo,
                        "geo_conf": "region", "place": f"Місце {i}", "kind": "фіксація",
                        "url": f"https://t.me/x/{i}", "depth": 100 + i,
                        "hhmm": t.strftime("%H:%M"), "utype": u})
        return out

    def test_majority_type_and_nodes_carry_it(self):
        rs, _ = RT.build(raid([], self._events(["Фламінго", None, "Фламінго"])))
        self.assertEqual(len(rs), 1)
        self.assertEqual(rs[0]["u"], "Фламінго")
        self.assertEqual([p.get("u") for p in rs[0]["pts"]], ["Фламінго", None, "Фламінго"])

    def test_no_types_gives_none(self):
        rs, _ = RT.build(raid([], self._events([None, None, None])))
        self.assertEqual(len(rs), 1)
        self.assertIsNone(rs[0]["u"])


class TestModeIsDeterministic(unittest.TestCase):
    def test_tie_goes_to_first_seen_regardless_of_hash_seed(self):
        import subprocess, sys
        code = ("from tgmine.routes import _mode;"
                "print(_mode(['Хорнет','БпЛА','ФПВ','БпЛА','Хорнет','ФПВ']))")
        outs = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                               env={**__import__("os").environ, "PYTHONHASHSEED": str(s)}).stdout
                for s in range(8)}
        self.assertEqual(outs, {"Хорнет\n"})
