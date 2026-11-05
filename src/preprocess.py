"""
Подготовка золотого слоя: признаки и целевые переменные для моделей.

Шаги:
1. Загрузка актуальных объявлений серебряного слоя (представление v_offers_current).
2. Исключение Московской области: задача решается для Москвы.
3. Удаление повторов одной квартиры и логических ошибок.
4. Разделение по домам на обучающую и тестовую выборки: квартиры одного дома не попадают в обе.
5. Границы выбросов по цене считаются только по обучающей выборке и применяются к обеим.
6. Обработка пропусков, объединение редких категорий, определение округа.
7. Целевые переменные: логарифм цены (регрессия) и ценовой класс (классификация).
   Границы классов считаются по квартилям цены обучающей выборки.
8. Сохранение в data/gold/offers_gold.csv и в таблицу offers_model.

Заполнение пропусков в числах, кодирование категорий и нормализация выполняются внутри конвейера
модели: их параметры должны вычисляться только по обучающей выборке.

Запуск:
    venv\\Scripts\\python.exe src\\preprocess.py
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupShuffleSplit

from db import connect
from geo import OkrugLocator

PROJECT_DIR = Path(__file__).resolve().parent.parent
GOLD_CSV = PROJECT_DIR / "data" / "gold" / "offers_gold.csv"
GOLD_META = PROJECT_DIR / "data" / "gold" / "gold_meta.json"

DUPLICATE_KEY = ["building_key", "area_total", "floor", "price"]
NUMERIC = ["area_total", "rooms", "floor", "floors_total", "built_year", "metro_minutes",
           "dist_center_km", "latitude", "longitude"]
CATEGORICAL = ["renovation", "building_type", "metro_transport", "okrug"]
TARGET = "log_price"
CLASS_TARGET = "price_class"
CLASS_NAMES = ["Эконом", "Средний", "Комфорт", "Премиум"]

AREA_MIN, AREA_MAX = 12, 300     # кв. м
DIST_MAX = 50                    # км от центра
IQR_K = 1.5                      # множитель межквартильного размаха
KEEP_RENOVATION = ["EURO", "DESIGNER_RENOVATION", "COSMETIC_DONE"]
KEEP_BUILDING = ["MONOLIT", "PANEL", "BRICK", "BLOCK", "MONOLIT_BRICK"]
TEST_SIZE = 0.25
RANDOM_STATE = 42


def price_class(price, bounds):
    """Цена -> номер ценового класса (0 — Эконом ... 3 — Премиум)."""
    return np.searchsorted(bounds, price, side="right")


class DataPreprocessor:
    """Готовит золотой слой из серебряного и хранит журнал шагов."""

    def __init__(self):
        self.steps = []
        self.meta = {}

    def _step(self, name, df):
        self.steps.append((name, len(df)))
        return df

    @staticmethod
    def load():
        with connect() as conn:
            cur = conn.execute("SELECT * FROM v_offers_current")
            df = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
        numeric = ["price", "area_total", "rooms", "floor", "floors_total", "built_year", "metro_minutes",
                   "dist_center_km", "latitude", "longitude"]
        df[numeric] = df[numeric].apply(pd.to_numeric)
        return df

    def clean(self, df):
        """Удаляет то, что не зависит от разделения выборок."""
        self._step("загружено из серебряного слоя", df)
        df = self._step("после исключения Московской области", df[df["in_moscow"]])
        df = self._step("после удаления повторов", df.drop_duplicates(subset=DUPLICATE_KEY, keep="first"))
        df = self._step("после удаления логических ошибок", df[~(df["floor"] > df["floors_total"])])
        wrong = (df["area_total"] < AREA_MIN) | (df["area_total"] > AREA_MAX) | (df["dist_center_km"] > DIST_MAX)
        df = self._step("после удаления ошибочных площадей и окраин", df[~wrong])
        return self._step("после удаления строк без этажа и метро",
                          df.dropna(subset=["floor", "floors_total", "metro_minutes"]))

    @staticmethod
    def split(df):
        """Разделение по домам: 75 процентов обучение, 25 процентов тест."""
        splitter = GroupShuffleSplit(n_splits=1, test_size=TEST_SIZE, random_state=RANDOM_STATE)
        train_idx, test_idx = next(splitter.split(df, groups=df["building_key"]))
        df = df.copy()
        df["split"] = "train"
        df.iloc[test_idx, df.columns.get_loc("split")] = "test"
        return df

    def drop_price_outliers(self, df):
        """Границы межквартильного размаха логарифма цены считаются только по обучающей выборке."""
        log_price = np.log(df.loc[df["split"] == "train", "price"])
        q1, q3 = log_price.quantile([0.25, 0.75])
        low, high = q1 - IQR_K * (q3 - q1), q3 + IQR_K * (q3 - q1)
        self.meta["price_low"], self.meta["price_high"] = float(np.exp(low)), float(np.exp(high))
        logs = np.log(df["price"])
        return self._step("после удаления выбросов цены", df[(logs >= low) & (logs <= high)])

    @staticmethod
    def encode_categories(df):
        df = df.copy()
        for col in ("renovation", "building_type", "metro_transport"):
            df[col] = df[col].fillna("UNKNOWN")
        df.loc[~df["renovation"].isin(KEEP_RENOVATION + ["UNKNOWN"]), "renovation"] = "OTHER"
        df.loc[~df["building_type"].isin(KEEP_BUILDING + ["UNKNOWN"]), "building_type"] = "OTHER"
        df["okrug"] = OkrugLocator().locate_many(df["latitude"].to_numpy(), df["longitude"].to_numpy())
        return df

    def add_targets(self, df):
        df = df.copy()
        df[TARGET] = np.log(df["price"])
        bounds = df.loc[df["split"] == "train", "price"].quantile([0.25, 0.5, 0.75]).tolist()
        self.meta["class_bounds"] = [float(b) for b in bounds]
        self.meta["class_names"] = CLASS_NAMES
        df[CLASS_TARGET] = price_class(df["price"].to_numpy(), bounds)
        return df

    def save(self, df):
        cols = ["offer_key", "building_key"] + NUMERIC + CATEGORICAL + ["price", TARGET, CLASS_TARGET, "split"]
        df = df[cols]
        GOLD_CSV.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(GOLD_CSV, index=False, encoding="utf-8-sig")
        GOLD_META.write_text(json.dumps(self.meta, ensure_ascii=False, indent=1), encoding="utf-8")
        rows = [[None if pd.isna(v) else (v.item() if hasattr(v, "item") else v) for v in r]
                for r in df.itertuples(index=False)]
        with connect() as conn:
            conn.execute("DROP TABLE IF EXISTS offers_model")
            conn.execute("""
                CREATE TABLE offers_model (
                    offer_key       TEXT PRIMARY KEY REFERENCES offers(offer_key),
                    building_key    TEXT NOT NULL,
                    area_total      NUMERIC(7, 2) NOT NULL,
                    rooms           SMALLINT NOT NULL,
                    floor           SMALLINT NOT NULL,
                    floors_total    SMALLINT NOT NULL,
                    built_year      SMALLINT,
                    metro_minutes   SMALLINT NOT NULL,
                    dist_center_km  NUMERIC(6, 2) NOT NULL,
                    latitude        DOUBLE PRECISION NOT NULL,
                    longitude       DOUBLE PRECISION NOT NULL,
                    renovation      TEXT NOT NULL,
                    building_type   TEXT NOT NULL,
                    metro_transport TEXT NOT NULL,
                    okrug           TEXT NOT NULL,
                    price           INTEGER NOT NULL,
                    log_price       DOUBLE PRECISION NOT NULL,
                    price_class     SMALLINT NOT NULL CHECK (price_class BETWEEN 0 AND 3),
                    split           TEXT NOT NULL CHECK (split IN ('train', 'test')),
                    prepared_at     TIMESTAMP NOT NULL DEFAULT now()
                )""")
            with conn.cursor() as cur:
                cur.executemany(f"INSERT INTO offers_model ({', '.join(cols)}) "
                                f"VALUES ({', '.join(['%s'] * len(cols))})", rows)

    def run(self):
        df = self.clean(self.load())
        df = self.drop_price_outliers(self.split(df))
        df = self.add_targets(self.encode_categories(df))
        self.save(df)
        for name, n in self.steps:
            print(f"{name:45} {n}")
        print("обучающая / тестовая выборка:", (df["split"] == "train").sum(), "/", (df["split"] == "test").sum())
        print("границы цены:", round(self.meta["price_low"]), round(self.meta["price_high"]))
        print("границы классов:", self.meta["class_bounds"], df.groupby("split")[CLASS_TARGET].value_counts().to_dict())
        return df


if __name__ == "__main__":
    DataPreprocessor().run()
