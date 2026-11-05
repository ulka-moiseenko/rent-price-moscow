"""
Собирает и выполняет блокноты Jupyter. Весь код анализа хранится здесь, а результаты попадают в блокноты.

Запуск:
    venv\\Scripts\\python.exe notebooks\\build_notebooks.py
Один блокнот:
    venv\\Scripts\\python.exe notebooks\\build_notebooks.py 02
"""

import sys
from pathlib import Path

import nbformat
from nbclient import NotebookClient

NB_DIR = Path(__file__).resolve().parent

SETUP = '''\
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path.cwd().parent
sys.path.insert(0, str(ROOT / "src"))
from db import connect

pd.set_option("display.width", 130, "display.max_columns", 30, "display.max_rows", 60)
FIG = ROOT / "reports" / "figures"
FIG.mkdir(parents=True, exist_ok=True)
NAVY, BLUE, YELLOW, GREY = "#17358A", "#2F6FD0", "#F2C230", "#8A94A6"
plt.rcParams.update({"font.family": "Times New Roman", "font.size": 12, "axes.spines.top": False,
                     "axes.spines.right": False, "figure.facecolor": "white", "savefig.dpi": 200,
                     "savefig.bbox": "tight"})


def sql(query, params=None):
    """Запрос к базе PostgreSQL: результат в виде таблицы pandas."""
    with connect() as conn:
        cur = conn.execute(query, params)
        return pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])'''

NB1 = [
    ("md", "# Этап 1. Слои данных, персональные данные и качество\n\nБронзовый слой лежит в data/bronze, "
           "серебряный в таблицах базы и в data/silver, золотой в таблице offers_model и в data/gold."),
    ("code", "setup", SETUP),
    ("code", "layers", '''\
# Объём данных в слоях
for path in sorted((ROOT / "data" / "bronze").glob("offers_*.jsonl")):
    with open(path, encoding="utf-8") as f:
        print(path.name, "строк", sum(1 for _ in f), "размер, МБ", round(path.stat().st_size / 1e6, 1))
print(sql("SELECT (SELECT COUNT(*) FROM offers) AS offers, (SELECT COUNT(*) FROM price_history) AS price_history, "
          "(SELECT COUNT(*) FROM v_offers_current) AS current, (SELECT COUNT(*) FROM offers_model) AS gold").to_string(index=False))'''),
    ("code", "bronze_fields", '''\
# Какие поля остаются в записи бронзового слоя
with open(ROOT / "data" / "bronze" / "offers_2026-10-25_1742.jsonl", encoding="utf-8") as f:
    record = json.loads(f.readline())
print(sorted(record))
print("location:", sorted(record["location"]))
print("point:", record["location"]["point"])
print("offerKey:", record["offerKey"], "buildingKey:", record["buildingKey"])'''),
    ("code", "pd_scan", '''\
# Проверка серебряного и золотого слоёв на персональные данные
from security import PersonalDataGuard

for name in ("silver/offers_silver.csv", "gold/offers_gold.csv"):
    table = pd.read_csv(ROOT / "data" / name, encoding="utf-8-sig", low_memory=False)
    print(name, "столбцов", table.shape[1], "строк", table.shape[0], "находок:", PersonalDataGuard.find_personal_data(table))'''),
    ("code", "quality", '''\
# Журнал проверок качества данных
sql("SELECT source, check_name, ROUND(value::numeric, 4) AS value, threshold, status FROM quality_checks "
    "ORDER BY checked_at, source")'''),
    ("code", "update_check", '''\
# Механизм обновления: два сбора, журнал загрузок и история цен
print(sql("SELECT run_id, file_name, offers_count, new_offers, price_changes FROM load_runs ORDER BY run_id").to_string(index=False))
print(sql("SELECT COUNT(*) FILTER (WHERE is_active) AS active, COUNT(*) FILTER (WHERE NOT is_active) AS inactive FROM offers").to_string(index=False))
print(sql("SELECT run_id, price FROM price_history WHERE offer_key IN (SELECT offer_key FROM price_history "
          "GROUP BY offer_key HAVING COUNT(DISTINCT price) > 1) ORDER BY run_id").to_string(index=False))'''),
    ("code", "roles", '''\
# Разграничение доступа: права роли rent_reader
sql("SELECT table_name, privilege_type FROM information_schema.role_table_grants WHERE grantee = 'rent_reader' ORDER BY table_name")'''),
]

NB2 = [
    ("md", "# Этап 2. Разведочный анализ данных\n\nАнализ выполняется по серебряному слою, только объявления из Москвы."),
    ("code", "setup", SETUP),
    ("code", "load", '''\
df = sql("SELECT * FROM v_offers_current WHERE in_moscow")
num = ["price", "area_total", "area_kitchen", "rooms", "floor", "floors_total", "built_year", "metro_minutes", "dist_center_km"]
df[num] = df[num].apply(pd.to_numeric)
print("Объявлений:", len(df), "столбцов:", df.shape[1])
df[["price", "area_total", "rooms", "floor", "floors_total", "built_year", "metro_minutes", "dist_center_km"]].describe().round(1).T[["count", "mean", "min", "25%", "50%", "75%", "max"]]'''),
    ("code", "missing", '''\
# Доля пропусков
df.isna().mean().sort_values(ascending=False).head(14).round(3)'''),
    ("code", "skew", '''\
# Асимметрия цены и её логарифма
print("Средняя:", round(df.price.mean()), "медиана:", round(df.price.median()))
print("Асимметрия цены:", round(df.price.skew(), 2), "логарифма:", round(np.log(df.price).skew(), 2))
fig, ax = plt.subplots(1, 2, figsize=(11, 3.8))
ax[0].hist(df.price / 1000, bins=60, range=(0, 800), color=BLUE)
ax[0].set(xlabel="Цена, тыс. руб. в месяц", ylabel="Объявлений")
ax[1].hist(np.log(df.price), bins=50, color=NAVY)
ax[1].set(xlabel="Натуральный логарифм цены", ylabel="Объявлений")
fig.savefig(FIG / "price_distribution.png")'''),
    ("code", "iqr", '''\
# Межквартильный размах на цене и на логарифме цены
q1, q3 = df.price.quantile([.25, .75])
print("По цене: граница", round(q3 + 1.5 * (q3 - q1)), "выбросов", int((df.price > q3 + 1.5 * (q3 - q1)).sum()))
l = np.log(df.price); a, b = l.quantile([.25, .75]); low, high = a - 1.5 * (b - a), b + 1.5 * (b - a)
print("По логарифму: границы", round(np.exp(low)), round(np.exp(high)), "выбросов", int(((l < low) | (l > high)).sum()))'''),
    ("code", "corr", '''\
# Корреляция Спирмена
cols = ["price", "area_total", "rooms", "area_kitchen", "built_year", "floors_total", "floor", "metro_minutes", "dist_center_km"]
names = ["Цена", "Площадь", "Комнаты", "Кухня", "Год", "Этажность", "Этаж", "До метро", "До центра"]
corr = df[cols].corr(method="spearman")
print(corr["price"].round(2).sort_values().to_string())
fig, ax = plt.subplots(figsize=(7, 5.6))
im = ax.imshow(corr, cmap="RdBu", vmin=-1, vmax=1)
ax.set_xticks(range(len(cols)), names, rotation=45, ha="right"); ax.set_yticks(range(len(cols)), names)
for i in range(len(cols)):
    for j in range(len(cols)):
        ax.text(j, i, f"{corr.iloc[i, j]:.2f}".replace(".", ","), ha="center", va="center", fontsize=9,
                color="white" if abs(corr.iloc[i, j]) > .6 else "black")
fig.colorbar(im, shrink=.8, label="Коэффициент Спирмена")
fig.savefig(FIG / "correlation.png")'''),
    ("code", "groups", '''\
# Медианная цена по группам
print(df.groupby("rooms").price.agg(["count", "median"]).round().head(6).to_string())
print(df.groupby(df.renovation.fillna("не указан")).price.agg(["count", "median"]).sort_values("median").to_string())
print(df.groupby(df.building_type.fillna("не указан")).agg(n=("price", "count"), price=("price", "median"), dist=("dist_center_km", "median")).sort_values("price").to_string())
print(df.groupby("metro_transport").price.agg(["count", "median"]).to_string())
print(df.groupby(pd.cut(df.dist_center_km, [0, 5, 15, 100])).apply(lambda g: (g.price / g.area_total).median()).round().to_string())'''),
    ("code", "okrug", '''\
# Цена по округам: округ вычислен в золотом слое по координатам
gold = pd.read_csv(ROOT / "data" / "gold" / "offers_gold.csv", encoding="utf-8-sig")
table = gold.groupby("okrug").agg(n=("price", "count"), price=("price", "median"), dist=("dist_center_km", "median")).sort_values("price")
print(table.round(1).to_string())
part = table[table.index != "OTHER"]
fig, ax = plt.subplots(figsize=(8, 3.8))
ax.barh(part.index, part.price / 1000, color=BLUE)
ax.set(xlabel="Медианная цена, тыс. руб. в месяц")
fig.savefig(FIG / "price_by_okrug.png")'''),
    ("code", "classes", '''\
# Ценовые классы: границы и состав
meta = json.loads((ROOT / "data" / "gold" / "gold_meta.json").read_text(encoding="utf-8"))
print(meta)
print(gold.groupby(["split", "price_class"]).agg(n=("price", "count"), price=("price", "median"), area=("area_total", "median"), dist=("dist_center_km", "median")).round(1).to_string())'''),
    ("code", "steps", '''\
# Журнал подготовки золотого слоя
import io, contextlib
from preprocess import DataPreprocessor
p = DataPreprocessor()
buffer = io.StringIO()
with contextlib.redirect_stdout(buffer):
    p.clean(p.load())
for name, n in p.steps:
    print(f"{name:45} {n}")
print("после удаления выбросов цены", len(gold), "обучение", (gold.split == "train").sum(), "тест", (gold.split == "test").sum())
print("общих домов в обучении и тесте:", len(set(gold[gold.split == "train"].building_key) & set(gold[gold.split == "test"].building_key)))'''),
]

NB3 = [
    ("md", "# Этап 3. Модели\n\nРезультаты получены программой src/train.py и сохранены в reports/metrics.json."),
    ("code", "setup", SETUP),
    ("code", "load", '''\
import joblib
from preprocess import CLASS_NAMES
m = json.loads((ROOT / "reports" / "metrics.json").read_text(encoding="utf-8"))
model = joblib.load(ROOT / "models" / "model.joblib")
gold = pd.read_csv(ROOT / "data" / "gold" / "offers_gold.csv", encoding="utf-8-sig")
test = gold[gold.split == "test"]
print("Признаки:", m["features"])
print("Обучение:", m["n_train"], "тест:", m["n_test"], "лучшая модель:", m["best"])'''),
    ("code", "cv", '''\
# Перекрёстная проверка по домам: MAE логарифма цены
print(pd.DataFrame({k: pd.DataFrame(m[k]).T["mean"] for k in ("cv_по_умолчанию", "cv_подобранные")}).round(4).to_string())
print(pd.DataFrame(m["cv_подобранные"]).T["std"].round(4).to_string())
for name, value in m["best_params"].items():
    print(name, value)'''),
    ("code", "results", '''\
# Итоговые ошибки на обучающей и тестовой выборках
rows = {}
for name, r in m["results"].items():
    rows[name] = {"MAE обуч.": r["train"]["MAE"], "MAE тест": r["test"]["MAE"], "RMSE тест": r["test"]["RMSE"],
                  "MAPE обуч.": r["train"]["MAPE"], "MAPE тест": r["test"]["MAPE"], "R2 тест": r["test"]["R2"]}
pd.DataFrame(rows).T.round({"MAE обуч.": 0, "MAE тест": 0, "RMSE тест": 0, "MAPE обуч.": 1, "MAPE тест": 1, "R2 тест": 3})'''),
    ("code", "class_metrics", '''\
# Ценовой класс: точность и F1 на тесте
rows = {name: {k: r["class"][k] for k in ("accuracy", "macro_f1", "off_by_one_or_less")} for name, r in m["results"].items()}
rows["Прямой классификатор"] = {k: m["direct_classifier"][k] for k in ("accuracy", "macro_f1", "off_by_one_or_less")}
print(pd.DataFrame(rows).T.round(3).to_string())
matrix = np.array(m["results"][m["best"]]["class"]["confusion"])
print(pd.DataFrame(matrix, index=CLASS_NAMES, columns=CLASS_NAMES).to_string())
fig, ax = plt.subplots(figsize=(5.2, 4.2))
ax.imshow(matrix, cmap="Blues")
ax.set_xticks(range(4), CLASS_NAMES); ax.set_yticks(range(4), CLASS_NAMES)
ax.set(xlabel="Прогноз", ylabel="Факт")
for i in range(4):
    for j in range(4):
        ax.text(j, i, matrix[i, j], ha="center", va="center", color="white" if matrix[i, j] > 120 else "black")
fig.savefig(FIG / "confusion_matrix.png")'''),
    ("code", "details", '''\
# Подробности об ошибке лучшей модели и проверка самопроверки
print({k: round(v, 1) for k, v in m["best_details"].items() if isinstance(v, float)})
print("MAPE по классам:", {k: round(v, 1) for k, v in m["best_details"]["by_class_mape"].items()})
print("Самопроверка на тесте:", m.get("self_check_on_test"))'''),
    ("code", "fig_pred", '''\
# Прогноз и факт на тестовой выборке
pred = np.exp(model.predict(test[m["features"]]))
fig, ax = plt.subplots(figsize=(6, 5))
ax.scatter(test.price / 1000, pred / 1000, s=8, alpha=.45, color=BLUE)
lim = [20, 500]
ax.plot(lim, lim, "--", color=NAVY, label="идеальный прогноз")
ax.set(xscale="log", yscale="log", xlim=lim, ylim=lim, xlabel="Фактическая цена, тыс. руб. в месяц", ylabel="Прогноз, тыс. руб. в месяц")
ax.set_xticks([25, 50, 100, 200, 400], ["25", "50", "100", "200", "400"]); ax.set_yticks([25, 50, 100, 200, 400], ["25", "50", "100", "200", "400"])
ax.legend(frameon=False)
fig.savefig(FIG / "pred_vs_true.png")'''),
    ("code", "fig_importance", '''\
# Важность признаков методом перестановки
names = {"area_total": "Общая площадь", "dist_center_km": "Расстояние до центра", "built_year": "Год постройки",
         "renovation": "Тип ремонта", "longitude": "Долгота", "latitude": "Широта", "building_type": "Тип дома",
         "floors_total": "Этажность", "okrug": "Округ", "rooms": "Число комнат", "floor": "Этаж",
         "metro_minutes": "Минут до метро", "metro_transport": "Способ добраться до метро"}
imp = pd.Series(m["best_details"]["importance"])
print(imp.round(4).to_string())
fig, ax = plt.subplots(figsize=(8, 4.2))
ax.barh([names[k] for k in imp.index[::-1]], imp.values[::-1], color=BLUE)
ax.set(xlabel="Рост MAE логарифма цены при перемешивании признака")
fig.savefig(FIG / "importance.png")'''),
    ("code", "fig_models", '''\
# Сравнение моделей
fig, ax = plt.subplots(figsize=(8, 3.6))
items = [k for k in m["results"] if not k.startswith("Базовая")]
x = np.arange(len(items))
ax.bar(x - .2, [m["results"][k]["train"]["MAPE"] for k in items], .4, label="обучающая выборка", color=YELLOW)
ax.bar(x + .2, [m["results"][k]["test"]["MAPE"] for k in items], .4, label="тестовая выборка", color=BLUE)
ax.set_xticks(x, items); ax.set_ylabel("MAPE, процентов"); ax.legend(frameon=False)
fig.savefig(FIG / "models_mape.png")'''),
    ("code", "examples", '''\
# Примеры прогнозов с самопроверкой (журнал прогнозов в блокноте не пополняется)
from predictor import Flat, RentPredictor
predictor = RentPredictor()
predictor.monitor.log = lambda *a, **k: None
cases = [("студия, 28 кв. м, ЮВАО", dict(area_total=28, rooms=0, floor=7, floors_total=17, built_year=2015, metro_minutes=10), predictor.resolver.by_filter("ЮВАО")),
         ("1 комн., 40 кв. м, станция Отрадное", dict(area_total=40, rooms=1, floor=5, floors_total=12, built_year=1985, metro_minutes=8, building_type="Панельный", renovation="Косметический"), predictor.resolver.by_station("Отрадное")),
         ("2 комн., 60 кв. м, 10 км от центра", dict(area_total=60, rooms=2, floor=9, floors_total=25, built_year=2018, metro_minutes=10), predictor.resolver.by_filter(distance=10)),
         ("3 комн., 90 кв. м, ЦАО", dict(area_total=90, rooms=3, floor=4, floors_total=9, built_year=2005, metro_minutes=7, renovation="Дизайнерский"), predictor.resolver.by_filter("ЦАО")),
         ("2 комн., 290 кв. м, ЦАО", dict(area_total=290, rooms=2, floor=4, floors_total=9, built_year=2005, metro_minutes=7), predictor.resolver.by_filter("ЦАО"))]
for name, values, place in cases:
    r = predictor.predict(Flat(**values), place)
    print(f"{name:38} {r['price']:9.0f} руб. {r['class_name']:8} {r['check']['status']}", [n for n, ok, _ in r["check"]["items"] if not ok])'''),
]

NOTEBOOKS = {"01": ("01_слои_и_качество_данных.ipynb", NB1), "02": ("02_разведочный_анализ.ipynb", NB2),
             "03": ("03_модели.ipynb", NB3)}


def build(filename, cells):
    nb = nbformat.v4.new_notebook()
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    for cell in cells:
        if cell[0] == "md":
            nb.cells.append(nbformat.v4.new_markdown_cell(cell[1]))
        else:
            c = nbformat.v4.new_code_cell(cell[2])
            c.metadata["name"] = cell[1]
            nb.cells.append(c)
    NotebookClient(nb, timeout=900, kernel_name="python3", resources={"metadata": {"path": str(NB_DIR)}}).execute()
    nbformat.write(nb, NB_DIR / filename)
    print("Готово:", filename)


if __name__ == "__main__":
    for key in sys.argv[1:] or NOTEBOOKS:
        build(*NOTEBOOKS[key])
