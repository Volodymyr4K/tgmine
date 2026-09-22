#!/usr/bin/env python3
"""Українські назви місць для підписів редактора — з людського джерела.

ЩО БУЛО. Підпис місця в ночі редактора (фіксації, збиття, курси) і базові
підписи міст будувались транслітерацією АНГЛІЙСЬКОЇ назви GeoNames
(`labels.uk`). Латиниця губить те, чого з неї не відновити: мʼякий знак,
«ё», «й», межу «і/и», апостроф. Заміряно 21 вересня 2026 на вибірці 60
місць з останніх ночей: «Самольотна Ветелка», «Стариє Богади», «Степнои
Заи», «Тимашйовськ», «Озйори міський округ», «Велики Копани», «Зимогіриа»
— приблизно третина підписів з помилкою, видимою кожному читачеві.

ЩО ТЕПЕР. Назва береться з першого джерела, яке її має:

1. ручний словник `labels.CITY_UA` і таблиці `labels` (області, винятки);
2. аліаси конфігу (`ALIAS_UK`): миси, бухти й аеродроми Криму, які канали
   пишуть у будь-якому відмінку («Фиолента», «Бухты Казачья»);
3. Wikidata: основний підпис `uk` елемента з тим самим GeoNames ID (P1566),
   `refdata/wikidata_uk.tsv` (`tools/wd_uk.py`). Для 78% точкових подій
   останніх 30 діб він є. Приймається лише коли це назва ТОГО Ж, що пишуть
   канали (`_wd_ok`): P1566 буває на сусідньому елементі («Музей-садиба
   Архангельське», «Харківська міська рада» для району). Перейменування в
   Україні — чинна офіційна назва: хто новіший, Wikidata чи GeoNames,
   вирішують псевдоніми Wikidata («Микільське», «Катирлез» — з Wikidata;
   «Курманський район» — з GeoNames, бо Wikidata його ще не знає);
4. для України — українська альт-назва GeoNames, звірена з латиницею
   (`pick_uk`): на записах, де є й Wikidata, збіг 157 із 161;
5. російська назва (альт-назва GeoNames чи `wikidata_ru.tsv`, вибрана за
   збігом із латиницею; «ё» відновлюється з латиниці), передана правилами
   відтворення російських назв українською (`ru2uk`). На 1608 парах з
   Wikidata: точних збігів 68% проти 63% у старого правила з латиниці,
   середня відстань до правильної назви на 18% менша; для України — 73%
   проти 62%. Правила звірено з Вікіпедією, яка сама непослідовна
   («Суровикіно», але «Жирятино»), тож стеля тут невисока — це запас,
   а не основне джерело;
6. стара транслітерація латиниці (`labels.uk`) — коли нічого іншого нема.

ЗВʼЯЗОК ІЗ ЗАПИСОМ. Подія несе назву GeoNames і її координату, але не ID.
Пара «назва + координата» відновлює запис однозначно: 5448 із 5448 місць
сховища (157 діб), неоднозначних 0. Газетир читається лише в рядках із
потрібними назвами — це дешево навіть для кожної ночі окремо.
"""
import difflib
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
from tgmine import geocode as GC  # noqa: E402
from labels import CITY_UA, EXC, UA_OBLAST, uk as uk_latin  # noqa: E402

GAZ = (os.path.join(ROOT, "gazetteer", "RU.txt"), os.path.join(ROOT, "gazetteer", "UA.txt"))
WD_UK = os.path.join(ROOT, "refdata", "wikidata_uk.tsv")

# Аліаси конфігу (`geo_aliases`) приходять у місце події так, як їх написав
# канал, зокрема в непрямому відмінку. Підпис — українською й у називному.
ALIAS_UK = {
    "Бельбек": "Бельбек", "Бельбека": "Бельбек", "Бельбеке": "Бельбек",
    "Фиолент": "мис Фіолент", "Фиолента": "мис Фіолент", "Фиоленте": "мис Фіолент",
    "Донузлав": "Донузлав", "Донузлава": "Донузлав", "Донузлаве": "Донузлав",
    "Чауда": "мис Чауда", "Чауды": "мис Чауда", "Чауде": "мис Чауда",
    "Опук": "мис Опук", "Опука": "мис Опук",
    "Мойнаки": "озеро Мойнаки",
    "Мекензиевы Горы": "Мекензієві Гори", "Мекензиевы": "Мекензієві Гори",
    "Мекензиевых": "Мекензієві Гори",
    "Мыс Херсонес": "мис Херсонес", "Мыса Херсонес": "мис Херсонес",
    "Херсонес": "Херсонес", "Херсонеса": "Херсонес", "Херсонес Таврический": "Херсонес",
    "Бухта Казачья": "Козача бухта", "Бухты Казачья": "Козача бухта",
    "Бухте Казачья": "Козача бухта", "Казачья": "Козача бухта", "Казачьей": "Козача бухта",
    "Бухта Камышовая": "Камишова бухта", "Бухты Камышовая": "Камишова бухта",
    "Камышовая": "Камишова бухта", "Камышовой": "Камишова бухта",
    "Бухта Стрелецкая": "Стрілецька бухта", "Бухты Стрелецкая": "Стрілецька бухта",
    "Голландия": "Голландія", "Голландии": "Голландія",
    "Хорлы": "Хорли",
    "Беглица": "Беглиця", "Беглицы": "Беглиця", "Беглицей": "Беглиця",
    "Балтимор": "аеродром Балтимор", "Балтимора": "аеродром Балтимор",
    "Утриш": "Великий Утриш",
    "Озеряновка": "Озерянівка", "Озеряновку": "Озерянівка",
    "Богородск": "Богородськ", "Богородский": "Богородськ",
}

# Субʼєкти РФ — таблицею, у стилі підписів областей редактора
# (`mkreglabels.NAMES`: «Брянська обл.», «Мордовія»). Відтворення давало
# «Вологодська область» поряд з українськими «Харківська обл.», латиниця —
# «Нортг Оссетиа-Аланіа» (заміряно 22 вересня 2026 на сховищі: 29 субʼєктів
# серед місць подій). Назви — усі ADM1 з gazetteer/RU.txt.
RU_ADM1 = {
    "Altayskiy Kray": "Алтайський край", "Amur Oblast": "Амурська обл.",
    "Arkhangelsk Oblast": "Архангельська обл.", "Astrakhan Oblast": "Астраханська обл.",
    "Bashkortostan": "Башкортостан", "Belgorod Oblast": "Бєлгородська обл.",
    "Bryansk Oblast": "Брянська обл.", "Chechenskaya Respublika": "Чечня",
    "Chelyabinsk Oblast": "Челябінська обл.", "Chukotskiy Avtonomnyy Okrug": "Чукотка",
    "Chuvashskaya Respublika": "Чувашія", "Dagestan": "Дагестан",
    "Irkutsk Oblast": "Іркутська обл.", "Ivanovo Oblast": "Івановська обл.",
    "Kabardino-Balkarskaya Respublika": "Кабардино-Балкарія",
    "Kaliningrad Oblast": "Калінінградська обл.", "Kalmykiya": "Калмикія",
    "Kaluga Oblast": "Калузька обл.", "Kamchatka Krai": "Камчатський край",
    "Karachayevo-Cherkesiya": "Карачаєво-Черкесія", "Kemerovo Oblast": "Кемеровська обл.",
    "Khabarovskiy Kray": "Хабаровський край",
    "Khanty-Mansiyskiy Avtonomnyy Okrug-Yugra": "ХМАО — Югра",
    "Kirov Oblast": "Кіровська обл.", "Komi": "Комі", "Kostroma Oblast": "Костромська обл.",
    "Krasnodarskiy Kray": "Краснодарський край", "Krasnoyarskiy Kray": "Красноярський край",
    "Kurgan Oblast": "Курганська обл.", "Kursk Oblast": "Курська обл.",
    "Leningrad Oblast": "Ленінградська обл.", "Lipetsk Oblast": "Липецька обл.",
    "Magadan Oblast": "Магаданська обл.", "Moscow Oblast": "Московська обл.",
    "Moskva": "Москва", "Murmansk Oblast": "Мурманська обл.",
    "Nenetskiy Avtonomnyy Okrug": "Ненецький АО",
    "Nizhny Novgorod Oblast": "Нижньогородська обл.", "North Ossetia-Alania": "Північна Осетія",
    "Novgorod Oblast": "Новгородська обл.", "Novosibirsk Oblast": "Новосибірська обл.",
    "Omsk Oblast": "Омська обл.", "Orenburg Oblast": "Оренбурзька обл.",
    "Oryol Oblast": "Орловська обл.", "Penza Oblast": "Пензенська обл.",
    "Perm Krai": "Пермський край", "Primorskiy Kray": "Приморський край",
    "Pskov Oblast": "Псковська обл.", "Republic of Sakha (Yakutia)": "Якутія",
    "Respublika Adygeya": "Адигея", "Respublika Altay": "Республіка Алтай",
    "Respublika Buryatiya": "Бурятія", "Respublika Ingushetiya": "Інгушетія",
    "Respublika Kareliya": "Карелія", "Respublika Khakasiya": "Хакасія",
    "Respublika Mariy-El": "Марій Ел", "Respublika Mordoviya": "Мордовія",
    "Respublika Tyva": "Тива", "Rostov Oblast": "Ростовська обл.",
    "Ryazan Oblast": "Рязанська обл.", "Sakhalin Oblast": "Сахалінська обл.",
    "Samara Oblast": "Самарська обл.", "Sankt-Peterburg": "Санкт-Петербург",
    "Saratovskaya Oblast": "Саратовська обл.", "Smolensk Oblast": "Смоленська обл.",
    "Stavropol Kray": "Ставропольський край", "Sverdlovsk Oblast": "Свердловська обл.",
    "Tambov Oblast": "Тамбовська обл.", "Tatarstan": "Татарстан",
    "Tomsk Oblast": "Томська обл.", "Transbaikal Territory": "Забайкальський край",
    "Tula Oblast": "Тульська обл.", "Tver Oblast": "Тверська обл.",
    "Tyumen Oblast": "Тюменська обл.", "Udmurtskaya Respublika": "Удмуртія",
    "Ulyanovsk Oblast": "Ульяновська обл.", "Vladimirskaya Oblast’": "Владимирська обл.",
    "Volgograd Oblast": "Волгоградська обл.", "Vologda Oblast": "Вологодська обл.",
    "Voronezh Oblast": "Воронезька обл.", "Yamalo-Nenetskiy Avtonomnyy Okrug": "ЯНАО",
    "Yaroslavl Oblast": "Ярославська обл.",
    "Yevrey (Jewish) Autonomous Oblast": "Єврейська АО",
}

# ---- порівняння назв у різних письмах --------------------------------------

_RU_LAT = {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
           "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
           "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
           "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
           "я": "ya", "і": "i", "ї": "yi", "є": "ye", "ґ": "g", "'": "", "ʼ": "", "’": ""}
_UA_LAT = dict(_RU_LAT, **{"г": "h", "и": "y", "і": "i", "ї": "i", "є": "ie", "ю": "iu",
                           "я": "ia", "й": "i"})


def _rom(s, table):
    return "".join(table.get(c, c) for c in s.lower())


def _lat_norm(s):
    """Латиниця без різниці між системами: y/i, ya/ia, діакритика, апостроф."""
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z ]", "", s.replace("-", " "))
    # родові слова: «Zherdevsky District» і «Жердевский район» — одне
    s = re.sub(r"\b(?:district|rayon|raion|rajon)\b", "raion", s)
    s = re.sub(r"\b(?:urban|gorodskoy|gorodskoi|gorodskoj)\s+okrug\b", "okrug", s)
    s = re.sub(r"\bgorod\b", "", s)
    # прикметник району до назви міста: «Курманський район» ~ «Kurman Raion»
    s = re.sub(r"(\w{3,}?)(?:s['’]?k[yi]*|ts['’]?k[yi]*) raion\b", r"\1 raion", s)
    s = s.replace("yi", "i").replace("iy", "i").replace("y", "i").replace("j", "i")
    s = re.sub(r"i+", "i", s)
    return re.sub(r"\s+", " ", s).strip()


def _sim(a, b):
    """Схожість рядків; порядок слів не важить («Mikhaylovka Urban Okrug» і
    «Городской округ город Михайловка»)."""
    r = difflib.SequenceMatcher(None, a, b).ratio()
    if " " in a or " " in b:
        r = max(r, difflib.SequenceMatcher(None, " ".join(sorted(a.split())),
                                           " ".join(sorted(b.split()))).ratio())
    return r


def _ua_fix(a):
    a = a.replace("'", "ʼ").replace("’", "ʼ")
    # «Киів», «Украінськ», «Горностаівка»: в альт-назвах GeoNames часто
    # білоруське «і» після голосної, в українській там завжди «ї».
    return re.sub(r"(?<=[аеєиіїоуюяʼ])і", "ї", a, flags=re.I)


_UK_ABC = re.compile(r"^[а-щьюяєіїґʼ'’\s\-]+$", re.I)


def pick_uk(latin, alts, thr=0.95):
    """Українська альт-назва запису України, з якої зроблено його латиницю.

    Поріг 0.95, а не нижче: на 0.7 до вибору потрапляють білоруські форми
    («Мірнаград», «Сарокіна»), на 0.95 — 4 розбіжності з Wikidata на 161.
    """
    ln, best, bs = _lat_norm(latin), None, 0.0
    for a in alts:
        if not _UK_ABC.match(a) or not re.search(r"[іїєґʼ'’]|[сц]ьк", a, re.I):
            continue
        a = _ua_fix(a)
        s = _sim(_lat_norm(_rom(a, _UA_LAT)), ln)
        if s > bs:
            best, bs = a, s
    return best if bs >= thr else None


def _rom_ru(s):
    out = []
    for i, ch in enumerate(s.lower()):
        pv = s[i - 1].lower() if i else ""
        if ch == "ё":
            out.append("yo")
        elif ch == "е" and (not pv or pv in "аеёиоуыэюяьъ"):
            out.append("ye")
        else:
            out.append(_RU_LAT.get(ch, ch))
    return "".join(out)


def _lat_key(s):
    s = unicodedata.normalize("NFC", s.lower())
    s = s.replace("’", "").replace("'", "").replace("ʼ", "")
    # GeoNames пише «ё» і як «ë» (Venëv), і як «yo» (Tokaryovka)
    s = re.sub(r"(?<=[bcdfghklmnprstvzh])y?ë|yë", "yo", s)
    return re.sub(r"[^a-z ]", "", s.replace("-", " "))


def _restore_yo(ru, latin):
    """Латиниця GeoNames пише «ë» («Venëv», «Vorob’yëvka»), а кирилична
    альт-назва часто його губить («Венев»). Повертаємо «ё» там, де воно
    робить назву ближчою до латиниці."""
    if not re.search(r"ë|yo", latin.lower()):
        return ru
    target, cur = _lat_key(latin), ru
    for i, ch in enumerate(ru):
        if ch.lower() != "е":
            continue
        alt = cur[:i] + ("Ё" if ch.isupper() else "ё") + cur[i + 1:]
        if _sim(_lat_key(_rom_ru(alt)), target) > _sim(_lat_key(_rom_ru(cur)), target):
            cur = alt
    return cur


def _seps(s):
    return re.sub(r"[^ \-]", "", s)


def pick_ru(latin, alts, extra=()):
    """Російська назва запису: кирилиця, з якої зроблено його латиницю.

    Серед альт-назв, що дають ту саму латиницю, вирішують ознаки, кожна з
    прикладу: лише російська абетка (сербське «Кирејевск», башкирське
    «Ҡурман районы»); ті самі роздільники, що в латиниці («Белая-Берёзка»
    проти «Belaya Berëzka»); мʼякий знак усередині лише там, де його має
    латиниця («Коломьна»); кінцевий — навпаки, бажаний («Ставрополь»:
    GeoNames часто губить кінцевий апостроф).
    """
    ln, cands = _lat_norm(latin), []
    soft = latin.rstrip("’'").count("’") + latin.rstrip("’'").count("'")
    for a in list(extra) + list(alts):
        # «Воробйове» — українська форма без і/ї/є: «приголосна + й + голосна»
        # у російській не буває, а поверх неї відновлювалось «ё» («Воробйовьо»)
        if not GC.CYRILLIC.match(a) or re.search(r"[бвгджзклмнпрстфхцчшщ]й[аоуеэ]", a, re.I):
            continue
        s = _sim(_lat_norm(_rom(a, _RU_LAT)), ln)
        inner = len(re.findall(r"[ьъ](?=.)", a, re.I))
        # друга міра — латиниця з «ye/oy»: «Bol’shoye» — Большое, а не
        # Большой (перша міра зводить y/i й дає нічию)
        s2 = _sim(_lat_key(_rom_ru(a)), _lat_key(latin))
        cands.append((round(s, 3), round(s2, 3), _seps(a) == _seps(latin), a in extra,
                      -max(0, inner - soft), a[-1:] in "ьЬ", a))
    if not cands:
        return None
    best = max(cands)
    return _restore_yo(best[-1], latin) if best[0] >= 0.8 else None


# ---- відтворення російських назв українською -------------------------------

_CONS = set("бвгджзклмнпрстфхцчшщ")
_LEX = {"большой": "великий", "большая": "велика", "большое": "велике", "большие": "великі",
        "белый": "білий", "белая": "біла", "белое": "біле", "белые": "білі",
        "черный": "чорний", "черная": "чорна", "черное": "чорне", "черные": "чорні",
        "средний": "середній", "средняя": "середня", "среднее": "середнє",
        "нижний": "нижній", "нижняя": "нижня", "нижнее": "нижнє", "нижние": "нижні",
        "верхний": "верхній", "верхняя": "верхня", "верхнее": "верхнє", "верхние": "верхні",
        "великий": "великий", "великая": "велика", "великое": "велике", "великие": "великі",
        "владимир": "владимир", "толстой": "толстой",
        "район": "район", "округ": "округ", "городской": "міський", "городское": "міське",
        "муниципальный": "муніципальний", "поселение": "поселення",
        "сельское": "сільське", "область": "область", "край": "край",
        "республика": "республіка"}
_UNIT = {"район", "округ", "міський", "міське", "муніципальний", "поселення", "сільське",
         "область", "край", "республіка"}
# Закінчення слова. Порядок важливий: довше раніше. Асиміляцій на кшталт
# «Острогожский -> Острогозький» тут свідомо нема: Вікіпедія пише і так, і
# «Всеволожський», «Заокський», «Вачський» — правило ламало більше, ніж давало.
_ENDS = (("цкий", "цький"), ("сский", "ський"), ("ский", "ський"),
         ("цкая", "цька"), ("сская", "ська"), ("ская", "ська"),
         ("цкое", "цьке"), ("сское", "ське"), ("ское", "ське"),
         ("цкие", "цькі"), ("ские", "ські"),
         ("ний", "ній"), ("няя", "ня"), ("нее", "нє"), ("ние", "ні"),
         ("ый", "ий"), ("ая", "а"), ("яя", "я"), ("ое", "е"), ("ые", "і"), ("ие", "і"),
         ("цк", "цьк"), ("сск", "ськ"), ("ск", "ськ"),
         ("ец", "ець"), ("ица", "иця"), ("ицы", "иці"), ("ичи", "ичі"), ("ши", "ші"),
         ("щи", "щі"), ("жи", "жі"), ("тти", "тті"), ("чи", "чі"), ("цы", "ці"),
         ("рь", "р"), ("шь", "ш"), ("жь", "ж"), ("чь", "ч"), ("щь", "щ"), ("мь", "м"))
# «-ой» — прикметник («Сухой», «Донской», «Лесной», «Чусовой», «Крутой»),
# але не іменник: «Уренгой», «Джанкой», «Металлострой», кавказькі «Ачхой»,
# «Курчалой». На замірі базових підписів ширший набір («[лдрсж]ой», будь-яке
# «хой») давав «Металлострий», «Ачхий-Мартан», «Курчалий».
_ADJ_OY = re.compile(r"(?:ск|цк|[нвт]|[аеиоуы]х)ой$")
# «и» лишається «и» після цих літер; після решти приголосних — «і». Це
# «правило дев'ятки» плюс к і х: на 1608 парах з Вікіпедії «ки/хи»
# лишаються «ки/хи» втричі частіше («Луки», «Валуйки»).
_KEEP_I = set("дтзсцчшщжркх")
# Перші частини складних назв, після яких «и» починає корінь.
_JOINT = re.compile(r"(?:ново|старо|мало|велико|больше|красно|бело|черно|перво|"
                    r"верхне|нижне|средне|зелено|светло|долго|широко)$")
# Корені, спільні з українськими іменами й словами, де «и» лишається «и»:
# «Михайловка», «Маломихайловка», «Дмитровский район» (було «Дмітровський»),
# «Кириллов», «Мирный» — корінь будь-де в слові.
_UK_ROOTS = ("михайл", "дмитр", "кирил", "мирн", "мирон", "вишн")


def _cap(s, like):
    return s[:1].upper() + s[1:] if like[:1].isupper() else s


def _word(w, nine=True):
    lo = w.lower()
    m = re.match(r"(нижне|верхне|средне)(?=[а-яё]{3})", lo)
    if m:              # «Нижнекамск» -> «Нижньокамськ»
        head = {"нижне": "нижньо", "верхне": "верхньо", "средне": "середньо"}[m.group(1)]
        return _cap(head + _word(w[len(m.group(1)):], nine).lower(), w)
    if lo in _LEX:
        s = _LEX[lo]
        return s if s in _UNIT else _cap(s, "X")
    tail = ""
    if _ADJ_OY.search(lo) and len(lo) > 4:
        if lo.endswith("ской"):
            lo, tail = lo[:-4], "ський"
        elif lo.endswith("цкой"):
            lo, tail = lo[:-4], "цький"
        else:
            lo, tail = lo[:-2], "ий"
    elif lo.endswith("ье") and len(lo) > 3:
        # «-ье» українською: після шиплячої — прикметник середнього роду
        # («Лебяжье» -> «Лебʼяже», «Гремячье» -> «Гремʼяче»), після губної й
        # р — апостроф («Верховье» -> «Верховʼя», «Поморье» -> «Поморʼя»),
        # після решти — подвоєння («Раздолье» -> «Раздолля», «Полесье» ->
        # «Полесся»). Було «Лебʼяжьє», «Верховʼє».
        # Іменник із префіксом («Заволжье», «Междуречье», «Подгорье») —
        # подвоєння й після шиплячої: «Заволжжя», «Междуріччя»-подібне.
        c = lo[-3]
        noun = re.match(r"(?:за|при|под|по|между|над|пере|раз|без)", lo)
        if c in "жчшщ" and not noun:
            lo, tail = lo[:-2], "е"
        elif c in "бпвмфр":
            lo, tail = lo[:-2], "ʼя"
        else:
            lo, tail = lo[:-2], c + "я"
    elif nine and re.search(r"[^тчщжшдзср]ино$", lo):
        lo, tail = lo[:-3], "іно"          # «Шебекино» -> «Шебекіно»
    else:
        for a, b in _ENDS:
            if lo.endswith(a) and len(lo) > len(a) + 1:
                lo, tail = lo[:-len(a)], b
                break
    keep = {j + k for r in _UK_ROOTS for j in range(len(lo)) if lo.startswith(r, j)
            for k in range(len(r))}
    out = []
    for i, ch in enumerate(lo):
        pv = lo[i - 1] if i else ""
        nx = lo[i + 1] if i + 1 < len(lo) else (tail[:1] or "#")
        if ch == "ы":
            ch = "и"
        elif ch == "э":
            ch = "е"
        elif ch == "ъ":
            ch = "ʼ"
        elif ch == "ё":
            if pv in "ьъ" and out:          # «Воробьёвка» -> «Воробйовка»
                out.pop()
                ch = "йо"
            else:
                ch = "о" if pv in "жчшщц" else ("ьо" if pv in _CONS else "йо")
        elif ch == "е":
            if not pv or pv in "аеёиоуыэюяьъ":
                ch = "є"
        elif ch == "и":
            prefix_pri = lo[max(0, i - 2):i] == "пр" and nx in "аоу"   # «Приазовский»
            # межа частин складної назви — «і», як на початку слова:
            # «Новоивановское» -> «Новоіванівське», а не «Новоївановське»
            joint = re.search(_JOINT, lo[:i]) is not None
            if not pv or joint or (nx in "аеёиоуэюя" and not prefix_pri) \
                    or (nine and pv in _CONS and pv not in _KEEP_I and i not in keep):
                ch = "і"
            elif pv in "аоуеэюяё":
                ch = "ї"
        out.append(ch)
    s = re.sub(r"([бпвмфр])[ьъ](?=[яюєї])", r"\1ʼ", "".join(out) + tail)
    return s.upper() if w.isupper() and len(w) > 1 else _cap(s, w)     # «ХТЗ»


def ru2uk(name, nine=True):
    """Російська назва -> українське відтворення: «Самолётная Ветелка» ->
    «Самольотна Ветелка», «Старые Богады» -> «Старі Богади»."""
    name = re.sub(r"(?<=округ )город\s+", "", name, flags=re.I)  # «…округ город Михайловка»
    return "".join(_word(p, nine) if p and p not in (" ", "-") else p
                   for p in re.split(r"([ \-])", name))


# «-ино» -> «-ине»: український присвійний суфікс -ин- («Витине», «Наташине»,
# «Юркине»); було «-іне» — «Витіне», «Наташіне».
_UA_ENDS = (("овка", "івка"), ("евка", "ївка"), ("ово", "ове"), ("ево", "еве"),
            ("ино", "ине"))


def ru2uk_ua(name):
    """Для місць України: офіційні назви мають українські закінчення
    (-івка, -ове, -іне), а «и» лишається «и» («Лиман», «Житомир»)."""
    out = []
    for p in re.split(r"([ \-])", ru2uk(name, nine=False)):
        for a, b in _UA_ENDS:
            if p.lower().endswith(a) and len(p) > len(a) + 1:
                if a == "евка" and p[-5:-4].lower() not in "аеоуиіяюєї":
                    b = "івка"
                p = p[:-len(a)] + b
                break
        out.append(p)
    return "".join(out)


# Зворотна транслітерація КМУ-2010 — латиниця GeoNames для України здебільшого
# саме українська («Yakymivka», «Bilovods'k»), і для місця без української
# альт-назви вона точніша за російську назву: «Акимовский район» дає
# «Акимовський», а латиниця — «Якимівка». Чого з КМУ не відновити: мʼякий
# знак усередині слова («Rovenky» — Ровеньки) і межу «і/ї/й» після голосної;
# тут лише однозначне.
_KMU = (("shch", "щ"), ("zgh", "зг"), ("zh", "ж"), ("kh", "х"), ("ts", "ц"), ("ch", "ч"),
        ("sh", "ш"), ("a", "а"), ("b", "б"), ("v", "в"), ("h", "г"), ("g", "ґ"), ("d", "д"),
        ("e", "е"), ("z", "з"), ("y", "и"), ("i", "і"), ("k", "к"), ("l", "л"), ("m", "м"),
        ("n", "н"), ("o", "о"), ("p", "п"), ("r", "р"), ("s", "с"), ("t", "т"), ("u", "у"),
        ("f", "ф"), ("'", "ʼ"), ("’", "ʼ"), ("`", "ʼ"), ("\x01", "ь"))
_KMU_VOW = "aeiouy"


def kmu2uk(latin):
    out = []
    for w in re.split(r"([ \-])", latin):
        if not w or w in (" ", "-"):
            out.append(w)
            continue
        # апостроф перед приголосною — це мʼякий знак старої системи
        # («Bilovods'k»), перед голосною — апостроф («Slov`yanoserbsk»)
        lo = re.sub(r"(?<=[bcdfghklmnprstvz])['’`](?=[bcdfghklmnprstvz])", "\x01", w.lower())
        lo = re.sub(r"(?<=ch|sh|zh|ts)['’`](?=[aeiou])", "", lo)     # «Rybach'e»
        # «Il’ichevskiy»: після «л», «н», «т»… апостроф — це мʼякий знак
        lo = re.sub(r"(?<=[dtzslnkgh])['’`](?=[aeiouy])", "\x01", lo)
        tail = ""
        for a, b in (("tske", "цьке"), ("ske", "ське"), ("skyi", "ський"), ("ska", "ська"),
                     ("sk", "ськ"), ("tsk", "цьк"), ("tsia", "ція"), ("iia", "ія"),
                     ("yi", "ий"), ("skyy", "ський"), ("skiy", "ський"), ("sky", "ський"),
                     ("raion", "район"), ("rayon", "район"), ("district", "район"),
                     ("oblast", "область")):
            if lo.endswith(a):
                lo, tail = lo[:-len(a)], b
                break
        res, i = "", 0
        while i < len(lo):
            head = i == 0 or lo[i - 1] in " -'’`"
            two = lo[i:i + 2]
            if head and two in ("ye", "yi", "yu", "ya"):
                res += {"ye": "є", "yi": "ї", "yu": "ю", "ya": "я"}[two]
                i += 2
                continue
            if head and lo[i] == "y":
                res, i = res + "й", i + 1
                continue
            if two == "yi" and i:                # «Kadiyivka», «Mykolayiv»
                res, i = res + "ї", i + 2
                continue
            if lo[i] == "y" and i and lo[i - 1] in "aeiou" \
                    and (i + 1 == len(lo) or lo[i + 1] not in _KMU_VOW):
                res, i = res + "й", i + 1      # «Mykhaylivka»
                continue
            if two in ("ya", "ye", "yu") and i and lo[i - 1] in "bcdfghklmnprstvz":
                # стара система: «Kamyanka» — Камʼянка, «Novoselytsya» — Новоселиця
                res += ("ʼ" if lo[i - 1] in "bpvmfr" else "") + {"ya": "я", "ye": "є", "yu": "ю"}[two]
                i += 2
                continue
            if two in ("ia", "ie", "iu") and i:
                # після приголосної «ia» — це «я», після голосної — «я» теж
                res += {"ia": "я", "ie": "є", "iu": "ю"}[two]
                i += 2
                continue
            if lo.startswith("ivka", i) and i and lo[i - 1] in _KMU_VOW:
                res, i = res + "ївка", i + 4
                continue
            if lo[i] == "i" and i and lo[i - 1] in "aeouy" and (i + 1 == len(lo) or lo[i + 1] not in _KMU_VOW):
                res, i = res + "й", i + 1      # «Novoaidar», «Hai»
                continue
            for a, c in _KMU:
                if lo.startswith(a, i):
                    res += c
                    i += len(a)
                    break
            else:
                i += 1
        res += tail
        if w.isupper() and len(w) > 1:
            res = res.upper()
        out.append(res if res in ("район", "область") else res[:1].upper() + res[1:])
    return "".join(out)


# Латиниця GeoNames для України буває й російською (Крим, окуповане:
# «Olenevka», «Uyutnoye», «Pervomayskiy») — тоді джерело назви російське.
_RU_STYLE = re.compile(r"ë|’|g|yy\b|iy\b|ye\b|oe\b|sky\b|skiy|evka\b|ovka\b|aya\b|"
                       r"(?<=\w)yo|[oe]vo\b|ino\b|district|rayon", re.I)   # «Vorobyovo»


# ---- Wikidata ---------------------------------------------------------------

_UNIT_LAT = re.compile(r"\b(rayon|raion|district|okrug|oblast|respublika|republic|krai|kray)\b", re.I)
_UNIT_UK = re.compile(r"\b(район|округ|область|рада|республіка|край)\b", re.I)


def _words(s):
    return len([w for w in re.split(r"[\s\-]+", s) if w])


_ADJ = re.compile(r"(?:ський|цький|зький|ий|ій|ська|цька|ське|цьке)$", re.I)


def _first(s):
    return next((w for w in re.split(r"[\s\-]+", s) if w), "")


def _renamed(aliases, latin):
    """Wikidata знає назву з латиниці як стару: псевдонім, що збігається з нею."""
    return any(_latin_sim(a, latin) >= 0.8 for a in aliases)


def _wd_ok(label, latin, fallback, cc="RU", aliases=()):
    """Чи мітка Wikidata — назва саме цього місця, як його пишуть канали.

    Три відсіви, кожен із прикладу: схожість із латиницею або з українським
    відтворенням російської назви (≥0.6: «Великі Козли» проходить, «Тархани»
    для Лермонтова й «Катирлез» для Войкова ні); той самий вид адмінодиниці
    («Клинський район» для «Gorodskoy Okrug Klin», «Харківська міська рада»
    для району — ні); не більше слів, ніж у назві («Музей-садиба
    Архангельське», «Зеленоградський адміністративний округ» — ні).
    """
    # Родові слова зі схожості прибрано: спільне «район» підтягувало
    # «Ломоносовський район» до «Петродворцового» (заміряно 22 вересня 2026).
    def bare(x):
        return re.sub(r"\b(?:raion|okrug|район|округ|міський|міська|obl|обл)\b\.?", " ", x).strip()
    s = _sim(bare(_lat_norm(_rom(label, _UA_LAT))), bare(_lat_norm(latin)))
    if fallback:
        s = max(s, _sim(bare(label.lower()), bare(fallback.lower())))
    # Перейменування, про яке Wikidata знає: «Микільське» з псевдонімом
    # «Нікольське» для «Nikol's’ke» — мітка новіша за GeoNames, беремо її.
    if s < 0.6 and cc == "UA" and _renamed(aliases, latin):
        s = 1.0
    if s < 0.6:
        return False
    # «Льгов» для селища «L’govskiy» (відтворення «Льговський») — інше місце,
    # місто; прикметник проти іменника виказує сусідній елемент. Лише для
    # назв без родового слова: у районів запасна назва буває іменником
    # («Якимівка район»), а мітка — прикметником, і вона правильна.
    if (fallback and not _UNIT_LAT.search(latin) and not _UNIT_UK.search(label)
            and bool(_ADJ.search(_first(label))) != bool(_ADJ.search(_first(fallback)))):
        return False
    lu = {m.lower() for m in _UNIT_LAT.findall(latin)}
    ku = {m.lower() for m in _UNIT_UK.findall(label)}
    if "рада" in ku or bool(lu) != bool(ku):
        return False
    if "okrug" in lu and "округ" not in ku:
        return False
    if lu & {"rayon", "raion", "district"} and "район" not in ku:
        return False
    return _words(label) <= max(_words(fallback or latin), _words(latin))


def load_wd(path=WD_UK, col=1):
    """geonameid -> мітки Wikidata (col=1) або псевдоніми для України (col=2)."""
    out = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                c = line.rstrip("\n").split("\t")
                if len(c) > col and c[col]:
                    out[c[0]] = c[col].split("|")
    return out


# ---- запис газетира -> українська назва -------------------------------------

def _fallback(latin, cc, alts, extra):
    if cc == "UA":
        p = pick_uk(latin, alts)
        if p:
            return p
    ru = pick_ru(latin, alts, extra)
    if not ru and cc != "UA":
        # Латиниця — англійський екзонім («Oryol District» для «Орловский
        # район»), тож зі збігом не вийде. Єдина російська назва запису —
        # і є його назва.
        # Але лише схожої: «Zaytseva Gora» має єдину альт-назву «Цветовка» —
        # це інше село. Поріг 0.5 без родових слів пропускає «Oryol
        # District» / «Орловский район» і не пропускає її.
        only = {a for a in list(alts) + list(extra) if GC.CYRILLIC.match(a)}
        one = only.pop() if len(only) == 1 else None
        bare = lambda x: re.sub(r"\b(?:raion|okrug)\b", " ", x).strip()
        if one and _sim(bare(_lat_norm(_rom(one, _RU_LAT))), bare(_lat_norm(latin))) >= 0.5:
            ru = one
            # «Kulebaksky Urban Okrug» з альт-назвою «Кулебакский район»: район
            # перетворено на округ, альт-назва стара — вид беремо з латиниці
            if re.search(r"\bokrug\b", latin, re.I) and re.search(r"\bрайон\b", ru, re.I):
                ru = re.sub(r"\bрайон\b", "городской округ", ru, flags=re.I)
            if _UNIT_LAT.search(latin) and not re.search(r"район|округ", ru, re.I):
                ru += " район"
    if cc == "UA":
        a = ru2uk_ua(ru) if ru else None
        # російське джерело — коли його відтворення сходиться з латиницею
        # або сама латиниця російська; інакше латиниця КМУ точніша
        if a and (_RU_STYLE.search(latin)
                  or _sim(_lat_norm(_rom(a, _UA_LAT)), _lat_norm(latin)) >= 0.95):
            return a
        return kmu2uk(latin)
    return ru2uk(ru) if ru else None


# «Gorod Shebekino», «Город Шебекино»: тип поселення, а не частина назви
_PREFIX = re.compile(r"^(?:gorod|poselok|selo|stanitsa|derevnya|urochishche|город|посёлок|поселок|"
                     r"село|станица|деревня|урочище)\s+", re.I)
_UNIT_CAP = re.compile(r"(?<=\S )(Район|Округ|Область|Міський|Міська)\b")


def name_of(latin, cc="RU", alts=(), extra=(), wd=(), wd_alias=()):
    """Українська назва запису GeoNames за описаною вище чергою джерел."""
    if not latin:
        return ""
    n = _name_of(_PREFIX.sub("", latin), cc,
                 [_PREFIX.sub("", GC.clean_alt(a)) for a in alts if a],
                 [_PREFIX.sub("", a) for a in extra], wd, wd_alias)
    # «Генічеський Район» з альт-назви: родові слова — з малої
    n = _UNIT_CAP.sub(lambda m: m.group(1).lower(), n)
    if " " not in n and n[:1].islower():      # «республіка» як уся назва
        n = n[:1].upper() + n[1:]
    # Губна після голосної перед я/ю/ї — з апострофом: «Камянка» (так у
    # Wikidata), «Полубянка», «Девятське». Перевірено на всіх 51 збігах
    # сховища й базових підписів; «є» сюди не входить — «Благовєщенськ»,
    # «Совєтськ» пишуться так за конвенцією, без апострофа.
    return _APOS.sub("ʼ", n)


_APOS = re.compile(r"(?<=[аеєиіїоуюя][бпвмф])(?=[яюї])", re.I)


def _name_of(latin, cc, alts, extra, wd, wd_alias=()):
    if re.search(r"[а-яёіїєґ]", latin, re.I):       # аліас конфігу, кирилиця
        return ALIAS_UK.get(latin, latin)
    if latin in CITY_UA:
        return CITY_UA[latin]
    if latin in UA_OBLAST:
        return UA_OBLAST[latin]
    if latin in RU_ADM1:
        return RU_ADM1[latin]
    if latin in EXC:
        return EXC[latin]
    fb = _fallback(latin, cc, alts, extra)
    good = [w for w in wd if _wd_ok(w, latin, fb, cc, wd_alias)]
    if good:
        # кілька елементів на один ID — найближчий до того, що пишуть канали
        best = max(good, key=lambda w: _sim(w.lower(), (fb or latin).lower()))
        # Україна: латиниця GeoNames — офіційна українська. Якщо українська
        # альт-назва збігається з нею точніше за мітку Wikidata, мітка стара:
        # «Красноперекопський район» проти «Перекопський район» / «Perekop Raion»
        # (перейменовано 2024).
        # Але не тоді, коли Wikidata знає латиницю як стару назву (вище).
        p = pick_uk(latin, alts) if cc == "UA" and not _renamed(wd_alias, latin) else None
        if p and p != best and _latin_sim(p, latin) > _latin_sim(best, latin):
            return p
        return best
    return fb or uk_latin(latin)


def _latin_sim(uk_name, latin):
    return _sim(_lat_norm(_rom(uk_name, _UA_LAT)), _lat_norm(latin))


class Names:
    """Українські назви для набору місць подій або записів газетира.

    `Names(places=[(назва, lat, lon), …])` — для ночі редактора;
    `Names(ids={geonameid, …})` — для базових підписів (`labels.py`).
    """

    def __init__(self, places=(), ids=(), gaz=GAZ, wd_path=WD_UK):
        want = {p[0] for p in places}
        ids = set(ids)
        self.wd = load_wd(wd_path)
        self.wd_alias = load_wd(wd_path, col=2)
        self.extra = GC._load_extra(GC.EXTRA)
        self.recs = {}          # назва -> [(lat, lon, uk)]
        self.by_id = {}
        for path in gaz:
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as f:
                for line in f:
                    head = line.split("\t", 2)
                    if len(head) < 3 or (head[1] not in want and head[0] not in ids):
                        continue
                    c = line.rstrip("\n").split("\t")
                    if len(c) < 15:
                        continue
                    n = name_of(c[GC.NAME], c[GC.CC], c[GC.ALT].split(","),
                                self.extra.get(c[0], ()), self.wd.get(c[0], ()),
                                self.wd_alias.get(c[0], ()))
                    self.recs.setdefault(c[GC.NAME], []).append(
                        (float(c[GC.LAT]), float(c[GC.LON]), n))
                    self.by_id[c[0]] = n

    def place(self, name, lat=None, lon=None):
        """Назва місця події: запис газетира з тією ж назвою й координатою."""
        if not name:
            return ""
        if re.search(r"[а-яёіїєґ]", name, re.I):
            return ALIAS_UK.get(name, name)
        cands = self.recs.get(name)
        if cands and lat is not None:
            la, lo, n = min(cands, key=lambda r: (r[0] - lat) ** 2 + (r[1] - lon) ** 2)
            if abs(la - lat) < 1e-3 and abs(lo - lon) < 1e-3:
                return n
        # запису нема (газетир оновився, або подію зібрано з іншого) — без
        # координати тезки не розрізнити, тож лише те, що не залежить від запису
        return name_of(name)
