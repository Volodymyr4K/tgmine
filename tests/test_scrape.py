"""Розбір превʼю t.me/s/: відповідь на власний пост."""
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

from tgmine import scrape as S

HTML = (Path(__file__).parent / "data" / "tg_reply.html").read_text(encoding="utf-8")


class TestReply(unittest.TestCase):
    def setUp(self):
        self.p = S._parse(BeautifulSoup(HTML, "html.parser"), "locatorru")[0]

    def test_own_text_not_parent_quote(self):
        # До 22.09.2026 сюди йшла цитата батька: перший блок
        # .tgme_widget_message_text у відповіді — це вона.
        self.assertTrue(self.p["text"].startswith("Предварительно группа БПЛА ушла"))
        self.assertNotIn("Нижегородской", self.p["text"])

    def test_parent_quote_kept_separately(self):
        self.assertIn("Нижегородской области", self.p["reply_text"])
        self.assertEqual(self.p["reply_to"], "https://t.me/locatorru/86704")

    def test_date_is_own(self):
        self.assertEqual(self.p["id"], 86705)
        self.assertTrue(self.p["date"])


if __name__ == "__main__":
    unittest.main()
