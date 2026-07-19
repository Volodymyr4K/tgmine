"""Генерація HTML. Тут жила XSS, і PoC доводив, що вона виконується.

Текст постів пишуть у публічних Telegram-каналах, назви обʼєктів — будь-хто в
OpenStreetMap, назви НП — GeoNames. У сторінку потрапляє все це.
"""
import ast
import json
import re
import unittest

from tests.helpers import ROOT, load_script

BREAKOUT = 'Белгород </script><script>window.PWNED=1</script>'
IMG = '<img src=x onerror="window.PWNED=1">'


class TestJsdump(unittest.TestCase):
    """JSON усередині <script>. `json.dumps` НЕ екранує `/`."""

    def setUp(self):
        self.mr = load_script("makeraid.py")

    def test_plain_json_dumps_is_unsafe(self):
        """Контроль: без jsdump тег справді розривається."""
        self.assertIn("</script>", json.dumps({"t": BREAKOUT}, ensure_ascii=False))

    def test_jsdump_closes_the_breakout(self):
        out = self.mr.jsdump({"t": BREAKOUT})
        self.assertNotIn("</script", out)
        self.assertNotIn("<", out)
        self.assertNotIn(">", out)

    def test_jsdump_is_lossless(self):
        for value in [BREAKOUT, IMG, "звичайний текст", "лапки \" й '",
                      "амперсанд & знак", "розрив рядка"]:
            with self.subTest(value=value):
                self.assertEqual(json.loads(self.mr.jsdump({"t": value}))["t"], value)

    def test_js_line_separators_escaped(self):
        """U+2028/2029 легальні в JSON, але в JS це розриви рядка."""
        out = self.mr.jsdump({"t": "a b c"})
        self.assertNotIn(" ", out)
        self.assertNotIn(" ", out)


class TestRender(unittest.TestCase):
    """Одним проходом: підставлені дані не бачить наступна підстановка."""

    def setUp(self):
        self.mr = load_script("makeraid.py")

    def test_data_containing_placeholder_survives(self):
        tpl = "A=__DATA__;B=__TARGETS__;"
        out = self.mr.render(tpl, {"__DATA__": '{"t":"текст __TARGETS__ тут"}',
                                   "__TARGETS__": "[1,2]"})
        self.assertEqual(out, 'A={"t":"текст __TARGETS__ тут"};B=[1,2];')

    def test_sequential_replace_would_corrupt(self):
        """Контроль: як саме ламався послідовний .replace()."""
        tpl = "A=__DATA__;B=__TARGETS__;"
        bad = tpl.replace("__DATA__", '{"t":"текст __TARGETS__ тут"}') \
                 .replace("__TARGETS__", "[1,2]")
        self.assertIn('"текст [1,2] тут"', bad)


class TestEscapingInGeneratedJs(unittest.TestCase):
    """Кожна вставка в innerHTML має проходити через esc()."""

    #: Обʼєкти, поля яких приходять ззовні: подія (e), трек (tr), «поблизу» (nr),
    #: ціль (o/to), місце (pl). Внутрішні локальні змінні (cls, st, індекс i)
    #: рахуються в самому JS і екранування не потребують.
    DATA = re.compile(r"\b(?:e|tr|nr|o|to|pl)\.")

    def _unescaped_data_fields(self, block: str) -> list[str]:
        out = []
        for expr in re.findall(r"\$\{([^}]*)\}", block):
            if self.DATA.search(expr) and "esc(" not in expr:
                out.append(expr)
        return out

    def test_makeraid_feed_and_tracks_escape(self):
        tpl = load_script("makeraid.py").TPL
        for anchor in ("document.getElementById('feed').innerHTML",
                       "document.getElementById('tracks').innerHTML"):
            i = tpl.find(anchor)
            self.assertGreater(i, 0, f"не знайдено {anchor}")
            with self.subTest(anchor=anchor):
                self.assertEqual(self._unescaped_data_fields(tpl[i:i + 600]), [],
                                 "поле даних іде в innerHTML без esc()")

    def test_makeraid_near_line_escapes_osm_name(self):
        """nr.name — сирий тег OSM, його редагує будь-хто."""
        tpl = load_script("makeraid.py").TPL
        i = tpl.find("поблизу:")
        self.assertGreater(i, 0)
        self.assertEqual(self._unescaped_data_fields(tpl[i - 200:i + 300]), [])

    def test_detector_catches_an_unescaped_field(self):
        """Сам детектор має ловити те, заради чого існує."""
        self.assertEqual(self._unescaped_data_fields("`<b>${e.text}</b>`"),
                         ["e.text"])
        self.assertEqual(self._unescaped_data_fields("`<b>${esc(e.text)}</b>`"), [])
        self.assertEqual(self._unescaped_data_fields("`<div class=${cls}>`"), [])

    def test_esc_covers_quotes(self):
        """Частина вставок іде в атрибути href="${...}"."""
        tpl = load_script("makeraid.py").TPL
        m = re.search(r"function esc\(t\)\{return[^\n]*", tpl)
        self.assertIsNotNone(m, "esc() у шаблоні не знайдено")
        for ch in ("&", "<", ">", '"', "'"):
            self.assertIn(ch, m.group(0), f"esc() не покриває {ch!r}")

    def test_live_page_defines_and_uses_esc(self):
        """site.py: решта сторінок рендериться на сервері, live — у браузері."""
        src = (ROOT / "site.py").read_text(encoding="utf-8")
        i = src.find("document.getElementById('feed').innerHTML")
        self.assertGreater(i, 0)
        self.assertIn("function esc(", src, "live-сторінка не має esc()")
        self.assertEqual(self._unescaped_data_fields(src[i:i + 500]), [])


class TestSharedFilesNotEmbedded(unittest.TestCase):
    """Спільні файли тягнуться окремо, а не вшиваються в кожну добу.

    targets.json: вшита копія робила сторінку застиглим знімком — cron
    перебудовує лише останні 10 діб, і архів розʼїжджався.
    regions.json: межі не міняються, тут причина суто у вазі (57 КБ × 30).
    """

    def test_no_placeholders_left(self):
        tpl = load_script("makeraid.py").TPL
        for ph in ("__TARGETS__", "__REGIONS__"):
            self.assertNotIn(ph, tpl)

    def test_template_fetches_both(self):
        tpl = load_script("makeraid.py").TPL
        for name in ("targets.json", "regions.json"):
            self.assertIn(name, tpl, f"шаблон має тягнути {name}")

    def test_site_copies_both_into_output(self):
        src = (ROOT / "site.py").read_text(encoding="utf-8")
        for name in ("targets.json", "regions.json"):
            self.assertIn(name, src)
        self.assertIn("copyfile", src)

    def test_missing_shared_file_does_not_break_the_map(self):
        """Обидва шари необовʼязкові; карта подій не має від них залежати."""
        tpl = load_script("makeraid.py").TPL
        self.assertRegex(tpl, r"let TARGETS\s*=\s*\{")
        self.assertRegex(tpl, r"let POLY\s*=\s*\{")


class TestGeneratedPages(unittest.TestCase):
    """Перевірка вже зібраних сторінок, якщо вони є."""

    @classmethod
    def setUpClass(cls):
        cls.pages = sorted((ROOT / "site" / "raids").glob("*.html")) \
            if (ROOT / "site" / "raids").is_dir() else []

    def test_embedded_json_parses_and_has_no_raw_angle_brackets(self):
        if not self.pages:
            self.skipTest("site/raids порожній — спершу python3 site.py --raids")
        for p in self.pages:
            s = p.read_text(encoding="utf-8")
            for const in ("RAID",):
                m = re.search(rf"^const {const}=(.*);$", s, re.M)
                with self.subTest(page=p.name, const=const):
                    self.assertIsNotNone(m)
                    json.loads(m.group(1))
                    self.assertNotIn("<", m.group(1))
                    self.assertNotIn(">", m.group(1))


if __name__ == "__main__":
    unittest.main()
