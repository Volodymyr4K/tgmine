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
        self.assertEqual(u["deg"], 45)
        self.assertEqual(u["place"], "Унеча")
        self.assertEqual(len(u["src"]), 3)

    def test_night_carries_bearings_key(self):
        """Ніч без курсів має порожній список, а не відсутній ключ: редактор
        читає `NIGHT.bearings` і рахує його в списку ночей."""
        import inspect
        src = inspect.getsource(self.mk.main)
        self.assertIn('"bearings": br', src)


if __name__ == "__main__":
    unittest.main()
