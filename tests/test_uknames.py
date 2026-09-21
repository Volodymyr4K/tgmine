"""Українські назви місць для підписів редактора: mapper/uknames.py.

Кожен випадок — із реальних ночей або з розбіжностей із Вікіпедією, на
яких правило й підбиралось (21 вересня 2026).
"""
import unittest

from tests.helpers import needs_gazetteer
from mapper import uknames as UN


class TestRu2Uk(unittest.TestCase):
    """Відтворення російської назви українською — запас, коли Wikidata нема."""

    def test_cases_from_nights(self):
        for ru, want in (
                # стара транслітерація латиниці давала «Самольотна», «Стариє
                # Богади», «Степнои Заи», «Воробьиьовський»
                ("Самолётная Ветелка", "Самольотна Ветелка"),
                ("Старые Богады", "Старі Богади"),
                ("Степной Зай", "Степний Зай"),
                ("Воробьёвский район", "Воробйовський район"),
                ("Большие Козлы", "Великі Козли"),
                ("Нижнекамск", "Нижньокамськ"),
                ("Шебекино", "Шебекіно"),
                ("Жирятино", "Жирятино"),         # після т «и» лишається
                ("Валуйки", "Валуйки"),           # «ки» теж
                ("Елец", "Єлець"),
                ("Тверь", "Твер"),
                ("Сочи", "Сочі"),
                ("Щёкино", "Щокіно"),
                ("Новый Уренгой", "Новий Уренгой"),  # «-гой» — не прикметник
                ("Ачхой-Мартан", "Ачхой-Мартан"), ("Металлострой", "Металлострой"),
                ("Сухой Лог", "Сухий Лог"), ("Чусовой", "Чусовий"),
                ("Дмитровский район", "Дмитровський район"), ("Мирный", "Мирний"),
                ("Маломихайловка", "Маломихайловка"), ("Защитное", "Защитне"),
                ("Приазовский район", "Приазовський район"),
                ("Юрьев-Польский", "Юрʼєв-Польський"),
                # «-ье»: прикметник, губна, подвоєння, іменник із префіксом
                ("Лебяжье", "Лебяже"), ("Верховье", "Верховʼя"),
                ("Раздолье", "Раздолля"), ("Заволжье", "Заволжжя"),
                ("Новоивановское", "Новоівановське"), ("Строитель", "Строїтель"),
                ("Васильевка", "Васильєвка")):
            with self.subTest(ru=ru):
                self.assertEqual(UN.ru2uk(ru), want)

    def test_ukraine_endings(self):
        """Для України — офіційні українські закінчення й «и» без «правила
        девʼятки» («Житомир», а не «Житомір»)."""
        for ru, want in (("Родниково", "Родникове"), ("Чистяково", "Чистякове"),
                         ("Поповка", "Попівка"), ("Житомир", "Житомир"),
                         ("Наташино", "Наташине"), ("Витино", "Витине")):
            with self.subTest(ru=ru):
                self.assertEqual(UN.ru2uk_ua(ru), want)


class TestPick(unittest.TestCase):
    """Вибір кириличної альт-назви, з якої зроблено латиницю запису."""

    def test_russian_name(self):
        for latin, alts, want in (
                ("Kolomna", ["Коломьна", "Коломна"], "Коломна"),
                ("Kireyevsk", ["Кирејевск", "Киреевск"], "Киреевск"),       # сербська ј
                ("Belaya Berëzka", ["Белая-Березка", "Белая Березка"], "Белая Берёзка"),
                ("Tokaryovka", ["Токаревка"], "Токарёвка"),                 # «yo» -> ё
                ("Venëv", ["Венев"], "Венёв")):
            with self.subTest(latin=latin):
                self.assertEqual(UN.pick_ru(latin, alts), want)

    def test_bashkir_and_latin_alts_are_not_russian(self):
        self.assertIsNone(UN.pick_ru("Kurman Raion", ["Ҡурман районы", "Kurman"]))

    def test_ukrainian_name(self):
        # білоруське «і» після голосної — це «ї»
        self.assertEqual(UN.pick_uk("Hornostayivka", ["Горностаевка", "Горностаівка"]),
                         "Горностаївка")
        self.assertEqual(UN.pick_uk("Kyiv", ["Киев", "Киів"]), "Київ")
        # білоруська форма з аканням не проходить поріг
        self.assertIsNone(UN.pick_uk("Myrnohrad", ["Мірнаград", "Мирноград"]))


class TestKmu(unittest.TestCase):
    """Українська латиниця GeoNames назад — для України без української альт-назви."""

    def test_cases(self):
        for latin, want in (("Yakymivka Raion", "Якимівка район"),
                            ("Bilovods'k", "Біловодськ"),
                            ("Kamyanka-Dniprovska", "Камʼянка-Дніпровська"),
                            ("Novoaidar", "Новоайдар"),
                            ("Novyi Hai", "Новий Гай"),
                            ("Myropillia", "Миропілля"),
                            ("Hvardiyske", "Гвардійське"),
                            ("Kadiyivka", "Кадіївка"),
                            ("Mykolaivka", "Миколаївка"),
                            ("Mykhaylivka", "Михайлівка"),
                            ("Rybach'e", "Рибаче")):
            with self.subTest(latin=latin):
                self.assertEqual(UN.kmu2uk(latin), want)

    def test_russian_latin_in_ukraine_goes_through_russian(self):
        """«Olenevka» (Крим) — латиниця російська, тож джерело — російська
        альт-назва, а не КМУ («Оленевка»)."""
        self.assertEqual(UN.name_of("Olenevka", "UA", ["Оленевка", "Караджи"]), "Оленівка")
        # українська латиниця, російська назва інша — КМУ
        self.assertEqual(UN.name_of("Yakymivka Raion", "UA", ["Акимовский район"]),
                         "Якимівка район")


class TestWikidataGuard(unittest.TestCase):
    """Мітка Wikidata — лише коли це назва того ж місця, як його пишуть канали."""

    def test_rejected(self):
        for label, latin, fb in (
                ("Катирлез", "Voykovo", "Войкове"),                  # перейменування
                ("Тархани", "Lermontovo", "Лермонтово"),
                ("Музей-садиба Архангельське", "Arkhangel’skoye", "Архангельське"),
                ("Клинський район", "Gorodskoy Okrug Klin", "міський округ Клин"),
                ("Харківська міська рада", "Kharkiv Raion", "Харків район"),
                ("Зеленоградський адміністративний округ", "Zelenograd", "Zelenograd"),
                # вид адмінодиниці: старий район для міського округу
                ("Ленінський район", "Leninskiy Gorodskoy Okrug", "Ленинський міський округ"),
                # район, названий без родового слова
                ("Кромський", "Kromskoy Rayon", "Кромський район"),
                # місто замість однойменного селища
                ("Льгов", "L’govskiy", "Льговський")):
            with self.subTest(label=label):
                self.assertFalse(UN._wd_ok(label, latin, fb))

    def test_accepted(self):
        for label, latin, fb in (
                ("Великі Козли", "Bol’shiye Kozly", "Великі Козли"),
                ("Ульяновський район", "Ulyanovskiy Rayon", "Ульяновський район"),
                ("Озьорський міський округ", "Ozyory Urban Okrug", "Озьори міський округ"),
                ("Підгірне", "Podgornoye", "Подгорне")):
            with self.subTest(label=label):
                self.assertTrue(UN._wd_ok(label, latin, fb))


class TestNameOf(unittest.TestCase):
    def test_order_of_sources(self):
        # ручний словник — понад Wikidata
        self.assertEqual(UN.name_of("Moscow", "RU", [], [], ["Москва (місто)"]), "Москва")
        # Wikidata — понад відтворення
        self.assertEqual(UN.name_of("Velyki Kopani", "UA", ["Великие Копани"], [],
                                    ["Великі Копані"]), "Великі Копані")
        # аліаси конфігу — у називному й українською
        self.assertEqual(UN.name_of("Фиолента"), "мис Фіолент")
        self.assertEqual(UN.name_of("Бухты Казачья"), "Козача бухта")

    def test_settlement_type_prefix_and_unit_case(self):
        self.assertEqual(UN.name_of("Gorod Staryye Bogady", "RU", ["Город Старые Богады"]),
                         "Старі Богади")
        self.assertEqual(UN.name_of("Henichesk Raion", "UA", ["Генічеський Район"]),
                         "Генічеський район")


class TestCriticalReview(unittest.TestCase):
    """Знахідки критичної перевірки 22 вересня 2026 на всьому сховищі."""

    def test_single_russian_alt_must_resemble(self):
        # єдина альт-назва «Цветовка» — інше село
        self.assertEqual(UN.name_of("Zaytseva Gora", "RU", ["Цветовка"]), "Зайцева Гора")
        # англійський екзонім, а російська назва та сама
        self.assertEqual(UN.name_of("Oryol District", "RU", ["Орловский район"]),
                         "Орловський район")

    def test_ukrainian_form_is_not_a_russian_candidate(self):
        alts = ["Kudajgul", "Vorob'jovo", "Воробйове", "Воробьёво", "Кудайгу́л"]
        self.assertEqual(UN.name_of("Vorobyovo", "UA", alts), "Воробйове")

    def test_unit_kind_from_latin(self):
        self.assertEqual(UN.name_of("Kulebaksky Urban Okrug", "RU", ["Кулебакский район"]),
                         "Кулебакський міський округ")

    def test_neuter_vs_masculine(self):
        self.assertEqual(UN.name_of("Bol’shoye", "RU", ["Большое", "Большой"]), "Велике")

    def test_tract_prefix_and_acronym(self):
        self.assertEqual(UN.name_of("Urochishche Zarya", "RU", ["Урочище Заря"]), "Заря")
        self.assertEqual(UN.name_of("Rayon KTZ", "UA", ["Район ХТЗ"]), "район ХТЗ")

    def test_wikidata_other_district_rejected(self):
        # спільне «район» не робить Ломоносовський Петродворцовим
        self.assertEqual(UN.name_of("Petrodvortsovyy Rayon", "RU",
                                    ["Ломоносовский Район", "Петродворцовый Район"], [],
                                    ["Ломоносовський район"]), "Петродворцовий район")

    def test_ukraine_renamed_districts(self):
        """Wikidata тримає назви до перейменування 2024; латиниця GeoNames і
        українська альт-назва — нові."""
        self.assertEqual(UN.name_of("Kurman Raion", "UA",
                                    ["Красногвардейский район", "Курманський район"], [],
                                    ["Красногвардійський район"]), "Курманський район")
        self.assertEqual(UN.name_of("Perekop Raion", "UA",
                                    ["Красноперекопский район", "Перекопський район"], [],
                                    ["Красноперекопський район"]), "Перекопський район")

    def test_rename_known_to_wikidata_wins(self):
        """Wikidata знає латиницю як стару назву (псевдонім) — мітка новіша."""
        self.assertEqual(UN.name_of("Nikol's’ke", "UA", ["Нікольське", "Никольское"], [],
                                    ["Микільське"], ["Нікольське", "Володарське"]),
                         "Микільське")
        self.assertEqual(UN.name_of("Leninskiy Rayon", "UA", [], [],
                                    ["Шевченківський район"], ["Ленінський район"]),
                         "Шевченківський район")

    def test_apostrophe_after_labial(self):
        # мітка Wikidata без апострофа, відтворення російської — теж
        self.assertEqual(UN.name_of("Bilmak", "UA", ["Більмак"], [], ["Камянка"], ["Більмак"]),
                         "Камʼянка")
        self.assertEqual(UN.name_of("Dal’nyaya Polubyanka", "RU", ["Дальняя Полубянка"]),
                         "Дальня Полубʼянка")
        # «є» — конвенція, апостроф не ставиться
        self.assertEqual(UN.name_of("Blagoveshchensk", "RU", [], [], ["Благовєщенськ"]),
                         "Благовєщенськ")

    def test_russian_regions_in_editor_style(self):
        for latin, want in (("Vologda Oblast", "Вологодська обл."),
                            ("North Ossetia-Alania", "Північна Осетія"),
                            ("Respublika Adygeya", "Адигея"),
                            ("Chuvashskaya Respublika", "Чувашія")):
            with self.subTest(latin=latin):
                self.assertEqual(UN.name_of(latin, "RU", ["Вологодская область"]), want)


@needs_gazetteer
class TestNamesFromGazetteer(unittest.TestCase):
    """Місце події — за назвою й координатою запису GeoNames."""

    def test_place_by_name_and_coordinate(self):
        nm = UN.Names([("Kamyanka-Dniprovska", 47.49629, 34.41026),
                       ("Samolëtnaya Vetelka", 49.9558, 48.7435)])
        self.assertEqual(nm.place("Kamyanka-Dniprovska", 47.49629, 34.41026),
                         "Камʼянка-Дніпровська")
        self.assertEqual(nm.place("Samolëtnaya Vetelka", 49.9558, 48.7435),
                         "Самольотна Ветелка")

    def test_unknown_coordinate_falls_back_without_record(self):
        nm = UN.Names([("Kamyanka-Dniprovska", 47.49629, 34.41026)])
        # тезку за 300 км не підмінюємо чужим записом
        self.assertEqual(nm.place("Kamyanka-Dniprovska", 50.0, 36.0),
                         UN.name_of("Kamyanka-Dniprovska"))


if __name__ == "__main__":
    unittest.main()
