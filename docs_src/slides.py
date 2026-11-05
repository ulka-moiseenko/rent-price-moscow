"""Презентация к защите на шаблоне ЦДО.

Запуск:
    venv\\Scripts\\python.exe docs_src\\slides.py
"""

import copy
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Cm, Pt

PROJECT = Path(__file__).resolve().parent.parent
IMG, FIG = PROJECT / "docs_src" / "img", PROJECT / "reports" / "figures"
TEMPLATE = next(PROJECT.glob("Шаблон*.pptx"))
OUT = PROJECT / "Пояснительная записка" / "ВКР_Презентация.pptx"
BLUE, YELLOW, LIGHT, DARK = RGBColor(0x15, 0x5F, 0xB0), RGBColor(0xF0, 0xBE, 0x2C), RGBColor(0xEA, 0xF2, 0xFB), RGBColor(0x1F, 0x29, 0x37)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

prs = Presentation(TEMPLATE)
tpl = list(prs.slides)
title_group = next(s for s in tpl[2].shapes if s.shape_type == 6)._element
number = next(s for s in tpl[2].shapes if s.is_placeholder and s.placeholder_format.idx == 12)._element
layout = tpl[2].slide_layout


def new_slide(title, subtitle=None):
    slide = prs.slides.add_slide(layout)
    for ph in list(slide.placeholders):
        if ph.placeholder_format.idx == 2 and subtitle:
            ph.text_frame.text = subtitle
        else:
            ph._element.getparent().remove(ph._element)
    group = copy.deepcopy(title_group)
    slide.shapes._spTree.append(group)
    slide.shapes._spTree.append(copy.deepcopy(number))
    shape = next(s for s in slide.shapes if s.shape_type == 6)
    for child in shape.shapes:
        if child.has_text_frame and child.text_frame.text.strip():
            child.text_frame.paragraphs[0].runs[0].text = title
            child.text_frame.paragraphs[0].runs[0].font.bold = True
    if len(title) > 16:                   # рамка заголовка растягивается под длину текста
        shape.width = int(shape.width * len(title) / 16 * 1.04)
    return slide


def text(slide, x, y, w, h, lines, size=16, color=DARK, bold=False, align=None, anchor=None):
    """Текстовый блок; lines — строка или список строк."""
    box = slide.shapes.add_textbox(Cm(x), Cm(y), Cm(w), Cm(h))
    fill_text(box.text_frame, lines, size, color, bold, align, anchor)
    return box


def fill_text(frame, lines, size, color, bold=False, align=None, anchor=None):
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = Cm(0.2)
    frame.margin_top = frame.margin_bottom = Cm(0.1)
    if anchor:
        frame.vertical_anchor = anchor
    for i, line in enumerate([lines] if isinstance(lines, str) else lines):
        p = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        p.space_after = Pt(5)
        if align:
            p.alignment = align
        r = p.add_run()
        r.text = line
        r.font.size, r.font.bold = Pt(size), bold
        r.font.color.rgb = color


def card(slide, x, y, w, h, big, small, fill=LIGHT, big_color=BLUE, small_color=DARK, big_size=30):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Cm(x), Cm(y), Cm(w), Cm(h))
    shape.adjustments[0] = 0.08
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    shape.line.fill.background()
    shape.shadow.inherit = False
    frame = shape.text_frame
    frame.word_wrap = True
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    frame.margin_left = frame.margin_right = Cm(0.3)
    p = frame.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = big
    r.font.size, r.font.bold = Pt(big_size), True
    r.font.color.rgb = big_color
    if small:
        p = frame.add_paragraph()
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run()
        r.text = small
        r.font.size = Pt(14)
        r.font.color.rgb = small_color
    return shape


def picture(slide, path, x, y, w, h):
    """Рисунок целиком вписывается в область и выравнивается по её центру."""
    with Image.open(path) as im:
        ratio = im.width / im.height
    pw, ph = (w, w / ratio) if w / ratio <= h else (h * ratio, h)
    return slide.shapes.add_picture(str(path), Cm(x + (w - pw) / 2), Cm(y + (h - ph) / 2), Cm(pw), Cm(ph))


def table(slide, x, y, widths, rows, size=14, row_h=0.95):
    t = slide.shapes.add_table(len(rows), len(widths), Cm(x), Cm(y), Cm(sum(widths)), Cm(row_h * len(rows))).table
    for j, w in enumerate(widths):
        t.columns[j].width = Cm(w)
    for i, row in enumerate(rows):
        t.rows[i].height = Cm(row_h)
        for j, value in enumerate(row):
            c = t.cell(i, j)
            c.vertical_anchor = MSO_ANCHOR.MIDDLE
            c.margin_left = c.margin_right = Cm(0.15)
            c.fill.solid()
            c.fill.fore_color.rgb = BLUE if i == 0 else (LIGHT if i % 2 == 0 else WHITE)
            frame = c.text_frame
            frame.paragraphs[0].text = ""
            r = frame.paragraphs[0].add_run()
            r.text = value
            r.font.size, r.font.bold = Pt(size), i == 0
            r.font.color.rgb = WHITE if i == 0 else DARK
    return t


# 1 Титульный
first = tpl[0]
first.shapes[0].text_frame.text = "Определение стоимости арендной платы квартиры в зависимости от параметров"
first.shapes[1].text_frame.text = "Моисеенко Юлия Владимировна"
first.shapes[0].text_frame.paragraphs[0].runs[0].font.bold = True

# 2 Постановка вопроса
s = new_slide("Постановка вопроса", "За сколько сдать квартиру?")
text(s, 1.1, 5.6, 14, 1, "Параметры квартиры", 20, BLUE, True)
text(s, 1.1, 6.8, 14.5, 9, ["2 комнаты, 50 кв. м", "5 этаж из 17", "Западный округ", "Монолитный дом 2010 года", "Евроремонт", "10 минут пешком до метро"], 20)
card(s, 17, 5.6, 15.6, 4.6, "98 551 ₽", "цена аренды в месяц", BLUE, WHITE, WHITE, 44)
card(s, 17, 10.6, 7.6, 3.8, "Комфорт", "ценовой класс", LIGHT, BLUE, DARK, 28)
card(s, 25, 10.6, 7.6, 3.8, "Норма", "итог самопроверки", LIGHT, BLUE, DARK, 28)
text(s, 17, 14.8, 15.6, 2, "Система определяет цену и класс квартиры и сама проверяет результат", 16)

# 3 Цель и задачи
s = new_slide("Цель и задачи")
picture(s, IMG / "fig01_structure.png", 1.1, 3.6, 31.6, 14.1)

# 4 Источник данных
s = new_slide("Источник данных", "Живые данные и защита персональных сведений")
table(s, 1.1, 5.5, [6.2, 8.2, 5.0], [["Сайт", "Результат проверки", "Вывод"],
      ["ЦИАН", "повторный запрос заблокирован", "сбор блокируется"], ["Авито", "запрос отклонён", "сбор блокируется"],
      ["Домклик", "данные не отданы", "данные недоступны"], ["Яндекс Недвижимость", "каталог с 8 568 объявлениями", "источник выбран"]])
card(s, 21.4, 5.5, 5.5, 4.75, "8 568", "объявлений в каталоге")
card(s, 27.3, 5.5, 5.5, 4.75, "5 972", "собрано на 25.10.2026")
text(s, 1.1, 11.2, 31.6, 1, "Персональные данные", 20, BLUE, True)
text(s, 1.1, 12.3, 31.6, 4, ["Удаляются при сборе: имена, фотографии, телефоны, описания, ссылки на объявления",
                             "Заменяются псевдонимом HMAC-SHA256: адрес и номер объявления",
                             "Координаты округляются примерно до 100 м; файл уменьшился с 324 до 12 МБ"], 18)

# 5 Слои данных
s = new_slide("Слои данных")
picture(s, IMG / "fig04_layers.png", 1.1, 3.8, 31.6, 13.6)

# 6 База данных
s = new_slide("База данных")
picture(s, IMG / "fig05_database.png", 1.1, 3.6, 31.6, 12)
text(s, 1.1, 15.8, 31.6, 1.6, "Цена хранится отдельно от квартиры: при новом сборе цена выросла с 80 000 до 89 500 ₽, в истории остались оба значения", 16, BLUE, True)

# 7 Анализ и ценовые классы
s = new_slide("Анализ и ценовые классы", "Логарифм снижает асимметрию цены с 12,09 до 1,3")
picture(s, FIG / "price_distribution.png", 1.1, 5.5, 31.6, 6)
table(s, 4.6, 11.9, [4.0, 6.6, 6.0, 8.0], [["Класс", "Цена, руб. в месяц", "Объявлений в обучении", "Медианная площадь, кв. м"],
      ["Эконом", "менее 70 000", "986", "36"], ["Средний", "от 70 000 до 95 000", "917", "41"],
      ["Комфорт", "от 95 000 до 140 000", "1 035", "48"], ["Премиум", "от 140 000", "1 044", "75"]], 14, 1.05)

# 8 Сравнение моделей
s = new_slide("Сравнение моделей", "Проверка на домах, которых модель не видела при обучении")
table(s, 1.1, 5.5, [5.4, 2.4, 2.4, 2.3, 2.1], [["Модель", "MAE, руб.", "RMSE, руб.", "MAPE", "R²"],
      ["Базовая (медиана)", "43 759", "66 893", "39,3", "−0,065"], ["Линейная регрессия", "20 590", "41 465", "16,3", "0,591"],
      ["Случайный лес", "17 426", "28 459", "14,7", "0,807"], ["Градиентный бустинг", "17 353", "28 622", "14,7", "0,805"],
      ["Нейронная сеть", "17 238", "29 079", "14,2", "0,799"]], 14, 1.15)
picture(s, FIG / "models_mape.png", 16.2, 5.3, 16.6, 8)
card(s, 1.1, 13.4, 31.7, 3.5, "Выбран градиентный бустинг", "лучший результат на перекрёстной проверке: MAE логарифма 0,1488 против 0,1498 у нейросети и 0,1512 у леса", BLUE, WHITE, WHITE, 24)

# 9 Точность модели
s = new_slide("Точность модели", "Ориентир цены, а не точная оценка")
picture(s, FIG / "pred_vs_true.png", 1.1, 5.4, 15, 12)
card(s, 17, 5.5, 7.6, 3.7, "14,7", "процента: средняя ошибка MAPE")
card(s, 25.1, 5.5, 7.6, 3.7, "0,805", "коэффициент R²")
card(s, 17, 9.6, 7.6, 3.7, "11,4", "процента: ошибка половины прогнозов не больше")
card(s, 25.1, 9.6, 7.6, 3.7, "70,8", "процента: верный ценовой класс")
text(s, 17, 13.8, 15.7, 3.4, ["У 10 процентов объявлений ошибка больше 30 процентов", "Модель не видит фотографии, вид из окна и состояние квартиры"], 16)

# 10 Конвейер данных
s = new_slide("Конвейер данных")
picture(s, IMG / "fig06_pipeline.png", 1.1, 3.6, 31.6, 9.8)
card(s, 1.1, 13.7, 10.2, 3.5, "342 из 5 972", "маленький сбор отклонён, база не изменилась", LIGHT, BLUE, DARK, 24)
card(s, 11.8, 13.7, 10.2, 3.5, "154 и 42", "новых объявления и изменения цены на копии базы", LIGHT, BLUE, DARK, 24)
card(s, 22.5, 13.7, 10.2, 3.5, "7 из 7 таблиц", "совпали при восстановлении из резервной копии", LIGHT, BLUE, DARK, 24)

# 11 Самопроверка прогноза
s = new_slide("Самопроверка прогноза")
picture(s, IMG / "fig09_selfcheck.png", 1.1, 3.7, 31.6, 13.8)

# 12 Приложение
s = new_slide("Приложение")
picture(s, IMG / "fig15_interface.png", 1.1, 3.6, 18, 14.2)
text(s, 19.6, 4, 13, 1, "Пользователь указывает", 20, BLUE, True)
text(s, 19.6, 5.2, 13, 5, ["параметры квартиры и дома", "округ или удалённость от центра", "станцию метро или адрес"], 18)
text(s, 19.6, 9.8, 13, 1, "Система выдаёт", 20, BLUE, True)
text(s, 19.6, 11, 13, 6, ["цену и примерный диапазон", "ценовой класс", "итог самопроверки", "точку на карте"], 18)

# 13 Выводы
s = new_slide("Выводы", "Цель работы достигнута")
for i, line in enumerate(["Собраны живые данные, персональные сведения исключены", "Реализовано хранилище из трёх слоёв на PostgreSQL",
                          "Конвейер контролирует качество данных и модель", "Выбран бустинг: MAE 17 353 ₽, MAPE 14,7, R² 0,805",
                          "Ценовой класс верен в 70,8 процента случаев", "Прогноз проходит самопроверку, приложение и код готовы"]):
    box = card(s, 1.1, 5.5 + i * 2.0, 20.2, 1.8, line, None, LIGHT, DARK, DARK, 17)
panel = card(s, 22, 5.5, 10.8, 11.8, "Ограничения", None, YELLOW, DARK, DARK, 20)
frame = panel.text_frame
for line, size, bold in [("обычный сегмент рынка, цена предложения, рынок на дату сбора", 16, False), ("", 10, False), ("Развитие", 20, True),
                         ("полный сбор через конвейер, еженедельный запуск, описания и фотографии", 16, False)]:
    q = frame.add_paragraph()
    q.alignment = PP_ALIGN.CENTER
    r = q.add_run()
    r.text = line
    r.font.size, r.font.bold = Pt(size), bold
    r.font.color.rgb = DARK

# Порядок: титульный, новые слайды, закрывающий; образцы шаблона удаляются
ids = prs.slides._sldIdLst
items = list(ids)
closing = items[6]
for el in items[1:6]:
    prs.part.drop_rel(el.rId)
    ids.remove(el)
ids.remove(closing)
ids.append(closing)

FONT = "Arial"


def set_font(shape):
    if shape.shape_type == 6:
        for child in shape.shapes:
            set_font(child)
    if getattr(shape, "has_table", False) and shape.has_table:
        for row in shape.table.rows:
            for c in row.cells:
                for q in c.text_frame.paragraphs:
                    for r in q.runs:
                        r.font.name = FONT
    if shape.has_text_frame:
        for q in shape.text_frame.paragraphs:
            for r in q.runs:
                r.font.name = FONT


for slide in prs.slides:
    for shape in slide.shapes:
        set_font(shape)
prs.save(OUT)
print("Сохранено:", OUT.name, "слайдов:", len(prs.slides))
