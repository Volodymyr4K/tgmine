"""Сторож мовчання каналів (health.py).

Два боки, і обидва на справжніх даних: на пів року історії він не кричить
(інакше оператор перестане дивитись на червоний блок), а канал, обрізаний
посеред справжньої ночі, ловить за кілька годин.
"""
import unittest
from datetime import datetime, timezone
from pathlib import Path

import health as H
from tests.helpers import ROOT

DATA = ROOT / "data"
SINCE = datetime(2026, 5, 1, tzinfo=timezone.utc).timestamp()
UNTIL = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc).timestamp()


def _history():
    t = {ch: [x for x in H._times(DATA / f"{ch}.jsonl", SINCE) if x <= UNTIL] for ch in H.LIMITS}
    return t


def _ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


@unittest.skipUnless((DATA / "vrv_radar.jsonl").exists(), "нема сирого шару")
class TestOnRealHistory(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.t = _history()

    def test_half_a_year_raises_only_the_known_pause(self):
        """З травня по 24 вересня — рівно одна пауза: vrv_radar 9–10 травня,
        25 год. Нова хибна тривога тут — поріг зсунули не туди."""
        g = [x for x in H.gaps(self.t, UNTIL, SINCE) if x["to"] is not None]
        self.assertEqual([(x["ch"], x["from"][:10]) for x in g], [("vrv_radar", "2026-05-09")])

    def test_collection_never_stopped_that_long(self):
        """Спільна тиша всіх каналів моніторингу в історії коротша за поріг
        «стоїть збір» — інакше він кричав би на звичайних нічних затишшях."""
        m = sorted(x for ch in H.MONITOR for x in self.t[ch])
        worst = max(b - a for a, b in zip(m, m[1:])) / 3600
        self.assertLess(worst, H.ALL_QUIET_H)

    def test_channel_cut_mid_night_is_caught_by_morning(self):
        """vrv_radar обрізано о 21:00 МСК на справжній ночі 21.09 (удар по
        Самарі): тривога мусить стояти до 06:00 МСК, коли малюють карту."""
        cut = _ts("2026-09-21T18:00:00Z")
        now = _ts("2026-09-22T03:00:00Z")
        t = {ch: [x for x in v if x <= now] for ch, v in self.t.items()}
        t["vrv_radar"] = [x for x in t["vrv_radar"] if x < cut]
        live = [x for x in H.gaps(t, now, SINCE) if x["to"] is None]
        self.assertEqual([x["ch"] for x in live], ["vrv_radar"])
        self.assertGreaterEqual(live[0]["others"], H.LIMITS["vrv_radar"][0])


class TestLogic(unittest.TestCase):

    def test_quiet_for_everybody_is_not_a_channel_problem(self):
        """Усі мовчать 5 год — жоден канал окремо не винен (інших нуль)."""
        h = 3600.0
        t = {ch: [0.0, 5 * h] for ch in H.LIMITS}
        self.assertEqual(H.gaps(t, 5 * h, 0.0), [])

    def test_everybody_silent_long_is_a_stopped_collection(self):
        h = 3600.0
        t = {ch: [0.0] for ch in H.LIMITS}
        g = [x for x in H.gaps(t, 7 * h, 0.0) if x["ch"] == "*"]
        self.assertEqual(len(g), 1)
        self.assertIsNone(g[0]["to"])

    def test_silence_while_others_post_is_flagged_and_ongoing(self):
        h = 3600.0
        busy = [i * 30.0 for i in range(int(3 * h / 30))]     # 360 постів за 3 год
        t = {ch: busy for ch in H.MONITOR}
        t["vrv_radar"] = [0.0]
        t["exilenova_plus"] = [0.0]
        g = [x for x in H.gaps(t, 3 * h, 0.0) if x["ch"] == "vrv_radar"]
        self.assertEqual(len(g), 1)
        self.assertIsNone(g[0]["to"])
        # а 3 год мовчання наслідків при тих самих 1080 постах — ще норма
        self.assertFalse([x for x in H.gaps(t, 3 * h, 0.0) if x["ch"] == "exilenova_plus"])

    def test_build_writes_every_channel(self):
        h = H.build(DATA, datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc))
        self.assertEqual(set(h["channels"]), set(H.LIMITS))
        self.assertTrue(h["built"].endswith("Z"))


if __name__ == "__main__":
    unittest.main()
