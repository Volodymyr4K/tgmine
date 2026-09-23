"""Відбиток ночі (tgmine/nightprint.py): повнота входів і чутливість.

Пропущений вхід — тиха застаріла карта на сайті, тому головний тест тут не
«хеш рахується», а «у відбиток входить усе, що ніч читає»: імпорти скриптів
ночі обходяться автоматично, шляхи даних беруться з самих модулів.
"""
import modulefinder
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import ROOT
from tgmine import nightprint as NP

SCRIPTS = ("raid.py", "makeraid.py", "mapper/mknight.py")


class TestInputsAreComplete(unittest.TestCase):

    def test_every_local_module_of_night_scripts_is_an_input(self):
        """Новий модуль, імпортований скриптом ночі, мусить потрапити у
        відбиток — інакше його правка не перебудує жодної карти."""
        have = {p.resolve() for p in NP.inputs(ROOT)}
        missing = set()
        for script in SCRIPTS:
            mf = modulefinder.ModuleFinder(path=[str(ROOT), str(ROOT / "mapper")] + sys.path)
            mf.run_script(str(ROOT / script))
            for m in mf.modules.values():
                f = getattr(m, "__file__", None)
                if not f:
                    continue
                p = Path(f).resolve()
                if ROOT in p.parents and "tests" not in p.parts:
                    if p not in have:
                        missing.add(str(p.relative_to(ROOT)))
        self.assertEqual(missing, set(), "модулі поза відбитком")

    def test_data_files_the_modules_open_are_inputs(self):
        """Шляхи — із самих модулів, а не переписані тут вдруге."""
        from tgmine import geocode as GC, territory as T
        have = {p.resolve() for p in NP.inputs(ROOT)}
        for p in (T.UA_CONTROLLED, GC.EXTRA, ROOT / "configs" / "ru-monitor.yaml",
                  ROOT / "regions.json", ROOT / "gazetteer" / "RU.txt",
                  ROOT / "gazetteer" / "UA.txt"):
            with self.subTest(path=str(p)):
                self.assertIn(Path(p).resolve(), have)

    def test_site_builds_nights_only_through_night_argv(self):
        """site.py не в відбитку, тож команди збирання ночі мусять іти з
        NP.NIGHT_ARGV (яка у відбитку). Прямий виклик скрипта ночі в site.py
        означав би, що зміна його аргументів не перебудує карт."""
        src = (ROOT / "site.py").read_text(encoding="utf-8")
        for script in ("raid.py", "makeraid.py", "mapper/mknight.py"):
            with self.subTest(script=script):
                self.assertNotIn(f'"{script}"', src)
        self.assertIn("NP.NIGHT_ARGV", src)

    def test_argv_changes_the_print(self):
        root = ROOT
        base = NP.code_print(root)
        old = NP.NIGHT_ARGV
        try:
            NP.NIGHT_ARGV = (("raid.py", "{d}", "18", "12"),) + old[1:]
            self.assertNotEqual(NP.code_print(root), base)
        finally:
            NP.NIGHT_ARGV = old

    def test_nightprint_itself_is_not_an_input(self):
        self.assertFalse([p for p in NP.inputs(ROOT) if p.name == "nightprint.py"])

    def test_raid_reads_the_config_and_gazetteer_named_in_inputs(self):
        # З 22.09.2026 (конвеєр v26) `raid.py` газетир не читає — ланки руху
        # вже в сховищі; газетир ночі читає `mapper/uknames.py` (підписи).
        src = (ROOT / "raid.py").read_text(encoding="utf-8")
        self.assertIn('"configs/ru-monitor.yaml"', src)
        uk = (ROOT / "mapper" / "uknames.py").read_text(encoding="utf-8")
        self.assertIn('"gazetteer", "RU.txt"', uk)


class TestSensitivity(unittest.TestCase):
    """На копії-мініатюрі репозиторію: що змінює відбиток, а що — ні."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        for pat in NP.CODE + NP.DATA:
            p = self.root / pat.replace("*", "x")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("v1")
        ev = self.root / "store" / "events"
        ev.mkdir(parents=True)
        for d in ("2026-09-09", "2026-09-10", "2026-09-11", "2026-09-12"):
            (ev / f"{d}.jsonl").write_text(d)
        (self.root / "site.py").write_text("v1")

    def tearDown(self):
        shutil.rmtree(self.root)

    def fp(self, day="2026-09-10"):
        return NP.night_print(self.root, day, NP.code_print(self.root))

    def test_window_files_change_the_print(self):
        base = self.fp()
        for d in ("2026-09-10", "2026-09-11"):
            with self.subTest(file=d):
                f = self.root / "store" / "events" / f"{d}.jsonl"
                old = f.read_text()
                f.write_text(old + "!")
                self.assertNotEqual(self.fp(), base)
                f.write_text(old)
                self.assertEqual(self.fp(), base)

    def test_days_outside_the_window_do_not(self):
        """Доба d+2 оновлюється щогодини; якби вона входила, позавчорашня
        ніч перебудовувалась би щопрогону."""
        base = self.fp()
        for d in ("2026-09-09", "2026-09-12"):
            (self.root / "store" / "events" / f"{d}.jsonl").write_text("changed")
        self.assertEqual(self.fp(), base)

    def test_aftermath_of_this_night_changes_the_print(self):
        """Наслідки лежать по ночах (`store/aftermath/<ніч>.jsonl`): пояснення
        заднім числом міняє файл давньої ночі — і саме її треба перебудувати,
        а сусідню ні."""
        af = self.root / "store" / "aftermath"
        af.mkdir(parents=True)
        base = self.fp()
        (af / "2026-09-11.jsonl").write_text('{"id": "x"}\n')
        self.assertEqual(self.fp(), base)
        (af / "2026-09-10.jsonl").write_text('{"id": "x"}\n')
        self.assertNotEqual(self.fp(), base)

    def test_corridor_memory_before_the_night_changes_the_print(self):
        """Містки ночі спираються на ВСЮ історію до неї (`linker.Prior`):
        нова ланка в давнішому дні мусить перебудувати ніч, а зміна того
        дня без ланок — ні."""
        base = self.fp()
        f = self.root / "store" / "events" / "2026-09-09.jsonl"
        f.write_text('{"id": 1, "legs": []}\n')
        self.assertEqual(self.fp(), base)
        f.write_text('{"id": 1, "legs": [["A", 50.0, 40.0, false, "C", 51.0, 41.0, false]]}\n')
        self.assertNotEqual(self.fp(), base)

    def test_every_code_and_data_input_changes_the_print(self):
        base = self.fp()
        for pat in NP.CODE + NP.DATA:
            with self.subTest(input=pat):
                p = self.root / pat.replace("*", "x")
                p.write_text("v2")
                self.assertNotEqual(self.fp(), base)
                p.write_text("v1")

    def test_new_module_in_package_changes_the_print(self):
        base = self.fp()
        (self.root / "tgmine" / "new.py").write_text("x")
        self.assertNotEqual(self.fp(), base)

    def test_site_py_does_not(self):
        """site.py лише викликає скрипти — його правка не перебудовує архів."""
        base = self.fp()
        (self.root / "site.py").write_text("v2")
        self.assertEqual(self.fp(), base)

    def test_manifest_round_trip_and_broken_file(self):
        f = self.root / "fp.json"
        NP.save(f, {"2026-09-10": "abc"})
        self.assertEqual(NP.load(f), {"2026-09-10": "abc"})
        f.write_text("{оборвано")
        self.assertEqual(NP.load(f), {}, "битий маніфест = перебудувати все")


if __name__ == "__main__":
    unittest.main()
