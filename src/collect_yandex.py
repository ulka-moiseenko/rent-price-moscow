"""
Сбор объявлений о долгосрочной аренде квартир в Москве с Яндекс Недвижимости.

Программа открывает страницы каталога, берёт встроенные в страницу данные (window.INITIAL_STATE),
удаляет персональные данные и дописывает объявления в файл бронзового слоя
data/bronze/offers_<дата>.jsonl. Между запросами выдерживается пауза 6-12 секунд. Если сайт показал
проверку или вернул ошибку, сбор останавливается: защита сайта не обходится.

Сайт отдаёт не больше 25 страниц на один поиск, поэтому поиск делится на сегменты. Сегменты
используют только параметры, которые robots.txt не запрещает: число комнат и тип ремонта.
Первый сбор 25.10.2026 делил поиск ещё и по цене, такие фильтры в robots.txt нежелательны.

Запуск:
    venv\\Scripts\\python.exe src\\collect_yandex.py
Пробный запуск, по одной странице на сегмент:
    venv\\Scripts\\python.exe src\\collect_yandex.py --max-pages 1
"""

import argparse
import json
import random
import re
import time
from datetime import datetime
from pathlib import Path

import requests

from security import PersonalDataGuard

BASE_URL = "https://realty.yandex.ru/moskva/snyat/kvartira/"
BRONZE_DIR = Path(__file__).resolve().parent.parent / "data" / "bronze"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"),
    "Accept-Language": "ru-RU,ru;q=0.9",
}
ROOMS = ["STUDIO", "1", "2", "3", "PLUS_4"]
RENOVATIONS = ["EURO", "COSMETIC_DONE", "DESIGNER_RENOVATION"]
SEGMENTS = {}
for rooms in ROOMS:
    SEGMENTS[f"rooms{rooms}"] = {"roomsTotal": rooms}
    for renovation in RENOVATIONS:
        SEGMENTS[f"rooms{rooms}_{renovation}"] = {"roomsTotal": rooms, "renovation": renovation}


class Blocked(Exception):
    """Сайт показал проверку или заблокировал запрос."""


class YandexCollector:
    """Собирает объявления и сохраняет их в бронзовый слой без персональных данных."""

    def __init__(self, max_pages=25):
        self.max_pages = max_pages
        self.session = requests.Session()
        self.guard = PersonalDataGuard()

    def fetch_page(self, params, page):
        """Скачивает одну страницу каталога: (объявления, всего страниц). page считается с 0."""
        resp = self.session.get(BASE_URL, params=dict(params, page=page + 1), headers=HEADERS, timeout=30)
        if resp.status_code != 200 or "showcaptcha" in resp.url:
            raise Blocked(f"код ответа {resp.status_code}")
        resp.encoding = "utf-8"
        match = re.search(r"window\.INITIAL_STATE\s*=\s*(\{.*?\});?\s*</script>", resp.text, re.S)
        if not match:
            raise Blocked("на странице нет данных")
        offers = json.loads(match.group(1))["search"]["offers"]
        return offers.get("entities", []), offers["pager"]["totalPages"]

    def run(self):
        """Обходит все сегменты и возвращает путь к файлу бронзового слоя."""
        BRONZE_DIR.mkdir(parents=True, exist_ok=True)
        path = BRONZE_DIR / f"offers_{datetime.now():%Y-%m-%d_%H%M}.jsonl"
        seen = set()
        with open(path, "w", encoding="utf-8") as bronze:
            try:
                for name, params in SEGMENTS.items():
                    page, total = 0, 1
                    while page < min(total, self.max_pages):
                        offers, total = self.fetch_page(params, page)
                        for offer in offers:
                            if offer.get("offerId") not in seen:
                                seen.add(offer.get("offerId"))
                                bronze.write(json.dumps(self.guard.sanitize_offer(offer), ensure_ascii=False) + "\n")
                        print(f"[{name}] стр. {page + 1}: {len(offers)} объявлений, всего {len(seen)}", flush=True)
                        if not offers:
                            break
                        page += 1
                        time.sleep(random.uniform(6, 12))
            except Blocked as error:
                print(f"Сбор остановлен: {error}. Сохранено то, что уже собрано.")
        print(f"Готово: {len(seen)} объявлений, файл {path.name}")
        return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--max-pages", type=int, default=25, help="страниц на сегмент (не больше 25)")
    YandexCollector(parser.parse_args().max_pages).run()
