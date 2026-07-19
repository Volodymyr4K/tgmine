"""Запис файлу, який неможливо обірвати на півдорозі.

Було: `path.open("w")` — відкриття РІЗАЛО файл одразу, а вміст писався
поступово. Аварія посеред запису (OOM-kill, скасування runner-а в Actions,
переповнений диск, Ctrl-C) лишала обрубок.

Виміряно на реальному `data/lpr1_treugolnik.jsonl`: смерть процесу на 500-му
рядку з 16068 лишала 478 рядків — **97% історії каналу знищено**. За CLAUDE.md
`data/` — єдине, що не відновлюється: `t.me/s/` віддає обмежену глибину
історії, тому це не «перезберемо», а «втратили назавжди».

Рішення стандартне: пишемо у тимчасовий файл поряд, скидаємо на диск, і аж тоді
`os.replace()` — на POSIX і Windows це атомарна операція. Спостерігач бачить або
старий файл цілком, або новий цілком. Проміжного стану не існує.

Тимчасовий файл створюється в тій самій теці навмисно: `os.replace` атомарний
лише в межах однієї файлової системи, а `/tmp` цілком може бути іншою.
"""
from __future__ import annotations

import contextlib
import os
import stat
import tempfile
from pathlib import Path

# Читаємо umask один раз при імпорті: os.umask() вміє лише «встановити й
# повернути попереднє», тобто запитати його без побічного ефекту не можна,
# а робити це на кожен запис — гонка.
_UMASK = os.umask(0)
os.umask(_UMASK)
_DEFAULT_MODE = 0o666 & ~_UMASK


@contextlib.contextmanager
def atomic_write(path, encoding: str = "utf-8"):
    """Контекст-менеджер: дає файловий обʼєкт, підміняє `path` лише на виході.

        with atomic_write(p) as f:
            for line in lines:
                f.write(line)

    Якщо всередині блоку виникне виняток — цільовий файл лишиться недоторканим,
    а тимчасовий приберемо.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmpname = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmpname)
    try:
        # mkstemp завжди дає 0600. Без цього кроку атомарний запис тихо міняв би
        # права наявного файлу (0644 -> 0600) на кожному оновленні — заміна ж
        # приносить із собою і права тимчасового файлу.
        try:
            os.chmod(tmp, stat.S_IMODE(os.stat(path).st_mode))
        except FileNotFoundError:
            os.chmod(tmp, _DEFAULT_MODE)
        with os.fdopen(fd, "w", encoding=encoding) as f:
            yield f
            # fsync до replace: інакше після втрати живлення можна дістати
            # порожній новий файл замість цілого старого.
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp is not None:
            with contextlib.suppress(OSError):
                tmp.unlink()


def write_text(path, text: str, encoding: str = "utf-8") -> None:
    """Те саме для одного готового рядка — заміна `path.write_text()`."""
    with atomic_write(path, encoding=encoding) as f:
        f.write(text)
