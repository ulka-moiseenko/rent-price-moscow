"""
Контроль качества данных.

Класс QualityGate проверяет данные перед загрузкой в серебряный слой. Схема каждой строки
проверяется библиотекой Pydantic. Итоги записываются в таблицу quality_checks. Статус «ошибка»
останавливает конвейер, статус «внимание» только фиксируется в журнале.
"""

from datetime import datetime

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, ValidationError

from db import connect
from security import PersonalDataGuard

MAX_SCHEMA_ERRORS = 0.02   # доля строк с нарушением схемы
MIN_VOLUME_SHARE = 0.5     # минимальный объём относительно прошлого сбора
MAX_FLOOR_ERRORS = 0.01    # доля строк, где этаж больше этажности
MAX_AGE_DAYS = 30          # допустимый возраст данных
PSI_ALERT = 0.25           # порог дрейфа PSI: выше него распределение заметно изменилось


class OfferRecord(BaseModel):
    """Схема строки серебряного слоя."""
    offer_key: str = Field(min_length=16)
    building_key: str = Field(min_length=16)
    price: int = Field(gt=0)
    area_total: float = Field(gt=0, lt=3000)
    rooms: int | None = Field(default=None, ge=0, le=30)
    floor: int | None = Field(default=None, ge=-3, le=150)
    floors_total: int | None = Field(default=None, ge=1, le=150)
    built_year: int | None = Field(default=None, ge=1700, le=2035)
    latitude: float = Field(ge=54, le=58)
    longitude: float = Field(ge=35, le=40)
    metro_minutes: int | None = Field(default=None, ge=0, le=300)


class QualityError(Exception):
    """Данные не прошли обязательную проверку."""


def psi(reference, current, bins=10):
    """Индекс стабильности распределения (PSI): сравнивает новое распределение с эталонным."""
    reference, current = pd.Series(reference).dropna(), pd.Series(current).dropna()
    edges = np.unique(reference.quantile(np.linspace(0, 1, bins + 1)))
    edges[0], edges[-1] = -np.inf, np.inf
    expected = np.histogram(reference, edges)[0] / len(reference)
    actual = np.histogram(current, edges)[0] / len(current)
    expected, actual = np.clip(expected, 1e-4, None), np.clip(actual, 1e-4, None)
    return float(((actual - expected) * np.log(actual / expected)).sum())


class QualityGate:
    """Набор проверок качества: схема, полнота, уникальность, логика, свежесть, объём, дрейф."""

    def __init__(self, source):
        self.source = source
        self.results = []

    def _add(self, name, value, threshold, ok, severe=True, details=""):
        status = "норма" if ok else ("ошибка" if severe else "внимание")
        self.results.append({"check_name": name, "value": float(value), "threshold": threshold,
                             "status": status, "details": details})

    @staticmethod
    def schema_errors(df):
        """Доля строк, нарушающих схему OfferRecord, и поля с нарушениями."""
        fields = list(OfferRecord.model_fields)
        table = df[fields].astype(object).where(df[fields].notna(), None)
        bad, by_field = 0, {}
        for record in table.to_dict("records"):
            record = {k: (v.item() if hasattr(v, "item") else v) for k, v in record.items()}
            try:
                OfferRecord(**record)
            except ValidationError as error:
                bad += 1
                for item in error.errors():
                    by_field[item["loc"][0]] = by_field.get(item["loc"][0], 0) + 1
        return bad / max(len(df), 1), by_field

    def check(self, df, collected_at, previous_count=0, reference=None, stop_on_error=True):
        share, by_field = self.schema_errors(df)
        self._add("нарушение схемы, доля строк", share, MAX_SCHEMA_ERRORS, share <= MAX_SCHEMA_ERRORS,
                  details=str(by_field))
        dup = int(df["offer_key"].duplicated().sum())
        self._add("повторы ключа объявления, строк", dup, 0, dup == 0)
        missing = float(df["price"].isna().mean())
        self._add("пропуски в цене, доля строк", missing, 0, missing == 0)
        floor = float((df["floor"] > df["floors_total"]).mean())
        self._add("этаж больше этажности, доля строк", floor, MAX_FLOOR_ERRORS, floor <= MAX_FLOOR_ERRORS,
                  severe=False)
        problems = PersonalDataGuard.find_personal_data(df)
        self._add("персональные данные, находок", len(problems), 0, not problems, details="; ".join(problems))
        if previous_count:
            volume = len(df) / previous_count
            self._add("объём относительно прошлого сбора", volume, MIN_VOLUME_SHARE, volume >= MIN_VOLUME_SHARE)
        age = (datetime.now() - collected_at).days
        self._add("возраст данных, дней", age, MAX_AGE_DAYS, age <= MAX_AGE_DAYS, severe=False)
        if reference is not None:
            for col in ("price", "area_total", "dist_center_km"):
                value = psi(pd.to_numeric(reference[col]), pd.to_numeric(df[col]))
                self._add(f"дрейф PSI: {col}", value, PSI_ALERT, value <= PSI_ALERT, severe=False)
        self.save()
        failed = [r["check_name"] for r in self.results if r["status"] == "ошибка"]
        if failed and stop_on_error:
            raise QualityError("; ".join(failed))
        return pd.DataFrame(self.results)

    def save(self):
        with connect() as conn, conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO quality_checks (source, check_name, value, threshold, status, details) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                [(self.source, r["check_name"], r["value"], r["threshold"], r["status"], r["details"])
                 for r in self.results])
