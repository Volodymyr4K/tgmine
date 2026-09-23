#!/usr/bin/env python3
"""Мутації правил виду поста (v27-v29): кожне обмеження має валити тест.

  python3 tools/ctx/mutate.py        # ~5 хв, по копії репо на мутацію

Прибирає одне обмеження в копії коду й проганяє test_store, test_mknight,
test_dedupe. «ВИЖИЛА» — тест не помітив, що правила нема. Рецензія v27
знайшла 8 виживших із 12; рецензія v29 — що стенд без `site.py` мовчки
нічого не перевіряв.
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
S, M = "tgmine/store.py", "mapper/mknight.py"
MUTATIONS = [
    # тактика
    (S, '        if is_tactical:\n            k = "інше"\n', '', "тактичні не на карту"),
    (S, 'FRONT_KM_BY_REGION = {"ТОТ_Донецьк": 90, "ТОТ_Запоріжжя": 70}', 'FRONT_KM_BY_REGION = {"ТОТ_Запоріжжя": 70}', "поріг Донеччини"),
    (S, 'FRONT_KM_BY_REGION = {"ТОТ_Донецьк": 90, "ТОТ_Запоріжжя": 70}', 'FRONT_KM_BY_REGION = {"ТОТ_Донецьк": 90}', "поріг Запоріжжя"),
    (S, 'FRONT_KM_BY_REGION = {"ТОТ_Донецьк": 90, "ТОТ_Запоріжжя": 70}', 'FRONT_KM_BY_REGION = {"ТОТ_Донецьк": 120, "ТОТ_Запоріжжя": 70}', "Донеччина 90->120"),
    (S, 'FRONT_KM_BY_REGION = {"ТОТ_Донецьк": 90, "ТОТ_Запоріжжя": 70}', 'FRONT_KM_BY_REGION = {"ТОТ_Донецьк": 90, "ТОТ_Запоріжжя": 85}', "Запоріжжя 70->85"),
    (S, "    if not TACTICAL.search(t) or len(t) > DRONE_MAXLEN:", "    if not TACTICAL.search(t):", "зведення не тактика"),
    (S, "FRONT_KM = 60", "FRONT_KM = 30", "межа 60->30"),
    (S, "FRONT_KM = 60", "FRONT_KM = 75", "межа 60->75"),
    (S, "        reg = point_region(lat, lon) or region\n", "        reg = region\n", "область за крапкою"),
    (S, "    for lat, lon in places:\n", "    for lat, lon in places[:1]:\n", "кілька місць"),
    (S, "    if not sure:\n        return region in BORDER_AREAS or bool(BORDER_WORDS.search(t))\n", "", "без надійної крапки"),
    (S, 'BORDER_AREAS = {"Бєлгородська", "Брянська", "Курська", "ТОТ_Донецьк"}', 'BORDER_AREAS = {"Бєлгородська", "Брянська", "Курська", "ТОТ_Донецьк", "ТОТ_Херсон"}', "Херсонщина не прикордоння"),
    (S, "        return region in BORDER_AREAS or bool(BORDER_WORDS.search(t))", "        return region in BORDER_AREAS", "слова прикордоння"),
    (S, '"centroid", "region-snap", "global")\n        is_tactical', '"centroid", "region-snap")\n        is_tactical', "global — не надійна"),
    (S, ' if sure else []),\n            sure=sure)', ' if False else []),\n            sure=sure)', "інші місця поста"),
    (S, r"\bшарк(?:а|у|ом|и|ов)?\b|\bshark", r"\bшарк|\bshark", "Шарк не Шарканський"),
    (S, r'r"\bфпв|\bfpv|', r'r"\bфпв\b|\bfpv\b|', "fpv без кінця слова"),
    (S, r"|дартс|чаклун|\bмайя\b|мавик|mavic|разведчик|разведыват", r"|дартс|разведчик|разведыват", "чаклун/майя/мавик"),
    (S, "    if TACTICAL.search(text.translate(YO)):\n        return \"інше\"\n    return kind_of(text, fallback=False)", "    return kind_of(text, fallback=False)", "plain_kind бачить тактику"),
    (S, '(len(clean) < 25 or plain_kind(clean) == "інше")', '(len(clean) < 25 or k == "інше")', "шум без фолбеку"),
    (S, 'kind_of=lambda p: plain_kind(strip_promo(p["text"], cfg)[0]),', 'kind_of=lambda p: kind_of(strip_promo(p["text"], cfg)[0]),', "дзеркало без фолбеку"),
    # фолбек DRONE_*
    (S, "DRONE_MAXLEN = 220", "DRONE_MAXLEN = 10**9", "межа довжини"),
    (S, "            and not MOVE_GUARD.search(norm):\n        if DRONE_PREP", ":\n        if DRONE_PREP", "MOVE_GUARD у фолбеку"),
    (S, "            and not DRONE_LAUNCHISH.search(norm) \\\n", "            \\\n", "охорона пуску"),
    (S, r'|\bбуд(?:ет|ут)\b|ожида\w*|в\s+вашем\s+направлении|в\s+вашу\s+сторону', r'|ожида\w*', "в вашем направлении / будет"),
    (S, r'r"приготов\w*|возможн\w*|', r'r"приготов\w*|', "возможно"),
    (S, "(?-i:[А-ЯЁ])", "[А-ЯЁ]", "велика літера"),
    (S, 'if k != "інше" and weak_geo and', 'if False and', "слабкий геокод фолбеку"),
    (S, '"_bare": k == "інше" and not weak_geo and', '"_bare": k == "інше" and', "слабкий геокод голого"),
    # контекст
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
#: Скрипти кореня теж: без `site.py` тести падали ще ДО мутації, і кожна
#: мутація записувалась як «впало» — стенд мовчки нічого не перевіряв
#: (рецензія v29). Тому спершу прогін без мутації.
LINK = ("gazetteer", "store", "data", "regions.json", "ukraine_controlled.json",
        "targets.json", "raids", "site") + tuple(
    f for f in os.listdir(ROOT) if f.endswith(".py"))


def run(mutation=None):
    """Код повернення тестів у копії репо з однією мутацією (або без)."""
    d = tempfile.mkdtemp()
    try:
        for x in COPY:
            shutil.copytree(os.path.join(ROOT, x), os.path.join(d, x), symlinks=True)
        for x in LINK:
            if os.path.exists(os.path.join(ROOT, x)):
                os.symlink(os.path.join(ROOT, x), os.path.join(d, x))
        if mutation:
            f, a, b = mutation
            src = open(os.path.join(d, f), encoding="utf-8").read()
            if src.count(a) != 1:
                return None
            open(os.path.join(d, f), "w", encoding="utf-8").write(src.replace(a, b))
        return subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", *TESTS],
                              cwd=d, capture_output=True, text=True).returncode
    finally:
        shutil.rmtree(d)


def main():
    if run() != 0:
        print("!! тести падають БЕЗ мутації — стенд нічого не перевірить")
        return 2
    alive = 0
    for f, a, b, name in MUTATIONS:
        rc = run((f, a, b))
        if rc is None:
            print(f"!! якір не знайдено: {name}")
            alive += 1
            continue
        print(("впало    " if rc else "ВИЖИЛА   ") + name)
        alive += not rc
    print(f"вижило {alive} з {len(MUTATIONS)}")
    return 1 if alive else 0


if __name__ == "__main__":
    sys.exit(main())
