"""
Оформление Word-документов по требованиям к ВКР ЦДО МГТУ им. Н.Э. Баумана:
- поля: левое 30 мм, правое 10 мм, верхнее 20 мм, нижнее 15 мм;
- Times New Roman 14, чёрный, межстрочный интервал 1,5, абзацный отступ 1,25 см,
  без интервалов между абзацами, автоматические переносы;
- заголовок раздела: по центру, полужирный, 16 пт, с новой страницы, 15 пт до и после;
- заголовок подраздела: с абзацного отступа, полужирный, 14 пт, 15 пт до и после;
- номер страницы внизу по центру, Times New Roman 14;
- «Таблица N – Название» над таблицей слева, «Рисунок N – Название» под рисунком по центру.

Текст-описание наших действий (от первого лица) выделяется голубым
(цвет выделения текста в Word), чтобы потом его было легко найти и доработать.
Сам шрифт остаётся чёрным — после снятия выделения текст соответствует требованиям.
"""

import re
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_COLOR_INDEX, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Mm, Pt, RGBColor

FONT = "Times New Roman"
BLUE = WD_COLOR_INDEX.TURQUOISE  # в русском Word этот цвет выделения называется «Бирюзовый»

OUT_DIR = Path(__file__).resolve().parent.parent / "Пояснительная записка"


def _set_font(run_or_style, size=14, bold=False):
    font = run_or_style.font
    font.name = FONT
    font.size = Pt(size)
    font.bold = bold
    font.italic = False
    font.color.rgb = RGBColor(0, 0, 0)
    # Чтобы кириллица тоже была в Times New Roman
    rpr = run_or_style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(attr), FONT)
    # Стили заголовков ссылаются на шрифт темы (Calibri Light) — убираем эти ссылки
    for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:cstheme", "w:eastAsiaTheme"):
        rfonts.attrib.pop(qn(attr), None)


def plural(n, one, few, many):
    """Согласование слова с числом: plural(24, 'процент', 'процента', 'процентов')."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


class VkrDocument:
    def __init__(self):
        self.doc = Document()
        self.table_no = 0
        self.figure_no = 0
        self._setup_page()
        self._setup_styles()
        self._add_page_numbers()
        self._enable_hyphenation()
        # Убираем пустой абзац, который python-docx создаёт по умолчанию
        body = self.doc.element.body
        for p in body.findall(qn("w:p")):
            body.remove(p)

    # ---------- настройка документа ----------
    def _setup_page(self):
        s = self.doc.sections[0]
        s.page_width, s.page_height = Mm(210), Mm(297)
        s.left_margin, s.right_margin = Mm(30), Mm(10)
        s.top_margin, s.bottom_margin = Mm(20), Mm(15)
        s.footer_distance = Mm(7)

    def _setup_styles(self):
        st = self.doc.styles
        normal = st["Normal"]
        _set_font(normal)
        pf = normal.paragraph_format
        pf.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
        pf.first_line_indent = Cm(1.25)
        pf.space_before = pf.space_after = Pt(0)
        pf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        pf.widow_control = True

        h1 = st["Heading 1"]
        _set_font(h1, size=16, bold=True)
        f = h1.paragraph_format
        f.alignment = WD_ALIGN_PARAGRAPH.CENTER
        f.first_line_indent = Cm(0)
        f.space_before = f.space_after = Pt(15)
        f.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
        f.page_break_before = True
        f.keep_with_next = True

        h2 = st["Heading 2"]
        _set_font(h2, size=14, bold=True)
        f = h2.paragraph_format
        f.alignment = WD_ALIGN_PARAGRAPH.LEFT
        f.first_line_indent = Cm(1.25)
        f.space_before = f.space_after = Pt(15)
        f.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
        f.keep_with_next = True

        # Запрет переносов в заголовках
        for h in (h1, h2):
            ppr = h.element.get_or_add_pPr()
            sup = OxmlElement("w:suppressAutoHyphens")
            ppr.append(sup)

    def _add_page_numbers(self, section=None):
        footer = (section or self.doc.sections[0]).footer
        p = footer.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.first_line_indent = Cm(0)
        run = p.add_run()
        _set_font(run)
        for tag, text in (("begin", None), (None, "PAGE"), ("end", None)):
            if tag:
                el = OxmlElement("w:fldChar")
                el.set(qn("w:fldCharType"), tag)
            else:
                el = OxmlElement("w:instrText")
                el.set(qn("xml:space"), "preserve")
                el.text = text
            run._r.append(el)

    def _enable_hyphenation(self):
        settings = self.doc.settings.element
        auto = OxmlElement("w:autoHyphenation")
        auto.set(qn("w:val"), "true")
        settings.append(auto)

    # ---------- содержимое ----------
    def heading1(self, text, new_page=True):
        p = self.doc.add_paragraph(text, style="Heading 1")
        p.paragraph_format.page_break_before = new_page
        return p

    def heading2(self, text):
        return self.doc.add_paragraph(text, style="Heading 2")

    def para(self, text, blue=False):
        """Обычный абзац. blue=True — описание действий, выделено голубым."""
        p = self.doc.add_paragraph()
        run = p.add_run(text)
        _set_font(run)
        if blue:
            run.font.highlight_color = BLUE
        return p

    def blue(self, text):
        return self.para(text, blue=True)

    def items(self, lines, blue=False):
        """Перечисление через дефис: каждый пункт — отдельный абзац.
        Пункты пишутся со строчной буквы, в конце «;», у последнего «.»."""
        for i, line in enumerate(lines):
            end = "." if i == len(lines) - 1 else ";"
            self.para(f"- {line}{end}", blue=blue)

    def table(self, caption, header, rows, widths_cm=None, font_size=12):
        """Таблица с подписью «Таблица N – Название» слева над таблицей."""
        self.table_no += 1
        cap = self.doc.add_paragraph()
        cap.paragraph_format.first_line_indent = Cm(0)
        cap.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
        cap.paragraph_format.keep_with_next = True
        _set_font(cap.add_run(f"Таблица {self.table_no} – {caption}"))

        t = self.doc.add_table(rows=1 + len(rows), cols=len(header))
        t.style = "Table Grid"
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        for r_i, values in enumerate([header] + rows):
            for c_i, value in enumerate(values):
                cell = t.cell(r_i, c_i)
                cell.text = ""
                p = cell.paragraphs[0]
                pf = p.paragraph_format
                pf.first_line_indent = Cm(0)
                pf.line_spacing_rule = WD_LINE_SPACING.SINGLE
                pf.alignment = (WD_ALIGN_PARAGRAPH.CENTER if r_i == 0
                                else WD_ALIGN_PARAGRAPH.LEFT)
                _set_font(p.add_run(str(value)), size=font_size)
                if widths_cm:
                    cell.width = Cm(widths_cm[c_i])
        # Пустая строка после таблицы
        self.doc.add_paragraph()
        return t

    def _code_lines(self, text, fill):
        """Блок моноширинного текста: каждая строка — отдельный абзац с серой заливкой."""
        lines = re.sub(r"\n\s*\n(\s*\n)+", "\n\n", text.rstrip("\n")).split("\n")
        for i, line in enumerate(lines):
            p = self.doc.add_paragraph()
            pf = p.paragraph_format
            pf.first_line_indent = Cm(0)
            pf.alignment = WD_ALIGN_PARAGRAPH.LEFT
            pf.line_spacing_rule = WD_LINE_SPACING.SINGLE
            pf.keep_with_next = i < len(lines) - 1 and len(lines) <= 40
            ppr = p._p.get_or_add_pPr()
            shd = OxmlElement("w:shd")
            shd.set(qn("w:val"), "clear")
            shd.set(qn("w:color"), "auto")
            shd.set(qn("w:fill"), fill)
            ppr.append(shd)
            ppr.append(OxmlElement("w:suppressAutoHyphens"))  # без переносов внутри кода
            run = p.add_run(line if line else " ")
            _set_font(run, size=9)
            run.font.name = "Courier New"
            rfonts = run.element.get_or_add_rPr().find(qn("w:rFonts"))
            for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
                rfonts.set(qn(attr), "Courier New")

    def listing(self, caption, code, output=None, label=None):
        """Листинг кода: подпись «Листинг N – Название», код и (если есть) результат.
        label — готовый номер (например, «А.3» для приложения)."""
        self.listing_no = getattr(self, "listing_no", 0) + 1
        cap = self.doc.add_paragraph()
        cap.paragraph_format.first_line_indent = Cm(0)
        cap.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
        cap.paragraph_format.keep_with_next = True
        _set_font(cap.add_run(f"Листинг {label or self.listing_no} – {caption}"))
        self._code_lines(code, "F2F2F2")
        if output:
            label = self.doc.add_paragraph()
            label.paragraph_format.first_line_indent = Cm(0)
            label.paragraph_format.keep_with_next = True
            label.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
            _set_font(label.add_run("Результат выполнения:"), size=11)
            self._code_lines(output, "E6EEF7")
        self.doc.add_paragraph()
        return self.listing_no

    def formula(self, text, where=None):
        """Формула по требованиям: отдельная строка с абзацного отступа, пустые строки
        до и после, номер в круглых скобках у правого края; ниже — пояснения,
        первая строка начинается со слова «где» без абзацного отступа."""
        from docx.enum.text import WD_TAB_ALIGNMENT
        self.formula_no = getattr(self, "formula_no", 0) + 1
        if self.doc.paragraphs[-1].text.strip():  # после предыдущей формулы пустая строка уже есть
            self.doc.add_paragraph()
        p = self.doc.add_paragraph()
        p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.tab_stops.add_tab_stop(Cm(17), WD_TAB_ALIGNMENT.RIGHT)
        _set_font(p.add_run(f"{text}\t({self.formula_no})"))
        if where:
            for i, line in enumerate(where):
                w = self.doc.add_paragraph()
                w.paragraph_format.first_line_indent = Cm(0)
                w.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
                end = "." if i == len(where) - 1 else ";"
                _set_font(w.add_run(("где " if i == 0 else "") + (line.rstrip(".") if i == len(where) - 1 else line) + end))
        self.doc.add_paragraph()
        return self.formula_no

    def figure(self, image_path, caption, width_cm=15):
        """Рисунок по центру и подпись «Рисунок N – Название» под ним."""
        self.figure_no += 1
        p = self.doc.add_paragraph()
        p.paragraph_format.first_line_indent = Cm(0)
        p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.keep_with_next = True
        p.add_run().add_picture(str(image_path), width=Cm(width_cm))
        cap = self.doc.add_paragraph()
        cap.paragraph_format.first_line_indent = Cm(0)
        cap.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _set_font(cap.add_run(f"Рисунок {self.figure_no} – {caption}"))
        self.doc.add_paragraph()
        return self.figure_no

    def save(self, filename):
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / filename
        self.doc.save(path)
        print("Сохранено:", path)
        return path
