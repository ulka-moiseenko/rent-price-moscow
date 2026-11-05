"""
Обучение и сравнение моделей прогноза цены аренды и ценового класса.

Модели: базовая (медиана), линейная регрессия (классическая), случайный лес и градиентный бустинг
(ансамбли деревьев), многослойный перцептрон (нейронная сеть). Все модели — конвейеры Pipeline:
заполнение пропусков, нормализация чисел, кодирование категорий, модель. Параметры преобразований
вычисляются только по обучающей выборке.

Гиперпараметры подбираются перекрёстной проверкой по 5 частям. Квартиры одного дома всегда попадают
в одну часть (GroupKFold). Лучшая модель выбирается по перекрёстной проверке, а тестовая выборка
служит для итоговой оценки.

Ценовой класс определяется по прогнозу цены. Для сравнения обучается классификатор на бустинге.

Запуск:
    venv\\Scripts\\python.exe src\\train.py
"""

import json
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer, TransformedTargetRegressor
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LinearRegression
from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score, mean_absolute_error,
                             mean_absolute_percentage_error, mean_squared_error, r2_score)
from sklearn.model_selection import GridSearchCV, GroupKFold, cross_val_score
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from db import connect
from preprocess import CATEGORICAL, CLASS_NAMES, CLASS_TARGET, GOLD_CSV, GOLD_META, NUMERIC, RANDOM_STATE, TARGET, price_class

PROJECT_DIR = Path(__file__).resolve().parent.parent
MODEL_DIR = PROJECT_DIR / "models"
METRICS_PATH = PROJECT_DIR / "reports" / "metrics.json"
FEATURES = NUMERIC + CATEGORICAL
BASE, LINEAR, FOREST, BOOSTING, NETWORK = ("Базовая (медиана)", "Линейная регрессия", "Случайный лес",
                                           "Градиентный бустинг", "Нейронная сеть")
GRIDS = {
    FOREST: {"model__n_estimators": [300], "model__max_depth": [None, 20],
             "model__min_samples_leaf": [1, 3], "model__max_features": ["sqrt", 0.5]},
    BOOSTING: {"model__n_estimators": [300, 600], "model__learning_rate": [0.05, 0.1],
               "model__max_depth": [3, 5], "model__subsample": [0.8]},
    NETWORK: {"model__regressor__hidden_layer_sizes": [(64,), (64, 32), (128, 64)],
              "model__regressor__alpha": [0.01, 0.1, 1.0]},
}


def make_preprocessor():
    """Числа: пропуски заполняются медианой, значения нормализуются. Категории: кодирование one-hot."""
    numeric = Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())])
    return ColumnTransformer([("num", numeric, NUMERIC),
                              ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL)])


def make_network():
    """Многослойный перцептрон. Целевая переменная тоже нормализуется: так обучение устойчивее."""
    net = MLPRegressor(hidden_layer_sizes=(64,), alpha=0.1, early_stopping=True, n_iter_no_change=30,
                       max_iter=3000, random_state=RANDOM_STATE)
    return TransformedTargetRegressor(regressor=net, transformer=StandardScaler())


class ModelTrainer:
    """Обучает модели, выбирает лучшую, оценивает её и сохраняет результат."""

    def __init__(self):
        df = pd.read_csv(GOLD_CSV, encoding="utf-8-sig")
        self.meta = json.loads(GOLD_META.read_text(encoding="utf-8"))
        self.train, self.test = df[df["split"] == "train"], df[df["split"] == "test"]
        self.X_train, self.X_test = self.train[FEATURES], self.test[FEATURES]
        self.y_train, self.y_test = self.train[TARGET], self.test[TARGET]
        self.groups = self.train["building_key"]
        self.cv = GroupKFold(n_splits=5)
        self.models = {name: Pipeline([("prep", make_preprocessor()), ("model", est)]) for name, est in {
            BASE: DummyRegressor(strategy="median"),
            LINEAR: LinearRegression(),
            FOREST: RandomForestRegressor(random_state=RANDOM_STATE, n_jobs=1),
            BOOSTING: GradientBoostingRegressor(random_state=RANDOM_STATE),
            NETWORK: make_network(),
        }.items()}
        self.report = {"features": FEATURES, "n_train": len(self.train), "n_test": len(self.test),
                       "class_bounds": self.meta["class_bounds"], "class_names": CLASS_NAMES}

    def cross_validate(self, label):
        rows = {}
        for name, model in self.models.items():
            scores = -cross_val_score(model, self.X_train, self.y_train, groups=self.groups, cv=self.cv,
                                      scoring="neg_mean_absolute_error", n_jobs=-1)
            rows[name] = {"mean": float(scores.mean()), "std": float(scores.std())}
            print(f"{label:15} {name:22} MAE логарифма {scores.mean():.4f} разброс {scores.std():.4f}", flush=True)
        self.report[f"cv_{label}"] = rows

    def tune(self):
        best = {}
        for name, grid in GRIDS.items():
            search = GridSearchCV(self.models[name], grid, cv=self.cv, scoring="neg_mean_absolute_error", n_jobs=-1)
            search.fit(self.X_train, self.y_train, groups=self.groups)
            self.models[name] = search.best_estimator_
            params = {k.split("__")[-1]: str(v) for k, v in search.best_params_.items()}
            best[name] = {"params": params, "variants": len(search.cv_results_["params"])}
            print(name, "лучшие параметры", params, flush=True)
        self.report["best_params"] = best

    @staticmethod
    def errors(y_log, pred_log):
        y, pred = np.exp(y_log), np.exp(pred_log)
        return {"MAE": float(mean_absolute_error(y, pred)), "RMSE": float(np.sqrt(mean_squared_error(y, pred))),
                "MAPE": float(mean_absolute_percentage_error(y, pred) * 100), "R2": float(r2_score(y, pred))}

    def class_metrics(self, true, pred):
        return {"accuracy": float(accuracy_score(true, pred)), "macro_f1": float(f1_score(true, pred, average="macro")),
                "off_by_one_or_less": float((np.abs(true - pred) <= 1).mean()),
                "confusion": confusion_matrix(true, pred, labels=range(4)).tolist()}

    def evaluate(self):
        """Итоговая оценка всех моделей на обучающей и тестовой выборках."""
        bounds, true_class = self.meta["class_bounds"], self.test[CLASS_TARGET].to_numpy()
        results = {}
        for name, model in self.models.items():
            model.fit(self.X_train, self.y_train)
            pred_test = model.predict(self.X_test)
            results[name] = {"train": self.errors(self.y_train, model.predict(self.X_train)),
                             "test": self.errors(self.y_test, pred_test),
                             "class": self.class_metrics(true_class, price_class(np.exp(pred_test), bounds))}
        self.report["results"] = results
        direct = Pipeline([("prep", make_preprocessor()),
                           ("model", GradientBoostingClassifier(n_estimators=200, learning_rate=0.05, max_depth=4,
                                                                subsample=0.8, random_state=RANDOM_STATE))])
        direct.fit(self.X_train, self.train[CLASS_TARGET])
        self.report["direct_classifier"] = self.class_metrics(true_class, direct.predict(self.X_test))

    def select(self):
        """Лучшая модель выбирается по перекрёстной проверке, тестовая выборка в выборе не участвует."""
        scores = {name: self.report["cv_подобранные"][name]["mean"] for name in self.report["cv_подобранные"]}
        return min(scores, key=scores.get)

    def details(self, best):
        model = self.models[best]
        pred, y = np.exp(model.predict(self.X_test)), np.exp(self.y_test)
        ape = np.abs(pred - y) / y
        imp = permutation_importance(model, self.X_test, self.y_test, n_repeats=10, random_state=RANDOM_STATE,
                                     scoring="neg_mean_absolute_error", n_jobs=-1)
        self.report["best"] = best
        self.report["best_details"] = {
            "median_ape": float(ape.median() * 100), "ape_le_10": float((ape <= 0.10).mean() * 100),
            "ape_gt_30": float((ape > 0.30).mean() * 100), "under": float((pred < y).mean() * 100),
            "pred_mean": float(pred.mean()), "true_mean": float(y.mean()), "true_median": float(y.median()),
            "train_median": float(np.exp(self.y_train).median()),
            "by_class_mape": {CLASS_NAMES[c]: float(ape[self.test[CLASS_TARGET] == c].mean() * 100) for c in range(4)},
            "importance": dict(sorted(zip(FEATURES, map(float, imp.importances_mean)), key=lambda x: -x[1])),
        }
        mape = self.report["results"][best]["test"]["MAPE"] / 100
        self.report["best_details"]["coverage"] = float((ape <= mape).mean() * 100)

    def save(self, best):
        MODEL_DIR.mkdir(exist_ok=True)
        joblib.dump(self.models[best], MODEL_DIR / "model.joblib")
        joblib.dump(self.models[LINEAR], MODEL_DIR / "control_linear.joblib")   # контрольная модель для самопроверки
        numeric = self.train[NUMERIC].apply(pd.to_numeric)
        info = {"модель": best, "обучена": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "объявлений в обучении": len(self.train), "признаки": FEATURES,
                "ошибки на тесте": self.report["results"][best]["test"],
                "классы": {"границы": self.meta["class_bounds"], "названия": CLASS_NAMES},
                "диапазоны": {c: [float(numeric[c].quantile(0.01)), float(numeric[c].quantile(0.99))] for c in NUMERIC},
                "значения": {c: sorted(self.train[c].unique().tolist()) for c in CATEGORICAL},
                "ошибка_контрольной_MAPE": self.report["results"][LINEAR]["test"]["MAPE"]}
        (MODEL_DIR / "model_info.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
        METRICS_PATH.parent.mkdir(exist_ok=True)
        METRICS_PATH.write_text(json.dumps(self.report, ensure_ascii=False, indent=1), encoding="utf-8")

    def check_monitor(self):
        """Проверяет самопроверку на тестовой выборке: ошибка при статусах «норма» и «внимание»."""
        from monitor import PredictionMonitor
        info = json.loads((MODEL_DIR / "model_info.json").read_text(encoding="utf-8"))
        monitor = PredictionMonitor(info, self.train)
        self.report["self_check_on_test"] = monitor.validate_on_test(
            joblib.load(MODEL_DIR / "model.joblib"), joblib.load(MODEL_DIR / "control_linear.joblib"), self.test, FEATURES)
        METRICS_PATH.write_text(json.dumps(self.report, ensure_ascii=False, indent=1), encoding="utf-8")

    def log_runs(self, best):
        with connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS model_runs (
                    run_at TIMESTAMP NOT NULL DEFAULT now(), model TEXT NOT NULL,
                    mae DOUBLE PRECISION, rmse DOUBLE PRECISION, mape DOUBLE PRECISION, r2 DOUBLE PRECISION,
                    class_accuracy DOUBLE PRECISION, class_f1 DOUBLE PRECISION, is_best BOOLEAN NOT NULL)""")
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO model_runs (model, mae, rmse, mape, r2, class_accuracy, class_f1, is_best) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    [(name, r["test"]["MAE"], r["test"]["RMSE"], r["test"]["MAPE"], r["test"]["R2"],
                      r["class"]["accuracy"], r["class"]["macro_f1"], name == best)
                     for name, r in self.report["results"].items()])

    def run(self):
        self.cross_validate("по_умолчанию")
        self.tune()
        self.cross_validate("подобранные")
        self.evaluate()
        best = self.select()
        self.details(best)
        self.save(best)
        self.check_monitor()
        self.log_runs(best)
        for name, r in self.report["results"].items():
            t, c = r["test"], r["class"]
            print(f"{name:22} обучение MAPE {r['train']['MAPE']:5.1f} | тест MAE {t['MAE']:7.0f} RMSE {t['RMSE']:7.0f} "
                  f"MAPE {t['MAPE']:5.1f} R2 {t['R2']:6.3f} | класс accuracy {c['accuracy']:.3f} F1 {c['macro_f1']:.3f}")
        print("Прямой классификатор:", {k: round(v, 3) for k, v in self.report["direct_classifier"].items() if k != "confusion"})
        print("Лучшая модель:", best)
        return best


if __name__ == "__main__":
    ModelTrainer().run()
