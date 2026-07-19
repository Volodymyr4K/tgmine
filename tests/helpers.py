"""Спільне для тестів: корінь репозиторію й завантаження скриптів верхнього рівня.

`site.py` називається так само, як модуль стандартної бібліотеки, тому
`import site` віддає stdlib, а не наш файл. Вантажимо явно за шляхом.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GAZ = ROOT / "gazetteer"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_script(filename: str):
    """Імпортує скрипт верхнього рівня (site.py, makeraid.py) за шляхом."""
    name = "tgmine_script_" + filename.replace(".py", "")
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def has_gazetteer() -> bool:
    return (GAZ / "RU.txt").exists() and (GAZ / "UA.txt").exists()


#: Газетир — 132 МБ, у .gitignore, CI тягне його окремим кроком. Тести, що його
#: потребують, пропускаються на чистому клоні, а не падають.
needs_gazetteer = unittest.skipUnless(
    has_gazetteer(), "нема gazetteer/RU.txt — див. README, розділ про дані")

#: Сховище подій наповнює sync.py; на чистому клоні його ще нема.
needs_store = unittest.skipUnless(
    (ROOT / "store" / "events").is_dir()
    and any((ROOT / "store" / "events").glob("*.jsonl")),
    "нема store/events/*.jsonl — спершу python3 sync.py --rebuild")
