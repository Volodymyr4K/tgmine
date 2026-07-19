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
from tgmine.territory import Borders, UA_CONTESTED, filter_objects

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
