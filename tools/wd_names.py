"""Російські назви з Wikidata для записів GeoNames, де їх нема.

Навіщо. Газетир індексує лише кириличні альт-назви (`geocode.CYRILLIC`), а в
GeoNames у театрі дій без жодної російської назви 37 тис. НП Росії, 17 тис.
НП України (половина) і ~2 тис. районів: «Kolpnyansky District», «Vyksunskiy
Rayon». Канали пишуть російською, тож такий запис для геокода не існує.

Зʼєднання — за точним ключем: властивість Wikidata P1566 («GeoNames ID»).
Ні транслітерації, ні зіставлення за відстанню — лише ті елементи, які самі
Wikidata привʼязала до цього geonameid. Беремо лише основний підпис `ru`:
синоніми (altLabel) містять колишні назви — «Сталинский район», «Юдинский
район Татарской АССР», «Дзержинск» для Романова, — і вони перехоплювали б
чужі запити (рецензія 21 вересня 2026).

Запуск: python3 tools/wd_names.py  (≈15 хв, пише refdata/wikidata_ru.tsv).
Формат: geonameid \t назва1|назва2… — `geocode.Gazetteer.load(extra=…)`
додає їх як альт-назви.
"""
import csv
import io
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

sys.path.insert(0, ".")
from tgmine import geocode as GC  # noqa: E402

SRC = ("gazetteer/RU.txt", "gazetteer/UA.txt")
OUT = "refdata/wikidata_ru.tsv"
BATCH = 1500
URL = "https://query.wikidata.org/sparql"
UA = "tgmine-geocoder/1.0 (offline gazetteer supplement)"


def missing_ids():
    ids = []
    for path in SRC:
        with open(path, encoding="utf-8") as f:
            for line in f:
                c = line.rstrip("\n").split("\t")
                if len(c) < 15 or c[GC.FCLASS] not in ("P", "A"):
                    continue
                if c[GC.FCLASS] == "A" and not c[GC.FCODE].startswith("ADM"):
                    continue
                if not any(GC.CYRILLIC.match(GC.clean_alt(x))
                           for x in c[GC.ALT].split(",") if x):
                    ids.append(c[0])
    return ids


def query(ids):
    vals = " ".join(f'"{i}"' for i in ids)
    q = ("SELECT ?g ?l WHERE { VALUES ?g { " + vals + " } ?i wdt:P1566 ?g. "
         "?i rdfs:label ?l. "
         'FILTER(lang(?l) = "ru") }')
    data = urllib.parse.urlencode({"query": q}).encode()
    req = urllib.request.Request(URL, data=data, headers={
        "Accept": "text/csv", "User-Agent": UA,
        "Content-Type": "application/x-www-form-urlencoded"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return list(csv.DictReader(io.StringIO(r.read().decode())))
        except Exception as e:  # 429/5xx — чекати й повторити
            print("  retry", attempt, e, file=sys.stderr)
            time.sleep(20 * (attempt + 1))
    raise RuntimeError("wikidata не відповідає")


def main():
    ids = missing_ids()
    print(len(ids), "записів без російської назви", file=sys.stderr)
    names: dict[str, set[str]] = {}
    for k in range(0, len(ids), BATCH):
        rows = query(ids[k:k + BATCH])
        for r in rows:
            n = unicodedata.normalize("NFC", r["l"].strip())
            # лише назва, без уточнень у дужках і через кому
            n = re.sub(r"\s*\(.*?\)\s*", " ", n).split(",")[0].strip()
            if n:
                names.setdefault(r["g"], set()).add(n)
        print(f"  {k + BATCH}/{len(ids)}: +{len(rows)}, разом {len(names)}",
              file=sys.stderr)
        time.sleep(2)
    with open(OUT, "w", encoding="utf-8") as f:
        for g in sorted(names, key=int):
            f.write(g + "\t" + "|".join(sorted(names[g])) + "\n")
    print(len(names), "записів отримали назви ->", OUT, file=sys.stderr)


if __name__ == "__main__":
    main()
