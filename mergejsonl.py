#!/usr/bin/env python3
"""Драйвер злиття для сховища. Git викликає його сам на конфліктних файлах.

Навіщо. Локальний запуск і крон у CI пишуть в одні й ті самі файли, тому
розбіжність — не аварія, а норма. Git бачить дописування з обох боків і кидає
конфлікт, а очевидний спосіб його зняти:

    git checkout --ours data/kupolrussia.jsonl

тихо знищує пости. `t.me/s/` віддає обмежену глибину історії: те, що з неї
пішло, не повертається нічим. Втрата мовчазна — файл валідний, конвеєр працює,
подій просто нема. Сьогодні різниця була 6 постів, наступного разу буде більше.

Правильне злиття завжди однакове, тож воно тут, а не в пам'яті того, хто
робить `git pull`.

Встановлення (один раз у кожному клоні, `git clone` це НЕ переносить):

    python3 mergejsonl.py --install

Далі `git pull` просто працює.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# Ключ, за яким рядки вважаються тим самим записом, і поле сортування.
# Сирі пости сортуються за id (як Cache.flush), події — за часом (як
# Store.build). Порядок тримаємо однаковий із тим, що пише конвеєр, інакше
# кожне злиття давало б переставлений файл і величезний беззмістовний diff.
LAYOUTS = {
    "data": ("id", "id"),
    "events": ("id", "t"),
}


def layout_for(path: str):
    p = path.replace("\\", "/")
    if p.startswith("data/") and p.endswith(".jsonl"):
        return LAYOUTS["data"]
    if "store/events/" in p and p.endswith(".jsonl"):
        return LAYOUTS["events"]
    return None


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def merge_jsonl(ours: Path, theirs: Path, key: str, order: str) -> list[dict]:
    """Обʼєднання за ключем. Наша сторона виграє при збігу ключа.

    Збіг означає, що обидві сторони розібрали той самий пост. Для сирих
    постів вони байт у байт однакові. Для подій можуть відрізнятись, якщо
    сторони будувались різними версіями конвеєра — тоді перевага нашій, а
    справжнє вирівнювання дає `sync.py --rebuild`, який усе одно потрібен.
    """
    merged: dict = {}
    for row in read_jsonl(theirs):
        merged[row[key]] = row
    for row in read_jsonl(ours):
        # Виняток із «наша виграє»: сирий пост, відновлений після вади
        # скрапера (22.09.2026, відповідь зберігала текст батька), несе поле
        # `reply_text`, а стара копія — ні. Без винятку щогодинний `pull` у
        # CI (у rebase «наша» — це вже опублікована сторона) мовчки повертав
        # би текст батька.
        prev = merged.get(row[key])
        if prev is not None and "reply_text" in prev and "reply_text" not in row:
            continue
        merged[row[key]] = row
    return sorted(merged.values(), key=lambda r: r[order])


def merge_state(ours: Path, theirs: Path) -> dict:
    """Курсори каналів — максимум із двох сторін.

    Менший курсор змусив би наступний збір перечитувати вже зібране; більший
    за реальний лишив би дірку. Максимум безпечний в обидва боки, бо збирач
    однаково звіряється з кешем.
    """
    a = json.loads(ours.read_text(encoding="utf-8")) if ours.exists() else {}
    b = json.loads(theirs.read_text(encoding="utf-8")) if theirs.exists() else {}
    out = dict(a)
    out["channels"] = dict(a.get("channels", {}))
    for ch, v in b.get("channels", {}).items():
        cur = out["channels"].get(ch)
        if cur is None or v.get("last_id", 0) > cur.get("last_id", 0):
            out["channels"][ch] = v
    out["version"] = max(a.get("version", 0), b.get("version", 0))
    return out


def install() -> int:
    root = Path(__file__).resolve().parent
    driver = f'python3 "{root / "mergejsonl.py"}" %A %B %P'
    for name, cmd in (("tgmine-jsonl", driver), ("tgmine-state", driver)):
        subprocess.run(["git", "config", f"merge.{name}.name",
                        "обʼєднання сховища tgmine"], cwd=root, check=True)
        subprocess.run(["git", "config", f"merge.{name}.driver", cmd],
                       cwd=root, check=True)
    print("драйвер увімкнено:")
    print(f"  {driver}")
    print("\nперевірити: git config --get merge.tgmine-jsonl.driver")
    return 0


def main(argv: list[str]) -> int:
    if "--install" in argv:
        return install()
    if len(argv) < 3:
        print(__doc__)
        return 2

    # Git передає тимчасові файли: %A — наша версія, вона ж місце для
    # результату; %B — чужа; %P — справжній шлях у дереві.
    ours, theirs, path = Path(argv[0]), Path(argv[1]), argv[2]

    if path.replace("\\", "/").endswith("store/state.json"):
        ours.write_text(json.dumps(merge_state(ours, theirs),
                                   ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        return 0

    lay = layout_for(path)
    if lay is None:
        # Не наш формат — хай Git конфліктує як завжди, це чесніше за
        # мовчазний вибір однієї зі сторін.
        return 1

    key, order = lay
    rows = merge_jsonl(ours, theirs, key, order)
    with ours.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
