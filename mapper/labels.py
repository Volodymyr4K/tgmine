#!/usr/bin/env python3
"""Підписи населених пунктів українською.

ЗАДАЧА. На карті театру було 53 підписи — обласні центри. Кадр однієї області
лишався порожнім: маршрут іде повз десяток міст, і жодне не названо.
Потрібні сотні підписів, і всі українською.

ЧОМУ НЕ ПРЯМО З ГАЗЕТИРА. GeoNames віддає латиницю («Novokhopërsk»), а
латиниця на україномовній карті гірша за відсутність підпису. Російська назва
є в полі alternatenames, тож беремо її й передаємо через правила українського
відтворення.

ЩО ЦІ ПРАВИЛА РОБЛЯТЬ І ЧОГО НЕ РОБЛЯТЬ. Вони механічні: -ск -> -ськ,
-цк -> -цьк, ы -> и, э -> е, ё -> йо/ьо, и -> і (крім позиції після
шиплячих і ц). Цього досить для «Курск -> Курськ», «Липецк -> Липецьк»,
«Мичуринск -> Мічуринськ». Це НЕ заміна редакторові: назви на кшталт
«Орёл -> Орел» правило дає правильно, а виняткові випадки лишаються в
ручному словнику CITY_UA нижче, який має пріоритет над правилами.
"""
import json
import re
import sys

import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# Ручний словник великих міст: правила транслітерації дають прийнятний
# результат для дрібних НП, але помилка в назві обласного центру помітна
# кожному читачеві, тому вони виписані.
CITY_UA = {
    "Moscow": "Москва", "Kyiv": "Київ", "Kharkiv": "Харків",
    "Nizhniy Novgorod": "Нижній Новгород", "Kazan": "Казань",
    "Rostov-on-Don": "Ростов-на-Дону", "Voronezh": "Воронеж",
    "Volgograd": "Волгоград", "Odesa": "Одеса", "Dnipro": "Дніпро",
    "Donetsk": "Донецьк", "Krasnodar": "Краснодар", "Saratov": "Саратов",
    "Zaporizhzhya": "Запоріжжя", "Tolyatti": "Тольятті",
    "Ulyanovsk": "Ульяновськ", "Yaroslavl": "Ярославль",
    "Kryvyy Rih": "Кривий Ріг", "Sevastopol": "Севастополь",
    "Ryazan’": "Рязань", "Astrakhan": "Астрахань", "Penza": "Пенза",
    "Lipetsk": "Липецьк", "Cheboksary": "Чебоксари", "Tula": "Тула",
    "Mykolayiv": "Миколаїв", "Kursk": "Курськ", "Stavropol": "Ставрополь",
    "Vinnytsya": "Вінниця", "Bryansk": "Брянськ", "Tver": "Твер",
    "Ivanovo": "Іваново", "Luhansk": "Луганськ", "Vladimir": "Владимир",
    "Belgorod": "Бєлгород", "Kaluga": "Калуга", "Simferopol": "Сімферополь",
    "Smolensk": "Смоленськ", "Sochi": "Сочі", "Saransk": "Саранськ",
    "Orël": "Орел", "Tambov": "Тамбов", "Taganrog": "Таганрог",
    "Kostroma": "Кострома", "Cherkasy": "Черкаси", "Poltava": "Полтава",
    "Sumy": "Суми", "Chernihiv": "Чернігів", "Kremenchuk": "Кременчук",
    "Mariupol": "Маріуполь", "Melitopol": "Мелітополь", "Kerch": "Керч",
    "Novorossiysk": "Новоросійськ", "Ryazan": "Рязань", "Oryol": "Орел",

    # Друга черга словника. Правила будуються від латиниці GeoNames, а вона
    # для частини міст не транслітерація, а англійський екзонім: «Saint
    # Petersburg» давало «Саінт Петерсбург» просто на найбільшому підписі
    # карти. Решта — випадки, де механічне правило дає близьке, але не те:
    # «Ривне» замість «Рівне», «Тернопіл» замість «Тернопіль».
    "Saint Petersburg": "Санкт-Петербург",
    "Naberezhnyye Chelny": "Набережні Челни",
    "Rivne": "Рівне", "Ternopil": "Тернопіль", "Lutsk": "Луцьк",
    "Nalchik": "Нальчик", "Nazran": "Назрань",
    "Nizhnekamsk": "Нижньокамськ", "Kamyanske": "Камʼянське",
    "Velikiy Novgorod": "Великий Новгород", "Velikiye Luki": "Великі Луки",
    "Engels": "Енгельс", "Syzran": "Сизрань", "Podolsk": "Подольськ",
    "Mytishchi": "Митищі", "Zheleznodorozhnyy": "Желєзнодорожний",
    "Korolev": "Корольов", "Pyatigorsk": "Пʼятигорськ",
    "Kislovodsk": "Кисловодськ", "Dimitrovgrad": "Димитровград",
    "Cherkessk": "Черкеськ", "Shchyolkovo": "Щолково",
    "Bataysk": "Батайськ", "Yevpatoriya": "Євпаторія",
    "Nikopol": "Нікополь", "Slovyansk": "Словʼянськ",
    "Zelenodolsk": "Зеленодольськ", "Siverskodonetsk": "Сєвєродонецьк",
    "Kamyanets-Podilskyi": "Камʼянець-Подільський",
    "Zhukovsky": "Жуковський", "Ramenskoye": "Раменське",
    "Nevinnomyssk": "Невинномиськ", "Elektrostal’": "Електросталь",
    "Kolpino": "Колпіно", "Odintsovo": "Одинцово", "Lyubertsy": "Люберці",
    "Balashikha": "Балашиха", "Khimki": "Хімки", "Zelenograd": "Зеленоград",
    "Domodedovo": "Домодєдово", "Krasnogorsk": "Красногорськ",
    "Shchelkovo": "Щолково", "Serpukhov": "Серпухов", "Noginsk": "Ногінськ",
    "Orekhovo-Zuyevo": "Орєхово-Зуєво", "Voskresensk": "Воскресенськ",
    "Pushkino": "Пушкіно", "Klin": "Клин", "Dubna": "Дубна",
    "Vidnoye": "Видне", "Reutov": "Реутов", "Lobnya": "Лобня",
    "Zhukovskiy": "Жуковський", "Ivanteyevka": "Івантіївка",
    "Dolgoprudnyy": "Долгопрудний", "Dmitrov": "Дмитров",
    "Chekhov": "Чехов", "Stupino": "Ступіно", "Yegoryevsk": "Єгорʼєвськ",
    "Naro-Fominsk": "Наро-Фомінськ", "Bronnitsy": "Бронниці",
    "Aleksin": "Алексин", "Uzlovaya": "Узловая", "Novomoskovsk": "Новомосковськ",
    "Yefremov": "Єфремов", "Shchekino": "Щокіно", "Donskoy": "Донськой",
    "Rossosh’": "Россош", "Borisoglebsk": "Борисоглібськ",
    "Gukovo": "Гуково", "Salsk": "Сальськ", "Azov": "Азов",
    "Millerovo": "Міллерово", "Kamensk-Shakhtinskiy": "Каменськ-Шахтинський",
    "Slavyansk-na-Kubani": "Славʼянськ-на-Кубані",
    "Gelendzhik": "Геленджик", "Anapa": "Анапа", "Tuapse": "Туапсе",
    "Yeysk": "Єйськ", "Tikhoretsk": "Тихорецьк", "Kropotkin": "Кропоткін",
    "Labinsk": "Лабінськ", "Belorechensk": "Білоріченськ",
    "Temryuk": "Темрюк", "Primorsko-Akhtarsk": "Приморсько-Ахтарськ",
    "Akhtubinsk": "Ахтубінськ", "Kotelnikovo": "Котельниково",
    "Mikhaylovka": "Михайлівка", "Uryupinsk": "Урюпинськ",
    "Frolovo": "Фролово", "Kalach-na-Donu": "Калач-на-Дону",
    "Svetlyy Yar": "Світлий Яр", "Zhirnovsk": "Жирновськ",
    # мʼякий знак у кінці, який із латиниці не видно
    "Uman": "Умань", "Korosten": "Коростень", "Boryspil": "Бориспіль",
    "Zvyahel": "Звягель", "Zviahel": "Звягель", "Chystopol": "Чистопіль",
    "Chistopol": "Чистополь", "Mariupol’": "Маріуполь",
    "Izmayil": "Ізмаїл", "Kolomyia": "Коломия", "Kolomyya": "Коломия",
    "Mineralnye Vody": "Мінеральні Води",
    "Mineral’nyye Vody": "Мінеральні Води",
    "Khrustalnyi": "Хрустальний", "Khrustalnyy": "Хрустальний",
    "Shchyokino": "Щокіно", "Shchekino": "Щокіно",
    "Kirishi": "Кириші", "Borovichi": "Боровичі", "Klimovsk": "Климовськ",
    "Mikhaylovsk": "Михайловськ", "Liski": "Лиски",
    "Krasnaya Glinka": "Красная Глинка", "Novaya Balakhna": "Нова Балахна",
    "Shuya": "Шуя", "Feodosiya": "Феодосія", "Oleksandriya": "Олександрія",
    "Berdychiv": "Бердичів", "Bakhmut": "Бахмут", "Yenakiyeve": "Єнакієве",
    "Kadiyivka": "Кадіївка", "Khrustalnyy": "Хрустальний",
    "Solnechnogorsk": "Солнечногорськ", "Vyksa": "Викса",
    "Solnetchnogorsk": "Солнечногорськ",
    "Shchëkino": "Щокіно", "Kirovo-Chepetsk": "Кирово-Чепецьк",
    "Bugulma": "Бугульма", "Budyonnovsk": "Будьонновськ",
    "Zarechnyy": "Зарічний", "Uzlovaya": "Узлова",
    "Giaginskaya": "Гіагінська", "Pereiaslav": "Переяслав",
    "Dobropillia": "Добропілля", "Bilopillia": "Білопілля",
    "Dzerzhinsky": "Дзержинський", "Kamensk-Shakhtinsky": "Каменськ-Шахтинський",
    "Terebovlia": "Теребовля", "Terebovlya": "Теребовля",
}

# Не міста, а райони всередині Москви, Одеси й Житомира: у газетирі вони
# позначені як населені пункти й лізуть у список нарівні з обласними
# центрами. На карті театру це просто сміття поверх самої Москви.
DROP = {
    "Cherëmushki", "Cheremushky", "Novo-Peredelkino", "Vostochnoe Degunino",
    "Bohuniya", "Zapadnoye Degunino", "Yuzhnoye Butovo", "Severnoye Butovo",
    "Bibirevo", "Otradnoye", "Mar’ino", "Golyanovo", "Perovo", "Kuz’minki",
    "Tekstil’shchiki", "Chertanovo", "Yasenevo", "Solntsevo", "Ochakovo",
    "Ramenki", "Kotlovka", "Zyuzino", "Nagornyy", "Donskoy Rayon",
}


# ЧОМУ НЕ З alternatenames. Спроба брати звідти російську назву дала
# «Волагду» замість Вологди й «Плоскуров» замість Хмельницького: у тому полі
# лежать назви багатьма мовами БЕЗ позначки мови, і перший кириличний рядок
# виявляється білоруським або застарілим. Латинська назва (поле 2) — одна,
# однозначна і вже є транслітерацією, тому правила будуються від неї.
PAIRS = [
    ("iyi", "ії"), ("yi", "ї"), ("shch", "щ"), ("sch", "щ"), ("zh", "ж"), ("kh", "х"), ("ch", "ч"),
    ("sh", "ш"), ("ts", "ц"), ("yu", "ю"), ("ya", "я"), ("ye", "є"),
    ("yo", "йо"), ("ay", "ай"), ("oy", "ой"), ("ey", "ей"), ("uy", "уй"),
    ("ë", "ьо"), ("ï", "ї"), ("é", "е"),
    ("a", "а"), ("b", "б"), ("v", "в"), ("g", "г"), ("d", "д"), ("e", "е"),
    ("z", "з"), ("i", "і"), ("y", "и"), ("j", "й"), ("k", "к"), ("l", "л"),
    ("m", "м"), ("n", "н"), ("o", "о"), ("p", "п"), ("r", "р"), ("s", "с"),
    ("t", "т"), ("u", "у"), ("f", "ф"), ("h", "г"), ("c", "ц"), ("w", "в"),
    ("x", "кс"), ("q", "к"), ("'", "ь"), ("’", "ь"), ("`", "ь"),
]
# закінчення обробляються ДО побуквеної заміни, інакше «-ск» дає «-ск»
# Закінчення знімаються ПОСЛІДОВНО: у «Khmelnytskyi» спершу «yi» -> «ий»,
# і лише потім видно «tsk» -> «цьк». За один прохід виходило «Хмелницкий».
TAILS = [("skiy", "ський"), ("skyy", "ський"), ("sky", "ський"),
         ("skaya", "ська"), ("skoye", "ське"), ("skoe", "ське"),
         # прикметникові назви на -ая/-ое українською втрачають це
         # закінчення: Отрадная -> Отрадна, Удельная -> Удельна
         ("naya", "на"), ("vaya", "ва"), ("laya", "ла"), ("raya", "ра"),
         ("noye", "не"), ("voye", "ве"),
         ("lnyy", "льний"),
         ("iya", "ія"), ("yia", "ия"), ("ayi", "аї"),
         ("yy", "ий"), ("iy", "ій"), ("yi", "ий"), ("ij", "ій"),
         ("tsk", "цьк"), ("sk", "ськ"), ("ets", "ець"), ("iv", "ів"),
         # Кінцеві -ы/-и російських назв українською це «и»: Шахти, Валуйки.
         # Виняток — на -ці: Клинці, Чернівці.
         ("tsy", "ці"), ("tsi", "ці"), ("y", "и"), ("i", "и")]

# «Правило дев'ятки»: після д, т, з, с, ц, ч, ш, ж, р пишеться «и», а не «і».
# Без нього виходили «Владікавказ», «Мічурінськ», «Клінці» — і це видно
# кожному читачеві, на відміну від тонкощів із м'яким знаком.
NINE = set("дтзсцчшжр")

# Кінцеве «-y» неоднозначне: у «Shakhty» це -ы (Шахти), у «Grozny» -ый
# (Грозний). З самої латиниці це не розрізнити, тому прикметникові назви
# театру просто перелічені. Виняток дешевший за правило, яке вгадує.
EXC = {
    "Grozny": "Грозний", "Groznyy": "Грозний", "Volzhsky": "Волзький",
    "Volzhskiy": "Волзький", "Khmelnytskyi": "Хмельницький",
    "Klintsy": "Клинці", "Novy Oskol": "Новий Оскол",
    "Stary Oskol": "Старий Оскол", "Krasny Sulin": "Красний Сулін",
    "Zheleznogorsk": "Желєзногорськ", "Kotelnich": "Котельнич",
    "Rossosh": "Россош", "Kstovo": "Кстово", "Uzlovaya": "Узловая",
    "Sergiyev Posad": "Сергієв Посад", "Orekhovo-Zuyevo": "Орєхово-Зуєво",
}


# У газетирі трапляється «Gorod Solnechnogorsk» — «город» тут не частина
# назви, а тип поселення.
PREFIX_DROP = ("Gorod ", "gorod ", "Poselok ", "poselok ", "Selo ", "selo ",
               "Stanitsa ", "stanitsa ", "Derevnya ", "derevnya ")


def uk(name: str) -> str:
    if name in EXC:
        return EXC[name]
    for pre in PREFIX_DROP:
        if name.startswith(pre):
            name = name[len(pre):]
            break
        if name in EXC:
            return EXC[name]
    out = []
    for word in re.split(r"([ \-])", name):
        if word in (" ", "-") or not word:
            out.append(word)
            continue
        w = word.lower()
        tail = ""
        for _ in range(2):
            for a, b in TAILS:
                if w.endswith(a) and len(w) > len(a):
                    w, tail = w[: -len(a)], b + tail
                    break
            else:
                break
        res = ""
        i = 0
        VOW = "aeiouy"
        while i < len(w):
            for a, b in PAIRS:
                if not w.startswith(a, i):
                    continue
                # «ay/oy/ey/uy» це дифтонг лише перед приголосною або в кінці:
                # у «Krasnaya» це не «айа», а «ая». Без цієї умови виходили
                # «Краснайа Глінка», «Новайа Балахна», «Шуйа».
                if a in ("ay", "oy", "ey", "uy") and i + len(a) < len(w) \
                        and w[i + len(a)] in VOW:
                    continue
                res += b
                i += len(a)
                break
            else:
                i += 1
        # Правило дев'ятки застосовується лише до ОСНОВИ. На закінченні воно
        # ламало те, що вже правильне: «Чернівці» ставали «Чернівци»,
        # «Клинці» — «Клинци», бо «і» там стоїть саме після ц.
        fixed = []
        for i, ch in enumerate(res):
            if ch == "і" and i and fixed[-1] in NINE:
                ch = "и"
            fixed.append(ch)
        res = "".join(fixed)
        res += tail
        out.append(res[:1].upper() + res[1:])
    return "".join(out)


def main(min_pop="15000", out=None):
    out = out or os.path.join(HERE, "labels.js")
    min_pop = int(min_pop)
    BOX = (41.0, 60.5, 25.0, 53.0)
    seen, res = set(), []
    for path in ("gazetteer/RU.txt", "gazetteer/UA.txt"):
        for line in open(f"{ROOT}/{path}", encoding="utf-8"):
            f = line.split("\t")
            if len(f) < 15 or f[6] != "P" or f[7] in ("PPLX", "PPLQ", "PPLH"):
                continue
            pop = int(f[14] or 0)
            if pop < min_pop:
                continue
            la, lo = float(f[4]), float(f[5])
            if not (BOX[0] <= la <= BOX[1] and BOX[2] <= lo <= BOX[3]):
                continue
            if f[1] in DROP:          # район міста, а не місто
                continue
            name = CITY_UA.get(f[1]) or uk(f[1])
            if name in seen:
                continue
            seen.add(name)
            res.append({"n": name, "la": round(la, 3), "lo": round(lo, 3), "p": pop})
    res.sort(key=lambda c: -c["p"])
    open(out, "w", encoding="utf-8").write(
        "window.LABELS=" + json.dumps(res, ensure_ascii=False,
                                      separators=(",", ":")) + ";\n")
    print(f"підписів: {len(res)}  (від {min_pop} осіб)")
    print("приклади:", ", ".join(c["n"] for c in res[40:60]))


if __name__ == "__main__":
    main(*sys.argv[1:])
