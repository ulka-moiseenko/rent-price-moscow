"""
Мониторинг прогнозов: самопроверка каждого результата и журнал.

При каждом прогнозе проверяется следующее:
1. значения признаков лежат в диапазоне обучающих данных (от 1-го до 99-го процентиля);
2. категории встречались при обучении;
3. прогноз близок к прогнозу контрольной модели (линейной регрессии);
4. прогноз близок к медианной цене похожих квартир из обучающей выборки;
5. прогноз лежит в границах цен, на которых обучена модель.

Статус «норма» означает, что все проверки пройдены. Статус «внимание» означает, что прогноз надо
воспринимать осторожнее. Журнал logs/predictions.jsonl не содержит адреса: при точном адресе
координаты в журнал не записываются.
"""

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
LOG_PATH = PROJECT_DIR / "logs" / "predictions.jsonl"
MAX_CONTROL_GAP = 0.35   # допустимое расхождение с контрольной моделью
MAX_ANALOG_GAP = 0.40    # допустимое расхождение с похожими квартирами
MIN_ANALOGS = 5
AREA_SHARE, DIST_KM = 0.2, 3.0   # что считать похожей квартирой


class PredictionMonitor:
    """Самопроверка прогноза и журнал прогнозов."""

    def __init__(self, info, train):
        self.ranges = info["диапазоны"]
        self.values = info["значения"]
        self.train = train

    def analogs(self, row):
        """Похожие квартиры: то же число комнат, площадь отличается не больше чем на 20 процентов,
        расстояние до центра не больше чем на 3 км."""
        t = self.train
        return t[(t["rooms"] == row["rooms"]) & ((t["area_total"] - row["area_total"]).abs() <= row["area_total"] * AREA_SHARE)
                 & ((t["dist_center_km"] - row["dist_center_km"]).abs() <= DIST_KM)]

    def check(self, row, price, control):
        """Список проверок и общий статус."""
        items = []
        out = [c for c, (low, high) in self.ranges.items() if pd.notna(row[c]) and not low <= row[c] <= high]
        items.append(("Параметры в диапазоне обучающих данных", not out,
                      "вне диапазона: " + ", ".join(out) if out else "все значения типичны"))
        unknown = [c for c, known in self.values.items() if row[c] not in known]
        items.append(("Категории известны модели", not unknown, ", ".join(unknown) if unknown else "все известны"))
        gap = abs(price - control) / price
        items.append(("Совпадение с контрольной моделью", gap <= MAX_CONTROL_GAP,
                      f"расхождение {gap * 100:.0f} процентов, допустимо {MAX_CONTROL_GAP * 100:.0f}"))
        analogs = self.analogs(row)
        if len(analogs) >= MIN_ANALOGS:
            median = float(analogs["price"].median())
            gap = abs(price - median) / median
            items.append(("Сравнение с похожими квартирами", gap <= MAX_ANALOG_GAP,
                          f"медиана {median:,.0f} руб. по {len(analogs)} квартирам, отличие {gap * 100:.0f} процентов".replace(",", " ")))
        else:
            median = None
            items.append(("Сравнение с похожими квартирами", False, f"мало похожих квартир: {len(analogs)}"))
        low, high = self.train["price"].min(), self.train["price"].max()
        items.append(("Цена в границах обучающих данных", low <= price <= high, f"от {low:,.0f} до {high:,.0f} руб.".replace(",", " ")))
        status = "норма" if all(ok for _, ok, _ in items) else "внимание"
        return {"status": status, "items": items, "analog_median": median}

    def log(self, row, result, exact_location=False):
        """Запись в журнал. Координаты точного адреса не сохраняются."""
        record = {k: (None if pd.isna(v) else (v.item() if hasattr(v, "item") else v)) for k, v in row.items()}
        if exact_location:
            record.pop("latitude"), record.pop("longitude")
            record["dist_center_km"] = round(record["dist_center_km"])
        record.update(time=f"{datetime.now():%Y-%m-%d %H:%M:%S}", price=round(result["price"]),
                      price_class=result["class_name"], status=result["check"]["status"],
                      failed=[name for name, ok, _ in result["check"]["items"] if not ok])
        LOG_PATH.parent.mkdir(exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def validate_on_test(self, model, control, test, features):
        """Проверка самой самопроверки: ошибка на тесте при статусах «норма» и «внимание»."""
        pred, ctrl = np.exp(model.predict(test[features])), np.exp(control.predict(test[features]))
        status = [self.check(row, p, c)["status"] for (_, row), p, c in zip(test[features].iterrows(), pred, ctrl)]
        frame = pd.DataFrame({"status": status, "ape": np.abs(pred - test["price"].to_numpy()) / test["price"].to_numpy() * 100})
        return {s: {"share": float((frame["status"] == s).mean() * 100), "mape": float(frame.loc[frame["status"] == s, "ape"].mean())}
                for s in frame["status"].unique()}
