#!/usr/bin/env python3
"""Мутації правил виду поста (v27-v29): кожне обмеження має валити тест.

  python3 tools/ctx/mutate.py        # ~5 хв, по копії репо на мутацію

Прибирає одне обмеження в копії коду й проганяє test_store, test_mknight,
test_dedupe. «ВИЖИЛА» — тест не помітив, що правила нема. Рецензія v27
знайшла 8 виживших із 12; після v28 — 0 із 21.
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
S, M = "tgmine/store.py", "mapper/mknight.py"
MUTATIONS = [
    (S, '        if is_tactical:\n            k = "інше"\n', '', "тактичні не на карту"),
    (S, 'FRONT_REGIONS = {"ТОТ_Донецьк", "ТОТ_Луганськ"}', 'FRONT_REGIONS = set()', "прифронтові ТОТ"),
    (S, 'FRONT_KM_BY_REGION = {"ТОТ_Запоріжжя": 70}', 'FRONT_KM_BY_REGION = {}', "межа Запоріжжя"),
    (S, "    return bool(TACTICAL_MODEL.search(t)) or (", "    return (", "моделі скрізь"),
    (S, "FRONT_KM = 60", "FRONT_KM = 10**6", "межа прифронту"),
    (S, r"\bшарк(?:а|у|ом|и|ов)?\b", r"\bшарк", "Шарк не Шарканський"),
    (S, "DRONE_MAXLEN = 220", "DRONE_MAXLEN = 10**9", "межа довжини"),
    (S, "            and not MOVE_GUARD.search(norm):\n        if DRONE_PREP", ":\n        if DRONE_PREP", "MOVE_GUARD у фолбеку"),
    (S, "and not DRONE_LAUNCHISH.search(norm) \\\n", "\\\n", "охорона пуску"),
    (S, "and not planned and not DRONE_LAUNCHISH", "and not DRONE_LAUNCHISH", "намір"),
    (S, r'|\bбуд(?:ет|ут)\b|ожида\w*|в\s+вашем\s+направлении|в\s+вашу\s+сторону', r'|ожида\w*', "в вашем направлении / будет"),
    (S, r'r"приготов\w*|возможн\w*|', r'r"приготов\w*|', "возможно"),
    (S, "(?-i:[А-ЯЁ])", "[А-ЯЁ]", "велика літера"),
    (S, 'if k != "інше" and weak_geo and', 'if False and', "слабкий геокод фолбеку"),
    (S, '"_bare": k == "інше" and not weak_geo and', '"_bare": k == "інше" and', "слабкий геокод голого"),
    (S, '(len(clean) < 25 or kind_of(clean, fallback=False) == "інше")', '(len(clean) < 25 or k == "інше")', "шум без фолбеку"),
    (S, 'kind_of(strip_promo(p["text"], cfg)[0], fallback=False)', 'kind_of(strip_promo(p["text"], cfg)[0])', "дзеркало без фолбеку"),
    (S, '        if par is not None and par["kind"] not in CTX_KIND:\n            continue\n',
        '        if par is not None and par["kind"] not in CTX_KIND:\n            par = None\n', "батько «інше»"),
    (S, '        if par is not None and not e.get("utype"):\n            e["utype"] = par.get("utype")\n', '', "тип від батька"),
    (S, "if parent and par is None and lookup is not None:", "if False:", "батько зі сховища"),
    (S, ' and m.group(1) == p["channel"] else None', ' else None', "той самий канал"),
    (S, ' or e.get("noise") \\\n                or not _ctx_point(e):', ' or e.get("noise"):', "лише з крапкою"),
    (S, 'CTX_KIND = {"фіксація": "фіксація", "ППО": "фіксація"', 'CTX_KIND = {"фіксація": "фіксація", "ППО": "тривога"', "ППО батька -> фіксація"),
    (S, r'r"\b(?:и|в|по|с|г|', r'r"\b(?:и|в|на|по|с|г|', "«на» не заповнювач"),
    (M, '        if e.get("kind_ctx"):\n            continue\n        t = datetime', '        t = datetime', "хронологія без голих"),
    (M, '        # і відкинуто (розмітка з контекстом: ~40-58% правильних, BACKLOG).\n        if e.get("kind_ctx"):\n            continue',
        '        # і відкинуто (розмітка з контекстом: ~40-58% правильних, BACKLOG).', "свідчення без голих"),
]
TESTS = ["tests/test_store.py", "tests/test_mknight.py", "tests/test_dedupe.py"]
COPY = ("tgmine", "tests", "mapper", "configs", "refdata")
LINK = ("gazetteer", "store", "data", "regions.json", "ukraine_controlled.json",
        "sync.py", "raid.py", "makeraid.py")


def main():
    alive = 0
    for f, a, b, name in MUTATIONS:
        d = tempfile.mkdtemp()
        try:
            for x in COPY:
                shutil.copytree(os.path.join(ROOT, x), os.path.join(d, x), symlinks=True)
            for x in LINK:
                if os.path.exists(os.path.join(ROOT, x)):
                    os.symlink(os.path.join(ROOT, x), os.path.join(d, x))
            src = open(os.path.join(d, f), encoding="utf-8").read()
            if src.count(a) != 1:
                print(f"!! якір ({src.count(a)}): {name}")
                alive += 1
                continue
            open(os.path.join(d, f), "w", encoding="utf-8").write(src.replace(a, b))
            r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", *TESTS],
                               cwd=d, capture_output=True, text=True)
            print(("впало    " if r.returncode else "ВИЖИЛА   ") + name)
            alive += not r.returncode
        finally:
            shutil.rmtree(d)
    print(f"вижило {alive} з {len(MUTATIONS)}")
    return 1 if alive else 0


if __name__ == "__main__":
    sys.exit(main())
