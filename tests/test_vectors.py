"""Вектори руху: джерело не має губитись там, де його видно словами."""
import unittest

from tests.helpers import GAZ, ROOT, needs_gazetteer
from tgmine import extract as E, geocode as GC, vectors as V

CFG = ROOT / "configs" / "ru-monitor.yaml"


class TestParseArtifacts(unittest.TestCase):
    """Розбір без газетира: що саме потрапляє в кандидати на джерело.

    Заміряно на 15 добах: із 1676 векторів джерело губили 242, і всі 242 —
    саме src. Дві причини суто розбірні: прийменник з великої склеювався з
    назвою («Над Белгородской»), а «Продолжаются»/«Противник» на початку
    речення ставали «назвами». Тексти дослівні з `data/`.
    """

    def test_leading_preposition_is_not_part_of_the_name(self):
        v = V.parse("Над Белгородской областью больше 40 БПЛА направление в "
                    "сторону восточной части Курской области далее на восток "
                    "Орловской области и запад Липецкой области.")
        self.assertTrue(v)
        self.assertNotIn("Над Белгородской", v[0]["src"])
        self.assertIn("Белгородской", v[0]["src"])

    def test_sentence_starters_are_not_places(self):
        v = V.parse("Продолжаются фиксации ударных БПЛА над акваторией "
                    "Азовского моря в сторону Краснодарского края.")
        self.assertTrue(v)
        self.assertNotIn("Продолжаются", v[0]["src"])


@needs_gazetteer
class TestSourceFallbacks(unittest.TestCase):
    """Район і область як джерело — тими самими правилами, що в геокоді.

    «Ливенский» без слова «район» лежить у газетирі як «Ливенский район» і
    береться ТІЛЬКИ зі своєї області (admin1); «от Брянской области» дає
    центроїд області — для dst газетир і так віддає ADM1, для src через
    прикметникову форму — ні. Заміряно: 59 + 11 векторів за 15 діб.
    """

    @classmethod
    def setUpClass(cls):
        cls.cfg = E.Config.load(CFG)
        cls.gaz = GC.Gazetteer.load(GAZ / "RU.txt", GAZ / "UA.txt")
        cls.a1 = cls.gaz.region_codes(cls.cfg.entities["регіон"], cls.cfg.geo)

    def _vec(self, text, region):
        posts = [{"text": text, "date": "2026-08-20T10:00:00+03:00", "url": "u",
                  "channel": "t",
                  "entities": [{"type": "регіон", "value": region}]}]
        vs = V.geocode_vectors(posts, self.gaz, self.cfg.geo, region_a1=self.a1,
                               region_rx=self.cfg.entities["регіон"])
        self.assertTrue(vs, "вектор не розібрано")
        return vs[0]

    def test_oblast_adjective_source_becomes_the_region_centroid(self):
        v = self._vec("Следующая многочисленная волна БПЛА от ГГ Брянская "
                      "область с дальнейшим прогнозируемым пролётом через все "
                      "районы в направлении Орловской, Калужской и Смоленской "
                      "области", "Брянська")
        self.assertIsNotNone(v["src"])
        self.assertEqual(v["src_name"], "Брянська")
        self.assertEqual(tuple(v["src"]), tuple(self.cfg.geo["Брянська"]))

    def test_without_the_maps_the_old_behaviour_is_unchanged(self):
        """Фолбеки мовчать, якщо їм не дали карт кодів і патернів."""
        posts = [{"text": "Следующая многочисленная волна БПЛА от ГГ Брянская "
                          "область в направлении Орловской области",
                  "date": "2026-08-20T10:00:00+03:00", "url": "u", "channel": "t",
                  "entities": [{"type": "регіон", "value": "Брянська"}]}]
        v = V.geocode_vectors(posts, self.gaz, self.cfg.geo)[0]
        self.assertIsNone(v["src"])
