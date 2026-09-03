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
    береться ТІЛЬКИ зі своєї області (admin1). Заміряно: 59 векторів за
    15 діб. Тексти дослівні з `data/`.
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

    def test_district_source_is_recovered_within_its_oblast(self):
        v = self._vec("Куськино, Мантуровский район, Курская область - пролёт "
                      "БПЛА на север в сторону Орловской области.\n📡\n"
                      "Локатор России -\n@locatorru", "Курська")
        self.assertIsNotNone(v["src"])
        self.assertIn("Manturov", v["src_name"])

    def test_oblast_source_stays_unresolved_on_purpose(self):
        """Центроїд області як кінець вектора не має споживача.

        Спроба віддавати його зробила два лиха: `routes.py` не впізнавав
        українські ключі як область і пустив 9 центроїдів у маршрути
        редактора (від чого стоїть TestAreaEndpoints), а міста-маркери
        («Казань») давали центроїд замість міста. І в районний фолбек
        область теж не йде — «Брянская район» знаходило міський округ
        Брянська. Тому — None.
        """
        v = self._vec("Следующая многочисленная волна БПЛА от ГГ Брянская "
                      "область с дальнейшим прогнозируемым пролётом через все "
                      "районы в направлении Орловской, Калужской и Смоленской "
                      "области", "Брянська")
        self.assertIsNone(v["src"])
        self.assertNotIn(v.get("src_name"), self.cfg.geo)

    def test_without_the_codes_the_old_behaviour_is_unchanged(self):
        """Фолбек мовчить, якщо йому не дали карти кодів admin1."""
        posts = [{"text": "Куськино, Мантуровский район, Курская область - "
                          "пролёт БПЛА на север в сторону Орловской области.",
                  "date": "2026-08-20T10:00:00+03:00", "url": "u", "channel": "t",
                  "entities": [{"type": "регіон", "value": "Курська"}]}]
        v = V.geocode_vectors(posts, self.gaz, self.cfg.geo)[0]
        self.assertIsNone(v["src"])
