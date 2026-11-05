"""Рисунки записки: файлы HTML из этой папки переводятся в PNG на белом фоне (папка docs_src/img).

Запуск:
    venv\\Scripts\\python.exe docs_src\\figures\\render.py
Один рисунок:
    venv\\Scripts\\python.exe docs_src\\figures\\render.py fig01_structure
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "img"

names = sys.argv[1:] or [p.stem for p in sorted(HERE.glob("fig*.html"))]
with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1500, "height": 900}, device_scale_factor=2)
    for name in names:
        page.goto((HERE / f"{name}.html").as_uri())
        page.wait_for_timeout(300)
        page.locator("body").screenshot(path=OUT / f"{name}.png")
        print("Сохранён:", name)
    browser.close()
