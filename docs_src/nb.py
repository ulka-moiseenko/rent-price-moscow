"""Чтение выполненных блокнотов: код и результат ячейки по её имени."""

import re
import sys
from functools import lru_cache
from pathlib import Path

import nbformat

NB_DIR = Path(__file__).resolve().parent.parent / "notebooks"
ANSI = re.compile(r"\x1b\[[0-9;]*m")


@lru_cache(maxsize=None)
def _load(name):
    path = next(NB_DIR.glob(f"{name}*.ipynb"))
    return nbformat.read(path, as_version=4)


def cell(nb, cell_name):
    """Возвращает (код, текст результата) ячейки с metadata.name == cell_name."""
    for c in _load(nb).cells:
        if c.cell_type == "code" and c.metadata.get("name") == cell_name:
            out = []
            for o in c.get("outputs", []):
                if o.output_type == "stream":
                    out.append(o.text)
                elif o.output_type in ("execute_result", "display_data"):
                    out.append(o.data.get("text/plain", ""))
                elif o.output_type == "error":
                    out.append("ОШИБКА: " + o.ename + ": " + o.evalue)
            return c.source, ANSI.sub("", "".join(out)).rstrip()
    raise KeyError(f"Нет ячейки {cell_name} в блокноте {nb}")


def add(doc, nb, cell_name, caption, output=True, intro=None):
    """Вставляет в документ листинг ячейки блокнота; intro — голубой абзац перед ним.
    В intro можно написать {n} — туда подставится номер листинга."""
    code, out = cell(nb, cell_name)
    n = getattr(doc, "listing_no", 0) + 1
    if intro:
        doc.blue(intro.format(n=n))
    return doc.listing(caption, code, out if output else None)


def add_func(doc, path, funcs, nb, cell_name, caption, intro=None):
    """Листинг «функция из программы + её вызов в блокноте» с результатом вызова."""
    code = "\n\n".join(source_of(path, f) for f in funcs)
    call, out = cell(nb, cell_name)
    n = getattr(doc, "listing_no", 0) + 1
    if intro:
        doc.blue(intro.format(n=n))
    return doc.listing(caption, f"{code}\n\n\n# Вызов в блокноте\n{call}", out)


def source_of(path, name):
    """Исходный код функции name из файла path (для листинга)."""
    import ast
    text = Path(path).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(text, node)
    raise KeyError(name)


def block_of(path, start, end, extra=0):
    """Фрагмент файла от строки, начинающейся с start, до строки с end включительно
    (и ещё extra строк после неё)."""
    import textwrap
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    i = next(k for k, l in enumerate(lines) if l.strip().startswith(start))
    j = next(k for k in range(i, len(lines)) if end in lines[k]) + extra
    return textwrap.dedent("\n".join(lines[i:j + 1]))


if __name__ == "__main__":
    # Печать всех ячеек блокнота: python nb.py 02
    for c in _load(sys.argv[1]).cells:
        if c.cell_type == "code":
            name = c.metadata.get("name")
            print(f"===== {name}")
            print(cell(sys.argv[1], name)[1][:1500])
