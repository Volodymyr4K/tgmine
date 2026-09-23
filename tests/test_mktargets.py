"""Цілі пошуку редактора (mapper/mktargets.py).

Помилка, по якій стоїть тест: рамка шару цілей була власною копією числа
(41–60.5° пн., 25–53° сх.) і не пішла за підкладкою, коли ту 9 вересня 2026
розширили до 82° сх. Орський, Уфимський, Салаватський, Пермський НПЗ — 190
цілей ярусу 1-2 — на карті були, а в пошуку ні. Оператор: «ця зона добре
відображається, а все інше через раз».
"""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import ROOT

sys.path.insert(0, str(ROOT / "mapper"))
import mktargets as MT  # noqa: E402


class TestBoxFollowsBasemap(unittest.TestCase):

    def test_box_is_the_basemap_box(self):
        head = (ROOT / "mapper" / "basemap.js").read_text(encoding="utf-8")[:4096]
        box = json.loads(re.search(r'"box":(\[[^\]]+\])', head).group(1))
        self.assertEqual(MT.base_box(), tuple(box))

    def test_ural_refinery_reaches_search(self):
        """Ціль за колишньою рамкою (58.5° сх.) іде в пошук; ярус 3 — ні."""
        objs = [
            {"name": "Орський НПЗ", "lat": 51.2, "lon": 58.5, "cat": "refinery",
             "tier": 1, "hits": 17},
            {"name": "Склад БК (Voronezh)", "lat": 51.6, "lon": 39.2,
             "cat": "ammo_depot", "tier": 1, "hits": 700},
            {"name": "Військовий обʼєкт", "lat": 51.2, "lon": 58.6,
             "cat": "military_base", "tier": 3, "hits": 0},
        ]
        with tempfile.TemporaryDirectory() as d:
            src, out = Path(d) / "targets.json", Path(d) / "targets.js"
            src.write_text(json.dumps({"objects": objs, "colors": {}}), encoding="utf-8")
            MT.main(str(src), str(out))
            js = out.read_text(encoding="utf-8")
        items = json.loads(js[len("window.TARGETS="):-2])["items"]
        self.assertEqual([i["n"] for i in items], ["Склад БК (Voronezh)", "Орський НПЗ"])


class TestUnrankedObjects(unittest.TestCase):
    """Щойно дозбираний обʼєкт (fetch_targets.py --tiles) ще без `tier`:
    `i["tier"]` валив збірку сайту (рецензія 23.09.2026)."""

    def test_tier_copy_matches_rank(self):
        sys.path.insert(0, str(ROOT))
        import rank_targets as RT
        self.assertEqual(MT.TIER, RT.TIER)

    def test_object_without_tier_gets_its_type_tier(self):
        objs = [{"name": "Авіабаза Оленья", "lat": 68.15, "lon": 33.46,
                 "cat": "airfield"},
                {"name": "Військовий обʼєкт", "lat": 68.1, "lon": 33.4,
                 "cat": "military_base"}]
        with tempfile.TemporaryDirectory() as d:
            src, out = Path(d) / "targets.json", Path(d) / "targets.js"
            src.write_text(json.dumps({"objects": objs, "colors": {}}), encoding="utf-8")
            MT.main(str(src), str(out))
            items = json.loads(out.read_text(encoding="utf-8")[len("window.TARGETS="):-2])["items"]
        self.assertEqual([(i["n"], i["t"]) for i in items], [("Авіабаза Оленья", 1)])


if __name__ == "__main__":
    unittest.main()
