#!/usr/bin/env python3
"""Підписи населених пунктів: українська назва і англійська поруч.

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
import unicodedata

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
    "Zaporizhzhya": "Запоріжжя",
    # Правило зʼїдає мʼякий знак: «Lviv» давало «Лвів». Місто, яке оператор
    # назвав серед пʼяти обовʼязкових, стояло на карті з помилкою в назві.
    "Lviv": "Львів", "Tolyatti": "Тольятті",
    "Ulyanovsk": "Ульяновськ", "Yaroslavl": "Ярославль",
    "Kryvyy Rih": "Кривий Ріг", "Sevastopol": "Севастополь",
    "Ryazan’": "Рязань", "Astrakhan": "Астрахань", "Penza": "Пенза",
    "Lipetsk": "Липецьк", "Cheboksary": "Чебоксари", "Tula": "Тула",
    "Mykolayiv": "Миколаїв", "Kursk": "Курськ", "Stavropol": "Ставрополь",
    "Vinnytsya": "Вінниця", "Bryansk": "Брянськ", "Tver": "Твер",
    # Урал і Західний Сибір (рамку розширено 10 вересня 2026). Правило
    # транслітерує з англійського запису GeoNames і губить «й» та мʼякий
    # знак: «Tyumen» давало «Тюмен», «Novy Urengoy» — «Новий Уренгои»,
    # «Nizhny Tagil» — «Ніжни Тагіл». Перелічено все від 40 тис. осіб.
    "Tyumen": "Тюмень", "Nizhny Tagil": "Нижній Тагіл",
    "Nizhnevartovsk": "Нижньовартовськ", "Novyy Urengoy": "Новий Уренгой",
    "Tobolsk": "Тобольськ", "Pervouralsk": "Первоуральськ",
    "Kopeysk": "Копейськ", "Nyagan": "Нягань", "Uray": "Урай",
    "Sibay": "Сибай", "Gay": "Гай", "Polevskoy": "Полевський",
    "Lesnoy": "Лісний", "Strezhevoy": "Стрежевой", "Pyt-Yakh": "Пить-Ях",
    "Verkhnyaya Pyshma": "Верхня Пишма", "Raduzhny": "Радужний",
    "Nizhnyaya Tura": "Нижня Тура", "Nizhnyaya Salda": "Нижня Салда",
    "Nizhniye Sergi": "Нижні Серги", "Sukhoy Log": "Сухий Лог",
    "Verkhny Ufaley": "Верхній Уфалей", "Kataysk": "Катайськ",
    "Sredneuralsk": "Середньоуральськ", "Novotroitsk": "Новотроїцьк",
    "Troitsk": "Троїцьк", "Beloretsk": "Білорецьк", "Bely Yar": "Білий Яр",
    "Beryozovsky": "Березовський", "Artemovsky": "Артемівський",
    "Kamen’-na-Obi": "Камінь-на-Обі", "Verkhnyaya Salda": "Верхня Салда",
    "Ivanovo": "Іваново", "Luhansk": "Луганськ", "Vladimir": "Владимир",
    "Starobilsk": "Старобільськ",
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


# Англійський підпис. Латиниця в газетирі вже є — саме з неї й будується
# українська назва, тож англійська версія карти не потребує ані нового
# джерела, ані перекладу: береться те саме поле `name`.
#
# Що з ним усе-таки роблять. По-перше, розкладають діакритику й прибирають
# мʼякий знак-апостроф: «Orël» і «Ryazan’» на карті мають бути «Orel» і
# «Ryazan». По-друге, словник винятків нижче — там, де GeoNames тримає
# застарілу або нестандартну латинку («Zaporizhzhya» замість офіційного
# «Zaporizhzhia», «Nizhniy Novgorod» замість узвичаєного «Nizhny Novgorod»).
# Дрібні НП лишаються як у газетирі: помилка в підписі райцентру коштує
# менше, ніж механічне правило, що зіпсує сусідні правильні назви.
CITY_EN = {
    "Nizhniy Novgorod": "Nizhny Novgorod", "Orël": "Oryol",
    "Naberezhnyye Chelny": "Naberezhnye Chelny",
    "Zheleznodorozhnyy": "Zheleznodorozhny",
    "Zaporizhzhya": "Zaporizhzhia", "Kryvyy Rih": "Kryvyi Rih",
    "Mykolayiv": "Mykolaiv", "Vinnytsya": "Vinnytsia",
    "Makiyivka": "Makiivka", "Kamyanske": "Kamianske",
    "Slovyansk": "Sloviansk", "Siverskodonetsk": "Sievierodonetsk",
    "Izmayil": "Izmail", "Yenakiyeve": "Yenakiieve",
    "Ilovays’k": "Ilovaisk", "Mohyliv-Podilskyy": "Mohyliv-Podilskyi",
    "Novoukrayinka": "Novoukrainka", "Chuhuyiv": "Chuhuiv",
    "Avdiyivka": "Avdiivka", "Dokuchayevsk": "Dokuchaievsk",
    "Kadiyivka": "Kadiivka", "Dzhankoy": "Dzhankoi",
    "Bakhchysaray": "Bakhchysarai", "Pervomaysk": "Pervomaisk",
    "Yevpatoriya": "Yevpatoriia", "Feodosiya": "Feodosiia",
    "Oleksandriya": "Oleksandriia", "Berdyansk": "Berdiansk",
    "Kupyansk": "Kupiansk", "Izyum": "Izium",
}


def en(name: str) -> str:
    """Латиниця газетира, придатна до друку: без діакритики й апострофів."""
    if name in CITY_EN:
        return CITY_EN[name]
    out = unicodedata.normalize("NFKD", name)
    out = "".join(c for c in out if not unicodedata.combining(c))
    out = out.replace("’", "").replace("ʼ", "").replace("'", "").strip()
    # Кінцеве -yy/-iy на англійських картах пишуть одним «y»: «Staryy Oskol»
    # це запис системи BGN, а очима читається як помилка набору. Українських
    # назв правило не чіпає: там кінцівка -yi («Khmelnytskyi»).
    return re.sub(r"(?:yy|iy)\b", "y", out)


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
TAILS = [("skiy", "ський"), ("skyy", "ський"), ("skoy", "ський"), ("sky", "ський"),
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
# Області України — таблицею, а не транслітом. Транслітерація англійської
# назви GeoNames давала «Одеска Област», «Миколаиів Област»: доки області
# майже не траплялись серед місць подій, цього не було видно, а відколи пуск
# стоїть на ДЖЕРЕЛІ, «пуски від Одеської області» — найчастіший його вид.
# Назви — точно ті, що лежать у gazetteer/UA.txt (ADM1).
UA_OBLAST = {
    "Autonomous Republic of Crimea": "АР Крим", "Cherkasy Oblast": "Черкаська обл.",
    "Chernihiv Oblast": "Чернігівська обл.", "Chernivtsi Oblast": "Чернівецька обл.",
    "Dnipropetrovsk Oblast": "Дніпропетровська обл.", "Donetska Oblast": "Донецька обл.",
    "Ivano-Frankivsk Oblast": "Івано-Франківська обл.", "Kharkiv Oblast": "Харківська обл.",
    "Kherson Oblast": "Херсонська обл.", "Khmelnytskyi Oblast": "Хмельницька обл.",
    "Kirovohrad Oblast": "Кіровоградська обл.", "Kyiv Oblast": "Київська обл.",
    "Luhanska Oblast": "Луганська обл.", "Lvivska Oblast": "Львівська обл.",
    "Misto Kyiv": "Київ", "Mykolayiv Oblast": "Миколаївська обл.",
    "Odeska Oblast": "Одеська обл.", "Poltava Oblast": "Полтавська обл.",
    "Rivne Oblast": "Рівненська обл.", "Sebastopol City": "Севастополь",
    "Sumska Oblast": "Сумська обл.", "Ternopil Oblast": "Тернопільська обл.",
    "Vinnytsya Oblast": "Вінницька обл.", "Volynska Oblast": "Волинська обл.",
    "Zakarpattia Oblast": "Закарпатська обл.", "Zaporizhzhya Oblast": "Запорізька обл.",
    "Zhytomyr Oblast": "Житомирська обл.",
}

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


# Родові слова адмінодиниць GeoNames — перекладом, а не транслітом.
# Транслітом «Chernsky District» ставав «Чернський Дистрицт», «Gorodskoy Okrug
# Chekhov» — «Городскои Округ Чехов». Доки районів у підписах було мало й
# майже всі звались «…skiy Rayon», це ховалось; 21 вересня 2026 газетир почав
# бачити райони з наголосами в назві, і в ночі редактора «Дистрицт» став
# звичайним (заміряно на шести ночах: 2–7 підписів за ніч).
UNIT_UK = {"district": "район", "rayon": "район", "raion": "район",
           "rajon": "район", "okrug": "округ", "gorodskoy": "міський",
           "urban": "міський", "municipal": "муніципальний",
           "munitsipal’nyy": "муніципальний", "oblast": "обл."}


def uk(name: str) -> str:
    # Кирилична назва вже для читача: так приходять аліаси конфігу
    # («Бельбек», «Фиолент»). Трансліт знає лише латиницю, і з кирилиці
    # виходив ПОРОЖНІЙ рядок — місце в редакторі стояло без підпису.
    if re.search(r"[а-яёіїєґ]", name, re.I):
        return name
    if name in UA_OBLAST:
        return UA_OBLAST[name]
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
        if word.lower() in UNIT_UK:
            out.append(UNIT_UK[word.lower()])
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


# 12000, а не 15000: саме з цим порогом зібрано labels.js у репозиторії
# (977 підписів). Стояло 15000, і перезбірка «без параметрів» мовчки
# викидала 164 назви — файл ставав меншим, а причина не видно ніде.
def main(min_pop="12000", out=None):
    out = out or os.path.join(HERE, "labels.js")
    min_pop = int(min_pop)
    # Західна межа 22.0, а не 25.0. Стояло 25 — і з карти випадав УВЕСЬ
    # захід України: Львів (717 тис.), Івано-Франківськ, Ужгород. Оператор
    # назвав Львів серед пʼяти міст, які мають бути на карті завжди, а його
    # у файлі не було взагалі — не «не влізав у ліміт», а не існував.
    # Дані ті самі, gazetteer/UA.txt, лише вікно ширше.
    # Східна межа 82.0 з 10 вересня 2026: підкладку розширено на Урал і
    # Західний Сибір (Єкатеринбург 60.6°, Омськ 73.3°, Новий Уренгой 76.6°).
    # Кадр за замовчуванням лишається європейським, оператор тягне карту
    # на схід, коли ніч уральська — таких 42 доби зі 145.
    BOX = (41.0, 70.0, 22.0, 82.0)
    seen, res = {}, []
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
            # При збігу назв лишається БІЛЬШЕ місто, а не те, що трапилось
            # першим. RU.txt читається перед UA.txt, і через це український
            # Донецьк (905 тис.) відкидався як дубль: ім'я вже займав
            # однойменний райцентр Ростовської області на 50 тисяч. На карті
            # це виглядало як «Донецьк» посеред Росії, а справжнього не було
            # взагалі — і жодного попередження ніде.
            old = seen.get(name)
            if old is not None and res[old]["p"] >= pop:
                continue
            if old is not None:
                res[old] = None
            # `e` — той самий пункт англійською. Ключем скрізь лишається `n`:
            # прибрані оператором назви й памʼять розкладки прив'язані до
            # української назви, тож перемикання мови їх не губить.
            seen[name] = len(res)
            res.append({"n": name, "e": en(f[1]), "la": round(la, 3),
                        "lo": round(lo, 3), "p": pop})
    res = [c for c in res if c]
    res.sort(key=lambda c: -c["p"])
    open(out, "w", encoding="utf-8").write(
        "window.LABELS=" + json.dumps(res, ensure_ascii=False,
                                      separators=(",", ":")) + ";\n")
    print(f"підписів: {len(res)}  (від {min_pop} осіб)")
    print("приклади:", ", ".join(c["n"] for c in res[40:60]))


if __name__ == "__main__":
    main(*sys.argv[1:])
