"""Відбиток ночі: чи треба перебудувати карту нальоту й ніч для редактора.

Навіщо. Карти старих ночей переїжджають між прогонами CI кешем і не
перебудовуються, доки їхній файл є. Досі свіжість гарантувала ручна
дія — підняти `raids-vN` в `update.yml` після кожної перебудови сховища чи
правки малювання. Одного разу це пропустили, і архів на сайті місяцями
показував дані до перебудови; 21 вересня 2026 версію підіймали тричі за день.

Тепер кожна ніч несе відбиток усього, від чого залежить: файлів сховища,
які читає її вікно, коду, що її будує, і даних, які цей код відкриває. Ніч
перебудовується, коли відбиток змінився, — і лише тоді. Ручного кроку нема,
забути нічого не можна.

Пастка, заради якої тут так багато слів: ПРОПУЩЕНИЙ вхід — це та сама тиха
застаріла карта, лише схована в хеші. Тому код береться цілими модулями, а не
«тим, що начебто впливає», і `tests/test_nightprint.py` сам обходить імпорти
скриптів ночі й падає, якщо якийсь локальний модуль не входить у відбиток.
Зайвий вхід коштує зайвої перебудови; пропущений — неправди на сайті.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, timedelta
from pathlib import Path

#: Як `site.py` будує ніч — рівно ці команди, argv збирається звідси. Входить
#: у відбиток явно: `site.py` сам у відбитку нема (кожна його правка
#: перебудовувала б архів), і без цієї константи зміна аргументів (скажімо,
#: годин вікна для `raid.py`) змінила б карти, не змінивши відбитка.
NIGHT_ARGV = (("raid.py", "{d}"),
              ("makeraid.py", "raid_{d}.json"),
              ("mapper/mknight.py", "raid_{d}.json", "{night}"))

#: Код, що будує ніч: скрипти з NIGHT_ARGV і все, що вони імпортують.
#: `tgmine/*.py` — цілим пакетом, а не точним переліком імпортів: `makeraid.py`
#: уже тягне `tgmine.territory` через `__import__`, а такого імпорту не бачить
#: ні `modulefinder`, ні тест. Ціна — зайва перебудова після правки
#: `scrape.py`/`cli.py`/`analyze.py` (ночі їх не імпортують), вона рідкісна.
#: Сам `nightprint.py` не входить: правка логіки відбитка карт не змінює.
CODE = ("raid.py", "makeraid.py", "mapper/mknight.py", "mapper/labels.py",
        "mapper/uknames.py", "mapper/mkreglabels.py", "tgmine/*.py")

#: Дані, які цей код відкриває. `raid.py` сам геокодує вектори руху, тож
#: газетир, `refdata` і конфіг змінюють карту навіть без зміни сховища;
#: `ukraine_controlled.json` вшивається в сторінку пунктиром лінії контролю;
#: `regions.json` читає `mknight` для стартів тривог; `refdata/wikidata_uk.tsv`
#: — українські назви місць (`mapper/uknames.py`).
DATA = ("configs/ru-monitor.yaml", "regions.json", "ukraine_controlled.json",
        "refdata/*", "gazetteer/RU.txt", "gazetteer/UA.txt")

#: Файл сховища — календарна дата події за МСК (перевірено: 14 809 подій,
#: 0 розбіжностей), а вікно ночі d — 12:00 d -> 12:00 d+1. Тож впливають
#: рівно файли d і d+1. `Store.window` відкриває ще й d+2, але його події
#: відсікає фільтр за часом; узяти його у відбиток означало б щогодини
#: перебудовувати позавчорашню ніч, бо свіжа доба оновлюється щогодини.
WINDOW = (0, 1)


def _file_hash(p: Path) -> str:
    if not p.exists():
        return "absent"
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def inputs(root: Path) -> list[Path]:
    """Усі файли коду й даних, від яких залежить будь-яка ніч."""
    out = []
    for pat in CODE + DATA:
        hits = [p for p in sorted(root.glob(pat)) if p.name != "nightprint.py"]
        out += hits if hits else [root / pat]      # відсутній теж впливає
    return out


def code_print(root: Path) -> str:
    """Спільна частина відбитка — рахується раз на прогін."""
    h = hashlib.sha256(repr(NIGHT_ARGV).encode())
    for p in inputs(root):
        h.update(f"{p.relative_to(root)}\0{_file_hash(p)}\n".encode())
    return h.hexdigest()


def prior_print(root: Path, day: str) -> str:
    """Відбиток памʼяті коридорів ночі `day` (`linker.Prior`): пари клітинок
    усіх днів СУВОРО до неї.

    Містки ночі залежать не лише від її вікна, а від усієї історії до неї.
    Без цього відбиток лишав би ніч старою, коли змінився давніший день, і
    повна перебудова давала б інше, ніж накопичений кеш. Береться саме набір
    пар, а не байти файлів: пізній пост без нової ланки ночей не перебудовує."""
    from . import linker
    days = linker.day_counts(root / "store")
    if _PRIOR.get("days") is not days:
        # Накопичувальний хеш по днях — один прохід на прогін, а не на ніч
        # (158 ночей × 158 днів коштували 1.3 с щогодини).
        acc, h = {}, hashlib.sha256()
        for d, c in sorted(days.items()):
            acc[d] = h.copy().hexdigest()          # усе СУВОРО до d
            h.update(f"{d}\0{sorted(c)!r}\n".encode())
        _PRIOR.clear()
        _PRIOR.update(days=days, acc=acc)
    if day in _PRIOR["acc"]:
        return _PRIOR["acc"][day]
    # Ночі без власного файлу сховища: усе, що раніше за неї.
    h = hashlib.sha256()
    for d, c in sorted(days.items()):
        if d >= day:
            break
        h.update(f"{d}\0{sorted(c)!r}\n".encode())
    return h.hexdigest()


_PRIOR: dict = {}


def night_print(root: Path, day: str, code: str) -> str:
    """Відбиток однієї ночі: код + файли сховища її вікна + памʼять коридорів."""
    d0 = date.fromisoformat(day)
    h = hashlib.sha256(code.encode())
    for k in WINDOW:
        d = (d0 + timedelta(days=k)).isoformat()
        h.update(f"{d}\0{_file_hash(root / 'store' / 'events' / f'{d}.jsonl')}\n".encode())
    h.update(f"prior\0{prior_print(root, day)}\n".encode())
    return h.hexdigest()


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def save(path: Path, prints: dict) -> None:
    """Атомарно: прогін, обірваний посеред запису, не має лишати битий
    маніфест — битий читається як порожній, і перебудовується все."""
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text(json.dumps(prints, sort_keys=True, indent=0), encoding="utf-8")
    os.replace(tmp, path)
