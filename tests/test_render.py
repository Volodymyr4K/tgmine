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
        """o.name — сирий тег OSM, його редагує будь-хто.

        Якір — САМ вираз, не текст поруч. Раніше він шукав рядок «поблизу:»,
        і коли той переїхав у коментар, тест лишився зеленим, стережучи
        коментар. Тому беремо блок між двома опорами коду.
        """
        tpl = load_script("makeraid.py").TPL
        i = tpl.find("const around=")
        j = tpl.find("const rows=", i)
        self.assertGreater(i, 0, "не знайдено обчислення сусідніх обʼєктів")
        self.assertGreater(j, i, "не знайдено кінець блоку")
        self.assertIn("esc(", tpl[i:j], "у блоці взагалі нема екранування")
        self.assertEqual(self._unescaped_data_fields(tpl[i:j]), [])

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


class TestRegionLabels(unittest.TestCase):
    """Назви регіонів на сайті й контури карти мають зшиватись.

    Карта бере контур області за назвою події (`POLY[e.region]`). Коли назви
    для читача підставили в подіях, але лишили внутрішні ключі в regions.json,
    для пʼяти областей POLY[reg] повертав undefined — заливка тривоги тихо
    зникала, і жодної помилки в консолі при цьому не було. Тест саме про це.
    """

    def test_map_regions_all_have_a_contour(self):
        site = ROOT / "site"
        regions = site / "regions.json"
        if not regions.exists():
            self.skipTest("сайт не зібрано")
        with regions.open(encoding="utf-8") as fh:
            poly = set(json.load(fh))
        orphan = set()
        for f in sorted((site / "raids").glob("*.html"))[:20]:
            m = re.search(r'"events":\s*(\[.*?\]),\s*"vectors"',
                          f.read_text(encoding="utf-8"), re.S)
            if not m:
                continue
            for e in json.loads(m.group(1)):
                if e.get("region") and e["region"] not in poly:
                    orphan.add(e["region"])
        self.assertEqual(sorted(orphan), [],
                         "регіон події без контуру — заливка тривоги зникне мовчки")

    def test_internal_keys_do_not_reach_the_reader(self):
        site = ROOT / "site"
        if not (site / "index.html").exists():
            self.skipTest("сайт не зібрано")
        leaked = [p.name for p in list(site.glob("*.html")) + list((site / "day").glob("*.html"))
                  if "ТОТ_" in p.read_text(encoding="utf-8")
                  or "Ивановська" in p.read_text(encoding="utf-8")]
        self.assertEqual(leaked[:5], [], "внутрішній ключ регіону потрапив у HTML")


class TestMapsAreByteStable(unittest.TestCase):
    """Карта завершеної доби не має мінятись від самої перезбірки.

    Тут стояв `datetime.now()` як «збірка HH:MM». Один цей рядок робив кожну
    перезбірку іншим файлом, тож хостинг перезаливав карти щогодини — 800 КБ
    на дві карти за прогін, при незмінному вмісті. За добу це десятки мегабайт
    трафіку ні за що, і саме воно зʼїдало кредити хостингу.

    Тепер підпис — час останньої події доби. Для минулої ночі він сталий, для
    сьогоднішньої змінюється, бо дані справді доходять.
    """

    def test_no_wall_clock_in_the_map_generator(self):
        # Перевіряємо КОД, не текст: у файлі є коментар, що пояснює, чому
        # datetime.now() звідси прибрано, і пошук по сирому рядку ловив би
        # саме його.
        tree = ast.parse((ROOT / "makeraid.py").read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "now"]
        self.assertEqual(calls, [],
                         "вихід карти знову залежить від часу збірки, "
                         "а не лише від даних")

    def test_rebuilding_the_same_day_gives_the_same_bytes(self):
        raid = ROOT / "site" / "raids"
        if not raid.is_dir() or not any(raid.glob("*.html")):
            self.skipTest("карти не зібрано")
        # Непрямо, але без запуску конвеєра: сторінка не повинна містити
        # мітки, яка залежить від часу збірки.
        page = sorted(raid.glob("*.html"))[0].read_text(encoding="utf-8")
        self.assertIn("дані до", page)
        self.assertNotIn("збірка", page)


class TestProseNumbersAreComputed(unittest.TestCase):
    """Числа в поясненнях сайту мають рахуватись на збірці, не бути вшитими.

    У прозі стояло «число пишуть у 3.2% згадок» і «підтверджених другим
    голосом 3.1%». Обидва виміряні один раз у липні 2026 і вшиті літералами.
    Після правки витягу числа перше стало 4.5%, після добору locatorru
    друге — 10.4%; сторінка при цьому далі показувала старі.

    Докстрінги й коментарі не перевіряються — там історичні заміри доречні.
    Перевіряється лише код і рядкові літерали, які йдуть у HTML.
    """

    @staticmethod
    def _doc_lines(tree):
        out = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) \
                    and node.body and isinstance(node.body[0], ast.Expr) \
                    and isinstance(getattr(node.body[0], "value", None), ast.Constant) \
                    and isinstance(node.body[0].value.value, str):
                d = node.body[0]
                out.update(range(d.lineno, d.end_lineno + 1))
        return out

    def test_no_literal_percent_in_page_prose(self):
        src = (ROOT / "site.py").read_text(encoding="utf-8")
        skip = self._doc_lines(ast.parse(src))
        bad = [f"{n}: {ln.strip()[:70]}" for n, ln in enumerate(src.splitlines(), 1)
               if n not in skip
               and not ln.strip().startswith("#")
               and re.search(r"\d+[.,]\d+ ?%", ln)
               and re.search(r"[а-яіїє]", ln)
               and "{" not in ln]
        self.assertEqual(bad, [], f"вшиті відсотки в прозі: {bad}")

    def test_the_two_known_literals_are_gone(self):
        src = (ROOT / "site.py").read_text(encoding="utf-8")
        self.assertNotIn("3.2% згадок", src)
        self.assertNotIn("<b>3.1%</b>", src)


class TestProseNumbersActuallyCompute(unittest.TestCase):
    """Сторож вище дивиться на текст; цей — виконує функції.

    Перша версія count_share/confirmed_share пройшла 161 тест і впала на
    першій же збірці: у site.py не було `import re`. Жоден тест ці функції
    не викликав. Тепер викликає — на реальному сховищі, з межами, у які
    справжні числа вкладаються з запасом.
    """

    def setUp(self):
        if not any((ROOT / "store" / "events").glob("*.jsonl")):
            self.skipTest("нема store/events — спершу sync.py")

    def test_shares_are_sane_fractions(self):
        site = load_script("site.py")
        from tgmine import store as ST
        st = ST.Store(root=ROOT / "store")
        c = site.count_share(st)
        v = site.confirmed_share(st)
        # число пишуть рідко, але не ніколи: у липні 3.2%, у вересні 4.5%
        self.assertGreater(c, 0.005)
        self.assertLess(c, 0.30)
        # другий голос є, але його мало: 3.1% -> 10.4% після locatorru
        self.assertGreater(v, 0.005)
        self.assertLess(v, 0.50)
