"""Драйвер злиття сховища.

Тест стоїть по конкретній загрозі: `git checkout --ours` на data/*.jsonl
знищує пости назавжди, бо t.me/s/ віддає обмежену глибину історії. Сьогодні
розбіжність між локальним запуском і прогоном бота була 6 постів.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import ROOT

DRIVER = ROOT / "mergejsonl.py"


def write_jsonl(path: Path, rows):
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def run_driver(ours: Path, theirs: Path, path: str):
    return subprocess.run([sys.executable, str(DRIVER), str(ours), str(theirs), path],
                          capture_output=True, text=True)


class TestRawMerge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_keeps_posts_present_only_on_one_side(self):
        # Саме той випадок, що стався: у бота були пости, яких нема локально.
        ours = self.dir / "a.jsonl"
        theirs = self.dir / "b.jsonl"
        write_jsonl(ours, [{"id": 1, "text": "a"}, {"id": 3, "text": "c"}])
        write_jsonl(theirs, [{"id": 2, "text": "b"}, {"id": 3, "text": "c"}])

        r = run_driver(ours, theirs, "data/chan.jsonl")
        self.assertEqual(r.returncode, 0, r.stderr)

        got = [json.loads(l) for l in ours.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([x["id"] for x in got], [1, 2, 3])

    def test_no_duplicates_and_sorted_by_id(self):
        ours = self.dir / "a.jsonl"
        theirs = self.dir / "b.jsonl"
        write_jsonl(ours, [{"id": 5}, {"id": 1}])
        write_jsonl(theirs, [{"id": 3}, {"id": 1}, {"id": 5}])

        run_driver(ours, theirs, "data/chan.jsonl")
        got = [json.loads(l) for l in ours.read_text(encoding="utf-8").splitlines()]
        ids = [x["id"] for x in got]
        self.assertEqual(ids, [1, 3, 5])
        self.assertEqual(len(ids), len(set(ids)))

    def test_events_keep_time_order(self):
        # Події конвеєр пише за часом, не за id. Інший порядок дав би
        # переставлений файл і величезний беззмістовний diff при кожному злитті.
        ours = self.dir / "a.jsonl"
        theirs = self.dir / "b.jsonl"
        write_jsonl(ours, [{"id": "x", "t": 200}])
        write_jsonl(theirs, [{"id": "y", "t": 100}])

        run_driver(ours, theirs, "store/events/2026-07-19.jsonl")
        got = [json.loads(l) for l in ours.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([x["t"] for x in got], [100, 200])

    def test_unknown_path_refuses_to_guess(self):
        # Мовчазний вибір сторони на незнайомому файлі — рівно та поведінка,
        # проти якої весь драйвер. Хай Git конфліктує як завжди.
        ours = self.dir / "a.jsonl"
        theirs = self.dir / "b.jsonl"
        write_jsonl(ours, [{"id": 1}])
        write_jsonl(theirs, [{"id": 2}])

        r = run_driver(ours, theirs, "somewhere/else.jsonl")
        self.assertNotEqual(r.returncode, 0)


class TestStateMerge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_cursor_is_the_maximum(self):
        # Менший курсор змусив би збирач перечитувати вже зібране.
        ours = self.dir / "a.json"
        theirs = self.dir / "b.json"
        ours.write_text(json.dumps({"version": 10, "channels": {
            "ch": {"last_id": 100, "last_date": "2026-07-19T10:00:00+00:00"}}}))
        theirs.write_text(json.dumps({"version": 10, "channels": {
            "ch": {"last_id": 140, "last_date": "2026-07-19T11:00:00+00:00"},
            "new": {"last_id": 7, "last_date": "2026-07-19T11:00:00+00:00"}}}))

        r = run_driver(ours, theirs, "store/state.json")
        self.assertEqual(r.returncode, 0, r.stderr)

        got = json.loads(ours.read_text(encoding="utf-8"))
        self.assertEqual(got["channels"]["ch"]["last_id"], 140)
        self.assertEqual(got["channels"]["new"]["last_id"], 7)


if __name__ == "__main__":
    unittest.main()
