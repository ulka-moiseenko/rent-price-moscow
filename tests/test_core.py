"""Автоматические проверки: персональные данные, качество данных, ценовые классы, прогноз и самопроверка."""

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from geo import OkrugLocator  # noqa: E402
from preprocess import price_class  # noqa: E402
from quality import QualityGate, psi  # noqa: E402
from security import PersonalDataGuard  # noqa: E402

RAW_OFFER = {
    "offerId": "123", "description": "Звоните Анне +7 916 123-45-67", "url": "//realty.yandex.ru/offer/123",
    "price": {"value": 50000}, "uid": "u1", "partnerName": "Агентство",
    "author": {"category": "OWNER", "name": "Анна", "photo": "x.jpg", "encryptedPhones": ["abc"]},
    "location": {"address": "улица Тестовая, 1", "geocoderAddress": "Россия, Москва, улица Тестовая, 1",
                 "point": {"latitude": 55.75123, "longitude": 37.61789},
                 "metro": {"name": "Тверская", "timeToMetro": 5, "metroTransport": "ON_FOOT"}},
}


def test_sanitize_removes_personal_data():
    clean = PersonalDataGuard().sanitize_offer(RAW_OFFER)
    text = json.dumps(clean, ensure_ascii=False)
    for secret in ("Анн", "916", "x.jpg", "abc", "Тестовая", "realty.yandex", "Агентство", '"123"'):
        assert secret not in text
    assert clean["location"]["point"] == {"latitude": 55.751, "longitude": 37.618}
    assert clean["authorType"] == "OWNER"


def test_pseudonym_is_stable_and_differs():
    guard = PersonalDataGuard()
    assert guard.pseudonym("a") == guard.pseudonym("a")
    assert guard.pseudonym("a") != guard.pseudonym("b")


def test_scan_finds_phone_and_forbidden_column():
    table = pd.DataFrame({"note": ["тел +7 916 123-45-67"], "url": ["x"]})
    problems = PersonalDataGuard.find_personal_data(table)
    assert any("url" in p for p in problems) and any("note" in p for p in problems)


def test_schema_detects_bad_row():
    row = dict(offer_key="a" * 20, building_key="b" * 20, price=-5, area_total=50.0, rooms=1, floor=1, floors_total=5,
               built_year=2000, latitude=55.7, longitude=37.6, metro_minutes=5)
    share, fields = QualityGate.schema_errors(pd.DataFrame([row]))
    assert share == 1 and "price" in fields


def test_psi_detects_shift():
    rng = np.random.default_rng(0)
    base = rng.normal(0, 1, 2000)
    assert psi(base, rng.normal(0, 1, 2000)) < 0.1
    assert psi(base, rng.normal(2, 1, 2000)) > 0.25


def test_price_class_bounds():
    bounds = [70000, 95000, 140000]
    assert [int(price_class(p, bounds)) for p in (50000, 70000, 100000, 500000)] == [0, 1, 2, 3]


def test_okrug_locator():
    locator = OkrugLocator()
    assert locator.locate(55.752, 37.6175) == "ЦАО"
    assert locator.locate(55.98, 37.2) == "ЗелАО"
    assert locator.locate(59.9, 30.3) == "OTHER"


@pytest.fixture(scope="module")
def predictor():
    from predictor import RentPredictor
    return RentPredictor()


def flat(**changes):
    from predictor import Flat
    values = dict(area_total=50, rooms=2, floor=5, floors_total=17, built_year=2010, metro_minutes=10)
    return Flat(**{**values, **changes})


def test_prediction_and_class(predictor):
    result = predictor.predict(flat(), predictor.resolver.by_station("Тверская"))
    assert result["low"] < result["price"] < result["high"]
    assert result["class_name"] in predictor.info["классы"]["названия"]
    assert result["check"]["status"] in ("норма", "внимание")


def test_larger_flat_costs_more(predictor):
    place = predictor.resolver.by_filter(okrug="ЗАО")
    assert predictor.predict(flat(area_total=100, rooms=3), place)["price"] > predictor.predict(flat(area_total=40, rooms=1), place)["price"]


def test_wrong_input_is_rejected(predictor):
    with pytest.raises(ValueError):
        predictor.predict(flat(floor=30, floors_total=5), predictor.resolver.by_station("Тверская"))


def test_unusual_flat_gets_attention(predictor):
    result = predictor.predict(flat(area_total=290, rooms=2), predictor.resolver.by_station("Тверская"))
    assert result["check"]["status"] == "внимание"


def test_gate_stops_small_collection():
    from quality import QualityError
    row = dict(offer_key="a" * 20, building_key="b" * 20, price=50000, area_total=50.0, rooms=1, floor=1, floors_total=5,
               built_year=2000, latitude=55.7, longitude=37.6, metro_minutes=5)
    gate = QualityGate("тест")
    gate.save = lambda: None            # в рабочую таблицу не пишем
    with pytest.raises(QualityError):
        gate.check(pd.DataFrame([row]), datetime.now(), previous_count=1000)
