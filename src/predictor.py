"""
Прогноз цены аренды и ценового класса по параметрам квартиры.

Класс LocationResolver переводит выбранное пользователем расположение (адрес, станция, округ или
удалённость от центра) в признаки модели. Класс RentPredictor проверяет ввод, делает прогноз
и передаёт результат на самопроверку классу PredictionMonitor.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from geo import OkrugLocator
from lake import distance_km
from monitor import PredictionMonitor
from preprocess import GOLD_CSV, price_class

PROJECT_DIR = Path(__file__).resolve().parent.parent
MODEL_DIR = PROJECT_DIR / "models"
STATIONS_PATH = PROJECT_DIR / "data" / "reference" / "metro_stations.csv"

# Подписи для пользователя и коды, на которых обучена модель
RENOVATION = {"Евроремонт": "EURO", "Дизайнерский": "DESIGNER_RENOVATION", "Косметический": "COSMETIC_DONE",
              "Другой": "OTHER", "Не указан": "UNKNOWN"}
BUILDING = {"Монолит": "MONOLIT", "Панельный": "PANEL", "Кирпичный": "BRICK", "Блочный": "BLOCK",
            "Монолитно-кирпичный": "MONOLIT_BRICK", "Другой": "OTHER", "Не указан": "UNKNOWN"}
TRANSPORT = {"Пешком": "ON_FOOT", "На транспорте": "ON_TRANSPORT"}
LIMITS = {"area_total": (12, 300), "rooms": (0, 12), "floor": (1, 95), "floors_total": (1, 100),
          "built_year": (1800, 2030), "metro_minutes": (1, 60)}


@dataclass
class Flat:
    """Параметры квартиры, которые вводит пользователь."""
    area_total: float
    rooms: int
    floor: int
    floors_total: int
    built_year: int | None
    metro_minutes: int
    metro_transport: str = "Пешком"
    renovation: str = "Евроремонт"
    building_type: str = "Монолит"


@dataclass
class Location:
    """Расположение квартиры в виде признаков модели."""
    latitude: float
    longitude: float
    dist_center_km: float
    okrug: str
    description: str
    exact: bool = False       # True, если расположение известно с точностью до дома


class LocationResolver:
    """Переводит адрес, станцию, округ или удалённость от центра в координаты и признаки."""

    def __init__(self, train=None):
        self.locator = OkrugLocator()
        self.stations = pd.read_csv(STATIONS_PATH, encoding="utf-8-sig").set_index("name")
        if train is None:
            gold = pd.read_csv(GOLD_CSV, encoding="utf-8-sig")
            train = gold[gold["split"] == "train"]
        self.train = train

    def _point(self, lat, lon, description, exact=False):
        return Location(lat, lon, round(distance_km(lat, lon), 2), self.locator.locate(lat, lon), description, exact)

    def by_coordinates(self, lat, lon, description):
        return self._point(round(lat, 3), round(lon, 3), description, exact=True)

    def by_station(self, name):
        s = self.stations.loc[name]
        return self._point(float(s["latitude"]), float(s["longitude"]), f"станция «{name}»")

    def by_filter(self, okrug=None, distance=None):
        """Типичная точка объявлений в округе и (или) на заданном расстоянии от центра."""
        part = self.train
        if okrug:
            part = part[part["okrug"] == okrug]
        if distance is not None:
            near = part[(part["dist_center_km"] - distance).abs() <= 1.5]
            if len(near) < 5:
                near = part.assign(d=(part["dist_center_km"] - distance).abs()).nsmallest(20, "d")
            part = near
        if part.empty:
            raise ValueError("нет данных для выбранного расположения")
        text = ", ".join(x for x in (okrug, f"около {distance:g} км от центра" if distance is not None else None) if x)
        return Location(float(part["latitude"].median()), float(part["longitude"].median()),
                        float(distance if distance is not None else part["dist_center_km"].median()),
                        okrug or part["okrug"].mode()[0], text)

    def nearest_station(self, lat, lon):
        dist = self.stations.apply(lambda s: distance_km(s["latitude"], s["longitude"], (lat, lon)), axis=1)
        return dist.idxmin(), float(dist.min())


class RentPredictor:
    """Прогноз цены и ценового класса с самопроверкой результата."""

    def __init__(self):
        self.model = joblib.load(MODEL_DIR / "model.joblib")
        self.control = joblib.load(MODEL_DIR / "control_linear.joblib")
        self.info = json.loads((MODEL_DIR / "model_info.json").read_text(encoding="utf-8"))
        gold = pd.read_csv(GOLD_CSV, encoding="utf-8-sig")
        self.train = gold[gold["split"] == "train"]
        self.resolver = LocationResolver(self.train)
        self.monitor = PredictionMonitor(self.info, self.train)

    @staticmethod
    def validate(flat):
        errors = []
        for field, (low, high) in LIMITS.items():
            value = getattr(flat, field)
            if value is not None and not low <= value <= high:
                errors.append(f"{field}: значение {value} вне диапазона от {low} до {high}")
        if flat.floor > flat.floors_total:
            errors.append("этаж не может быть больше этажности дома")
        return errors

    @staticmethod
    def to_features(flat, location):
        return pd.DataFrame([{
            "area_total": flat.area_total, "rooms": flat.rooms, "floor": flat.floor, "floors_total": flat.floors_total,
            "built_year": np.nan if flat.built_year is None else flat.built_year, "metro_minutes": flat.metro_minutes,
            "dist_center_km": location.dist_center_km, "latitude": location.latitude, "longitude": location.longitude,
            "renovation": RENOVATION[flat.renovation], "building_type": BUILDING[flat.building_type],
            "metro_transport": TRANSPORT[flat.metro_transport], "okrug": location.okrug,
        }])

    def predict(self, flat, location):
        """Цена, диапазон, ценовой класс и итог самопроверки."""
        errors = self.validate(flat)
        if errors:
            raise ValueError("; ".join(errors))
        features = self.to_features(flat, location)[self.info["признаки"]]
        price = float(np.exp(self.model.predict(features)[0]))          # модель прогнозирует логарифм цены
        control = float(np.exp(self.control.predict(features)[0]))
        mape = self.info["ошибки на тесте"]["MAPE"] / 100
        number = int(price_class(price, self.info["классы"]["границы"]))
        check = self.monitor.check(features.iloc[0], price, control)
        result = {"price": price, "low": price * (1 - mape), "high": price * (1 + mape), "class_number": number,
                  "class_name": self.info["классы"]["названия"][number], "check": check, "location": location}
        self.monitor.log(features.iloc[0], result, exact_location=location.exact)
        return result
