"""Атомарний запис. Регресія тут коштує безповоротної втрати data/*.jsonl.

Історія: `path.open("w")` різав файл ще до першого записаного байта, і смерть
процесу посеред циклу лишала обрубок. Виміряно на реальному каналі: убивство на
500-му рядку з 16068 лишало 478 рядків — 97% історії знищено.
"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import ROOT
from tgmine.atomic import atomic_write, write_text

# Пишемо у temp і вбиваємо процес на N-му рядку — саме так, як це робить SIGKILL:
# без finally, без скидання буферів.
CRASH = r"""
import os, sys
sys.path.insert(0, %r)
from tgmine.atomic import atomic_write
p = sys.argv[1]
with atomic_write(p) as f:
    for i in range(100000):
        f.write("line %%d\n" %% i)
        if i == 300:
            os._exit(137)
"""


class TestAtomicWrite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_writes_content(self):
        p = self.dir / "a.txt"
        with atomic_write(p) as f:
            f.write("привіт\n")
        self.assertEqual(p.read_text(encoding="utf-8"), "привіт\n")

    def test_crash_midwrite_keeps_old_file(self):
        p = self.dir / "data.jsonl"
        original = "".join(json.dumps({"id": i}) + "\n" for i in range(2000))
        p.write_text(original, encoding="utf-8")

        script = self.dir / "boom.py"
        script.write_text(CRASH % str(ROOT), encoding="utf-8")
        r = subprocess.run([sys.executable, str(script), str(p)],
                           capture_output=True)
        self.assertEqual(r.returncode, 137, "процес мав померти посеред запису")
        self.assertEqual(p.read_text(encoding="utf-8"), original,
                         "старий файл мусить лишитись недоторканим")

    def test_exception_keeps_old_file_and_cleans_temp(self):
        p = self.dir / "b.txt"
        p.write_text("старе", encoding="utf-8")
        with self.assertRaises(ValueError):
            with atomic_write(p) as f:
                f.write("нове")
                raise ValueError("бум")
        self.assertEqual(p.read_text(encoding="utf-8"), "старе")
        self.assertEqual(list(self.dir.glob(".*.tmp")), [],
                         "тимчасовий файл має прибратись")

    def test_no_temp_left_on_success(self):
        write_text(self.dir / "c.txt", "x")
        self.assertEqual(list(self.dir.glob(".*.tmp")), [])

    def test_keeps_permissions_of_existing_file(self):
        p = self.dir / "d.txt"
        p.write_text("x", encoding="utf-8")
        os.chmod(p, 0o640)
        write_text(p, "y")
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o640,
                         "mkstemp дає 0600; права наявного файлу мають зберегтись")

    def test_new_file_respects_umask(self):
        p = self.dir / "e.txt"
        write_text(p, "x")
        old = os.umask(0)
        os.umask(old)
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o666 & ~old)

    def test_creates_missing_parent(self):
        p = self.dir / "deep" / "f.txt"
        write_text(p, "x")
        self.assertTrue(p.exists())


class TestCallersUseAtomic(unittest.TestCase):
    """Три місця, де запис не можна робити звичайним open("w").

    Перевіряємо AST, а не текст: у самих файлах є коментарі, які згадують
    `open("w")` саме для пояснення, чому так робити не можна.
    """

    WRITERS = ["tgmine/scrape.py", "tgmine/store.py", "rank_targets.py"]

    @staticmethod
    def _truncating_writes(src: str) -> list[int]:
        """Рядки, де відкривають файл на запис: open(x, "w") чи path.open("w")."""
        import ast
        bad = []
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name != "open":
                continue
            args = list(node.args) + [k.value for k in node.keywords
                                      if k.arg == "mode"]
            for a in args:
                if isinstance(a, ast.Constant) and isinstance(a.value, str) \
                        and "w" in a.value:
                    bad.append(node.lineno)
        return bad

    def test_writers_do_not_truncate_in_place(self):
        for rel in self.WRITERS:
            src = (ROOT / rel).read_text(encoding="utf-8")
            with self.subTest(file=rel):
                self.assertRegex(src, r"\b(atomic_write|write_text)\b",
                                 f"{rel}: не використовує атомарний запис")
                self.assertEqual(
                    self._truncating_writes(src), [],
                    f"{rel}: open(..., 'w') ріже файл ще до першого байта — "
                    f"аварія посеред запису лишає обрубок")

    def test_detector_catches_a_bad_write(self):
        """Сам детектор має ловити те, заради чого існує."""
        self.assertEqual(self._truncating_writes('p.open("w")'), [1])
        self.assertEqual(self._truncating_writes('open(p, "w")'), [1])
        self.assertEqual(self._truncating_writes('open(p, mode="w")'), [1])
        self.assertEqual(self._truncating_writes('# p.open("w") у коментарі'), [])
        self.assertEqual(self._truncating_writes('open(p, encoding="utf-8")'), [])


if __name__ == "__main__":
    unittest.main()
