"""
Определение административного округа Москвы по координатам.

На сайте округ заполнен только у Новой Москвы и области, поэтому он вычисляется по границам
округов из OpenStreetMap (данные © участники OpenStreetMap, лицензия ODbL). Границы один раз
скачиваются в файл data/reference/okrugs.geojson и дальше используются без интернета.

Загрузка границ:
    venv\\Scripts\\python.exe src\\geo.py
"""

import json
import time
from pathlib import Path

import numpy as np
import requests
from matplotlib.path import Path as Polygon

PROJECT_DIR = Path(__file__).resolve().parent.parent
GEOJSON = PROJECT_DIR / "data" / "reference" / "okrugs.geojson"
URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "VKR-rent-price-moscow/1.0"}
OKRUGS = {
    "ЦАО": "Центральный административный округ", "САО": "Северный административный округ",
    "СВАО": "Северо-Восточный административный округ", "ВАО": "Восточный административный округ",
    "ЮВАО": "Юго-Восточный административный округ", "ЮАО": "Южный административный округ",
    "ЮЗАО": "Юго-Западный административный округ", "ЗАО": "Западный административный округ",
    "СЗАО": "Северо-Западный административный округ", "ЗелАО": "Зеленоградский административный округ",
    "НАО": "Новомосковский административный округ", "ТАО": "Троицкий административный округ",
}


def download():
    """Скачивает границы 12 округов (по одному запросу в секунду, по правилам службы)."""
    features = {}
    for short, full in OKRUGS.items():
        resp = requests.get(URL, params={"q": f"{full}, Москва", "format": "json", "limit": 1,
                                         "polygon_geojson": 1, "polygon_threshold": 0.001},
                            headers=HEADERS, timeout=60)
        resp.raise_for_status()
        found = resp.json()[0]
        features[short] = found["geojson"]
        print(short, found["geojson"]["type"], found["display_name"][:60])
        time.sleep(1.2)
    GEOJSON.parent.mkdir(parents=True, exist_ok=True)
    GEOJSON.write_text(json.dumps(features, ensure_ascii=False), encoding="utf-8")


class OkrugLocator:
    """Определяет округ по координатам. За пределами всех округов возвращает OTHER."""

    def __init__(self):
        self.polygons = {}
        for short, geometry in json.loads(GEOJSON.read_text(encoding="utf-8")).items():
            parts = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
            self.polygons[short] = [Polygon(np.array(part[0])) for part in parts]

    def locate(self, lat, lon):
        for short, parts in self.polygons.items():
            if any(p.contains_point((lon, lat)) for p in parts):
                return short
        return "OTHER"

    def locate_many(self, lats, lons):
        points = np.column_stack([lons, lats])
        result = np.full(len(points), "OTHER", dtype=object)
        for short, parts in self.polygons.items():
            for part in parts:
                result[part.contains_points(points)] = short
        return result


if __name__ == "__main__":
    download()
