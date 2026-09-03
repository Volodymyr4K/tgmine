"""Нечіткі дублі дзеркала kupolrussia <-> lpr1_treugolnik."""
import unittest

from tgmine import dedupe as D, store as ST

REG = {"kupolrussia": "Крим", "lpr1_treugolnik": "Крим"}


def post(channel, pid, text, t):
    return {"channel": channel, "id": pid, "text": text,
            "date": f"2026-08-20T{t}+03:00", "entities": []}


def run(posts, region=lambda p: "Крим"):
    posts = sorted(posts, key=lambda p: p["date"])
    n = D.mirror_dups(posts, kind_of=lambda p: ST.kind_of(p["text"]), region_of=region)
    return n, {f"{p['channel']}/{p['id']}": p.get("_dup_of") for p in posts}


class TestMirrorDups(unittest.TestCase):
    """Дзеркало переписує не буквально: викидає рядок загрози.

    Точний збіг тексту ловив 59% постів kupolrussia; ще 1220 пар за 15 діб
    (8.3% усіх «унікальних», ≈81 на добу) лишались непозначеними — і добові
    підсумки по областях були роздуті на ~8%, а один голос рахувався двічі.
    На 20 випадкових злиттях, прочитаних очима, хибних 0.

    Тексти дослівні з `data/`.
    """

    def test_dropped_threat_line_is_a_duplicate(self):
        n, m = run([post("lpr1_treugolnik", 1, 'Форос - Алупка - Ялта и далее на восток тревога по БПЛА', "08:43:41"),
                    post("kupolrussia", 2, 'Форос - Алупка - Ялта и далее на восток', "08:44:00")])
        self.assertEqual(n, 1)
        self.assertEqual(m["kupolrussia/2"], "lpr1_treugolnik/1")
        self.assertIsNone(m["lpr1_treugolnik/1"])

    def test_bare_place_after_alarm(self):
        n, m = run([post("lpr1_treugolnik", 1, 'Севастополь\nТревога по БПЛА', "17:42:32"),
                    post("kupolrussia", 2, 'Севастополь', "17:42:50")])
        self.assertEqual(n, 1)
        self.assertEqual(m["kupolrussia/2"], "lpr1_treugolnik/1")

    def test_informative_post_survives_even_if_later(self):
        """Дублем стає менш інформативний, а не пізніший — інакше відбій зник би."""
        n, m = run([post("kupolrussia", 2, 'Ростовская область', "03:25:50"),
                    post("lpr1_treugolnik", 1, 'Ростовская область отбой опасности по БпЛА', "03:26:03")])
        self.assertEqual(n, 1)
        self.assertEqual(m["kupolrussia/2"], "lpr1_treugolnik/1")
        self.assertIsNone(m["lpr1_treugolnik/1"])

    def test_alarm_and_all_clear_are_two_messages(self):
        """Ті самі назви, різні типи — не зливати: тривога і відбій."""
        n, m = run([post("lpr1_treugolnik", 1, 'Севастополь\nТревога по БПЛА', "17:42:32"),
                    post("kupolrussia", 2, 'Севастополь\nОтбой опасности по БПЛА.\nПереходим в режим повышенного внимания', "17:42:50")])
        self.assertEqual(n, 0)

    def test_outside_the_window_is_not_a_duplicate(self):
        n, _ = run([post("lpr1_treugolnik", 1, 'Форос - Алупка - Ялта и далее на восток тревога по БПЛА', "08:43:41"),
                    post("kupolrussia", 2, 'Форос - Алупка - Ялта и далее на восток', "08:47:00")])
        self.assertEqual(n, 0)

    def test_different_region_is_not_a_duplicate(self):
        n, _ = run([post("lpr1_treugolnik", 1, 'Форос - Алупка - Ялта и далее на восток тревога по БПЛА', "08:43:41"),
                    post("kupolrussia", 2, 'Форос - Алупка - Ялта и далее на восток', "08:44:00")],
                   region=lambda p: "Крим" if p["channel"] == "kupolrussia" else "Краснодарський")
        self.assertEqual(n, 0)

    def test_non_mirror_channel_is_untouched(self):
        """vrv_radar — незалежний голос; однаковий текст там не є дзеркалом."""
        n, _ = run([post("lpr1_treugolnik", 1, 'Форос - Алупка - Ялта и далее на восток тревога по БПЛА', "08:43:41"),
                    post("vrv_radar", 2, 'Форос - Алупка - Ялта и далее на восток', "08:44:00")])
        self.assertEqual(n, 0)

    def test_already_marked_exact_duplicate_is_skipped(self):
        p1 = post("lpr1_treugolnik", 1, 'Форос - Алупка - Ялта и далее на восток тревога по БПЛА', "08:43:41")
        p2 = post("kupolrussia", 2, 'Форос - Алупка - Ялта и далее на восток тревога по БПЛА', "08:43:55"); p2["_dup_of"] = "lpr1_treugolnik/1"
        n, m = run([p1, p2])
        self.assertEqual(n, 0)
        self.assertEqual(m["kupolrussia/2"], "lpr1_treugolnik/1")
