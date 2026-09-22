"""Памʼять коридорів і містки ночі (tgmine/linker.py, BACKLOG §16.13-16.14).

Місток видно оператору з підписом «звичний коридор · N ноч.», тож N — це
твердження, і воно має бути правдою: скільки РІЗНИХ попередніх ночей.
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tgmine import linker as L


def leg(a, c):
    return ["A", a[0], a[1], False, "C", c[0], c[1], False]


class Store:
    def __init__(self, days):
        self.root = Path(tempfile.mkdtemp())
        ev = self.root / "events"
        ev.mkdir()
        for d, legs in days.items():
            with open(ev / f"{d}.jsonl", "w", encoding="utf-8") as f:
                f.write(json.dumps({"id": d, "legs": legs}, ensure_ascii=False) + "\n")
                f.write(json.dumps({"id": d + "x", "legs": []}) + "\n")

    def close(self):
        shutil.rmtree(self.root)


class TestPriorCountsNights(unittest.TestCase):

    def setUp(self):
        # Три ночі, у кожній — дві ланки між СУСІДНІМИ клітинками тих самих
        # місць. Сума лічильників сусідніх пар дала б 6, ночей же — 3.
        a, c = (50.0, 40.0), (51.0, 41.0)
        a2, c2 = (50.5, 40.0), (51.0, 41.5)
        self.s = Store({d: [leg(a, c), leg(a2, c2)]
                        for d in ("2026-09-01", "2026-09-02", "2026-09-03")})
        self.a, self.c = a, c

    def tearDown(self):
        self.s.close()

    def test_distinct_nights_not_summed_cell_pairs(self):
        p = L.Prior("2026-09-10", root=self.s.root)
        self.assertEqual(p.nights(self.a, self.c), 3)

    def test_only_nights_strictly_before(self):
        self.assertEqual(L.Prior("2026-09-03", root=self.s.root).nights(self.a, self.c), 2)
        self.assertEqual(L.Prior("2026-09-01", root=self.s.root).nights(self.a, self.c), 0)

    def test_changed_file_is_reread(self):
        """Памʼять процесу не має пережити зміну сховища (відбиток ночей
        рахує її в тому ж процесі, що й збірка)."""
        self.assertEqual(L.Prior("2026-09-10", root=self.s.root).nights(self.a, self.c), 3)
        (self.s.root / "events" / "2026-09-02.jsonl").write_text('{"legs": []}\n')
        self.assertEqual(L.Prior("2026-09-10", root=self.s.root).nights(self.a, self.c), 2)

    def test_area_ends_and_duplicates_are_not_memory(self):
        ev = self.s.root / "events" / "2026-09-04.jsonl"
        g = leg(self.a, self.c)
        area = list(g)
        area[3] = True
        ev.write_text(json.dumps({"legs": [area]}) + "\n" +
                      json.dumps({"legs": [g], "dup_of": "x"}) + "\n" +
                      json.dumps({"legs": [g], "noise": True}) + "\n")
        self.assertEqual(L.Prior("2026-09-10", root=self.s.root).nights(self.a, self.c), 3)


def route(a, ta, c, tc):
    return {"pts": [{"la": a[0], "lo": a[1], "hhmm": ta}, {"la": c[0], "lo": c[1], "hhmm": tc}]}


class FixedPrior:
    def __init__(self, n):
        self.n = n

    def nights(self, a, c):
        return self.n


class TestLinkCorridors(unittest.TestCase):
    # кінець першого маршруту -> початок другого: ~111 км на північ
    END, START = (50.0, 40.0), (51.0, 40.0)

    def pair(self, t_end, t_start, start=None):
        return [route((49.5, 40.0), "22:00", self.END, t_end),
                route(start or self.START, t_start, (51.5, 40.0), "03:00")]

    def test_plausible_gap_is_linked_with_its_night_count(self):
        # 111 км за 40 хв — 167 км/год
        self.assertEqual(L.link_corridors(self.pair("23:00", "23:40"), FixedPrior(7)),
                         [(0, 1, 7)])

    def test_rare_corridor_is_not_linked(self):
        self.assertEqual(L.link_corridors(self.pair("23:00", "23:40"),
                                          FixedPrior(L.CORRIDOR_MIN_NIGHTS - 1)), [])

    def test_speed_and_time_limits(self):
        for t in ("23:05",     # 5 хв — раніше за DT_MIN
                  "23:15",     # 111 км за 15 хв — 444 км/год
                  "02:30"):    # 3.5 год — понад DT_MAX
            with self.subTest(t=t):
                self.assertEqual(L.link_corridors(self.pair("23:00", t), FixedPrior(9)), [])

    def test_across_midnight(self):
        self.assertEqual(L.link_corridors(self.pair("23:50", "00:30"), FixedPrior(9)),
                         [(0, 1, 9)])

    def test_long_bridge_is_not_drawn(self):
        far = (self.END[0] + (L.BRIDGE_MAX_KM + 30) / 111.0, 40.0)
        self.assertEqual(L.link_corridors(self.pair("23:00", "01:00", start=far),
                                          FixedPrior(9)), [])

    def test_one_end_one_start(self):
        rs = self.pair("23:00", "23:40") + [route(self.START, "23:45", (52.0, 40.0), "03:00")]
        links = L.link_corridors(rs, FixedPrior(9))
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0][0], 0)


class TestChains(unittest.TestCase):

    def test_chain_and_singletons(self):
        self.assertEqual(L.chains(4, [(0, 2, 5), (2, 3, 5)]), [[0, 2, 3], [1]])

    def test_cycle_does_not_hang_or_lose_routes(self):
        out = L.chains(3, [(0, 1, 5), (1, 0, 5)])
        self.assertEqual(sorted(i for ch in out for i in ch), [0, 1, 2])



class TestCompatible(unittest.TestCase):

    def test_type_rules(self):
        c = L.compatible
        self.assertTrue(c({"k": "БПЛА", "u": "БпЛА"}, {"k": "БПЛА", "u": "Дартс"}))
        self.assertTrue(c({"k": "БПЛА", "u": None}, {"k": "БПЛА", "u": "Хорнет"}))
        self.assertTrue(c({"k": "БПЛА", "u": "Хорнет"}, {"k": "БПЛА", "u": "Хорнет"}))
        self.assertFalse(c({"k": "БПЛА", "u": "Хорнет"}, {"k": "БПЛА", "u": "Дартс"}))
        self.assertFalse(c({"k": "ракета", "u": "ракета"}, {"k": "БПЛА", "u": "БпЛА"}))

    def test_incompatible_types_are_not_bridged(self):
        rs = TestLinkCorridors().pair("23:00", "23:40")
        rs[0].update(k="ракета", u="Фламінго")
        rs[1].update(k="БПЛА", u="БпЛА")
        self.assertEqual(L.link_corridors(rs, FixedPrior(9)), [])


if __name__ == "__main__":
    unittest.main()
