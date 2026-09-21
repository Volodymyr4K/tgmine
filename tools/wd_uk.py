"""Українські назви з Wikidata для записів GeoNames — джерело підписів редактора.

Навіщо. Підписи місць у ночі редактора будувались транслітерацією
англійської назви GeoNames, і латиниця втрачає те, чого з неї не відновити:
«Velyki Kopani» давало «Велики Копани», «Zymohiria» — «Зимогіриа», «Ozyory
Urban Okrug» — «Озйори міський округ». В українському розділі Вікіпедії
для цих місць є назви, які писали люди: «Великі Копані», «Зимогірʼя»,
«Озьорський міський округ». Заміряно 21 вересня 2026 на 30 добах: така
назва є для 78% точкових подій.

Зʼєднання — за точним ключем P1566 («GeoNames ID»), як у `wd_names.py`.
Беремо лише основний підпис `uk`, без уточнення в дужках
(«Ульяновський район (Ульяновська область)» -> «Ульяновський район»).

Які записи. Усі 210 тис. записів, до яких може дійти геокодер, Wikidata не
віддає за розумний час: запит за переліком ID ішов би понад 4 год, просторовий
(`wikibase:box`) упирається в ліміт часу запитів (429). Тому — ті, що справді
трапляються або трапляться: (1) місця подій сховища, (2) адмінодиниці й
населені пункти з відомим населенням (серед них усі базові підписи
`labels.py`). Разом ~25 тис., ≈15 хв. Нове село, якого тут нема, отримає
назву запасними правилами `mapper/uknames.py`; перезапуск інструмента
його підхопить.

Для записів України беруться ще й псевдоніми (`skos:altLabel`): з них видно,
чи знає Wikidata про перейменування. «Микільське» має псевдонім «Нікольське»
(Wikidata новіша за GeoNames), «Красногвардійський район» псевдоніма
«Курманський» не має (Wikidata старша) — див. `mapper/uknames._wd_ok`.

Запуск: python3 tools/wd_uk.py            (усе, ≈15 хв)
        python3 tools/wd_uk.py --aliases  (лише псевдоніми до наявного файла)
Формат: geonameid \t назва1|назва2 \t псевдонім1|псевдонім2 (лише Україна).
"""
import csv
import glob
import io
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

sys.path.insert(0, ".")
from tgmine import geocode as GC  # noqa: E402

SRC = ("gazetteer/RU.txt", "gazetteer/UA.txt")
OUT = "refdata/wikidata_uk.tsv"
URL = "https://query.wikidata.org/sparql"
UA = "tgmine-geocoder/1.0 (offline gazetteer supplement)"


def wanted_ids():
    """ID записів: місця подій сховища + адмінодиниці й НП із населенням."""
    places = set()
    for f in sorted(glob.glob("store/events/*.jsonl")):
        for line in open(f, encoding="utf-8"):
            e = json.loads(line)
            if e.get("place") and e.get("lat"):
                places.add((e["place"], round(e["lat"], 3), round(e["lon"], 3)))
    names = {p[0] for p in places}
    extra = GC._load_extra(GC.EXTRA)
    ids, ua = set(), set()
    for path in SRC:
        with open(path, encoding="utf-8") as f:
            for line in f:
                c = line.rstrip("\n").split("\t")
                if len(c) < 15 or c[GC.FCLASS] not in ("P", "A"):
                    continue
                if c[GC.FCLASS] == "A" and not c[GC.FCODE].startswith("ADM"):
                    continue
                if c[GC.CC] == "UA":
                    ua.add(c[0])
                if c[GC.NAME] in names and (c[GC.NAME], round(float(c[GC.LAT]), 3),
                                            round(float(c[GC.LON]), 3)) in places:
                    ids.add(c[0])
                    continue
                if c[GC.FCLASS] == "P" and not int(c[GC.POP] or 0):
                    continue
                alts = [x for x in c[GC.ALT].split(",") if x]
                if (c[0] in extra
                        or any(GC.CYRILLIC.match(GC.clean_alt(x)) for x in alts)
                        or (c[GC.CC] == "UA" and any(GC._UKR.search(x) for x in alts))):
                    ids.add(c[0])
    return sorted(ids, key=int), ua


def query(ids, prop="rdfs:label"):
    vals = " ".join(f'"{i}"' for i in ids)
    q = ("SELECT ?g ?l WHERE { VALUES ?g { " + vals + " } ?i wdt:P1566 ?g. "
         f"?i {prop} ?l. FILTER(lang(?l) = \"uk\") }}")
    data = urllib.parse.urlencode({"query": q}).encode()
    req = urllib.request.Request(URL, data=data, headers={
        "Accept": "text/csv", "User-Agent": UA,
        "Content-Type": "application/x-www-form-urlencoded"})
    for attempt in range(8):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return list(csv.DictReader(io.StringIO(r.read().decode())))
        except Exception as ex:  # 429/5xx/таймаут — чекати й повторити
            print("  retry", attempt, ex, file=sys.stderr)
            time.sleep(30 * (attempt + 1))
    raise RuntimeError("wikidata не відповідає")


BATCH = 1000


def clean(label: str) -> str:
    n = unicodedata.normalize("NFC", label.strip())
    n = re.sub(r"\s*\(.*?\)\s*", " ", n).split(",")[0].strip()
    # апостроф — один знак на весь проєкт (ʼ), як у CITY_UA
    return re.sub(r"['’`]", "ʼ", n)


def fetch(ids, prop, what):
    out: dict[str, set[str]] = {}
    for k in range(0, len(ids), BATCH):
        for r in query(ids[k:k + BATCH], prop):
            n = clean(r["l"])
            if n:
                out.setdefault(r["g"], set()).add(n)
        print(f"  {what}: {k + BATCH}/{len(ids)}, разом {len(out)}", file=sys.stderr)
        time.sleep(3)
    return out


def main(argv):
    ids, ua = wanted_ids()
    if "--aliases" in argv:
        names = {}
        for line in open(OUT, encoding="utf-8"):
            g, n = line.rstrip("\n").split("\t")[:2]
            names[g] = set(n.split("|"))
    else:
        print(len(ids), "записів", file=sys.stderr)
        names = fetch(ids, "rdfs:label", "назви")
    alias = fetch(sorted((g for g in names if g in ua), key=int), "skos:altLabel", "псевдоніми")
    with open(OUT, "w", encoding="utf-8") as f:
        for g in sorted(names, key=int):
            row = g + "\t" + "|".join(sorted(names[g]))
            if alias.get(g):
                row += "\t" + "|".join(sorted(alias[g]))
            f.write(row + "\n")
    print(len(names), "записів отримали назви ->", OUT, file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
