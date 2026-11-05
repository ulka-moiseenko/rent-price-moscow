"""
Управление слоями данных.

Бронзовый слой: data/bronze/offers_<дата>.jsonl, объявления без персональных данных как есть.
Серебряный слой: таблицы offers и price_history в PostgreSQL, выгрузка data/silver/offers_silver.csv.
Золотой слой (признаки для модели) готовит класс DataPreprocessor.

Загрузка:
    venv\\Scripts\\python.exe src\\lake.py data\\bronze\\offers_<дата>.jsonl
"""

import argparse
import json
import math
from datetime import datetime
from pathlib import Path

import pandas as pd

from db import connect, create_database_if_missing

PROJECT_DIR = Path(__file__).resolve().parent.parent
BRONZE_DIR = PROJECT_DIR / "data" / "bronze"
SILVER_CSV = PROJECT_DIR / "data" / "silver" / "offers_silver.csv"
SCHEMA_PATH = PROJECT_DIR / "sql" / "schema.sql"
SOURCE = "realty.yandex.ru"
CENTER = (55.7520, 37.6175)      # Кремль
PRICE_FIELDS = ["price", "agent_fee", "utilities_included", "updated_on_site"]
INT_FIELDS = ["rooms", "floor", "floors_total", "built_year", "min_rent_period", "metro_minutes", "price"]
LOADED = "уже загружен"


def distance_km(lat, lon, center=CENTER):
    """Расстояние по прямой между двумя точками на сфере (формула гаверсинусов), км."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*center, lat, lon))
    a = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * 6371 * math.asin(math.sqrt(a))


def flatten(offer):
    """Запись бронзового слоя (вложенный JSON) -> плоская строка серебряного слоя."""
    loc = offer.get("location") or {}
    metro = loc.get("metro") or {}
    point = loc.get("point") or {}
    building, apartment, house = (offer.get(k) or {} for k in ("building", "apartment", "house"))
    flat_impr, bld_impr = apartment.get("improvements") or {}, building.get("improvements") or {}
    conditions = offer.get("rentConditionsMap") or {}
    districts = loc.get("districts") or []
    floors = offer.get("floorsOffered") or [None]

    def value(field):
        return (offer.get(field) or {}).get("value")

    # У студий roomsTotal не заполнено, а roomsTotalKey = "studio": считаем 0 комнат
    rooms = offer.get("roomsTotal")
    if rooms is None and offer.get("roomsTotalKey") == "studio":
        rooms = 0
    lat, lon = point.get("latitude"), point.get("longitude")
    return {
        "offer_key": offer["offerKey"], "building_key": offer["buildingKey"], "in_moscow": offer["inMoscow"],
        "price": (offer.get("price") or {}).get("value"), "agent_fee": offer.get("agentFee"),
        "utilities_included": offer.get("utilitiesIncluded"), "min_rent_period": offer.get("minRentPeriod"),
        "rooms": rooms, "open_plan": offer.get("openPlan"), "area_total": value("area"),
        "area_living": value("livingSpace"), "area_kitchen": value("kitchenSpace"),
        "ceiling_height": offer.get("ceilingHeight"), "floor": floors[0],
        "floors_total": offer.get("floorsTotal"), "renovation": apartment.get("renovation"),
        "has_furniture": flat_impr.get("ROOM_FURNITURE"), "has_fridge": flat_impr.get("REFRIGERATOR"),
        "has_washer": flat_impr.get("WASHING_MACHINE"), "has_dishwasher": flat_impr.get("DISHWASHER"),
        "has_aircon": flat_impr.get("AIRCONDITION"), "has_tv": flat_impr.get("TELEVISION"),
        "has_internet": flat_impr.get("INTERNET"), "bathroom": house.get("bathroomUnit"),
        "window_view": house.get("windowView"), "is_apartments": house.get("apartments"),
        "built_year": building.get("builtYear"), "building_type": building.get("buildingType"),
        "has_lift": bld_impr.get("LIFT"), "has_parking": bld_impr.get("PARKING"),
        "pets_allowed": conditions.get("PETS"), "children_allowed": conditions.get("CHILDREN"),
        "okrug": districts[0] if len(districts) > 0 else None,
        "district": districts[1] if len(districts) > 1 else None,
        "dist_center_km": round(distance_km(lat, lon), 2) if lat and lon else None,
        "latitude": lat, "longitude": lon, "metro": metro.get("name"),
        "metro_minutes": metro.get("timeToMetro"), "metro_transport": metro.get("metroTransport"),
        "author_type": offer.get("authorType"), "created_on_site": offer.get("creationDate"),
        "updated_on_site": offer.get("updateDate"),
    }


class DataLakeManager:
    """Перемещает данные между слоями: бронза -> серебро (база и CSV)."""

    def __init__(self):
        create_database_if_missing()
        with connect() as conn:
            conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))

    @staticmethod
    def read_bronze(path):
        """Файл бронзового слоя -> таблица pandas."""
        with open(path, encoding="utf-8") as f:
            return pd.DataFrame([flatten(json.loads(line)) for line in f])

    @staticmethod
    def collected_at(path):
        """offers_2026-10-25_1742.jsonl -> datetime(2026, 10, 25, 17, 42)."""
        return datetime.strptime(Path(path).stem.replace("offers_", ""), "%Y-%m-%d_%H%M")

    @staticmethod
    def previous_count():
        with connect() as conn:
            row = conn.execute("SELECT offers_count FROM load_runs ORDER BY run_id DESC LIMIT 1").fetchone()
        return row[0] if row else 0

    @staticmethod
    def _rows(df):
        for col in INT_FIELDS:
            df[col] = df[col].astype("Int64")
        df = df.astype(object).where(df.notna(), None)
        return [{k: (v.item() if hasattr(v, "item") else v) for k, v in r.items()} for r in df.to_dict("records")]

    def load_silver(self, path, df=None):
        """Загружает файл бронзового слоя в базу. Повторный файл пропускается."""
        path = Path(path)
        df = self.read_bronze(path) if df is None else df
        rows = self._rows(df.copy())
        offer_cols = [c for c in rows[0] if c not in PRICE_FIELDS]
        with connect() as conn:
            conn.autocommit = True
            if conn.execute("SELECT 1 FROM load_runs WHERE file_name = %s", (path.name,)).fetchone():
                print(f"{path.name}: {LOADED}, пропускаю")
                return LOADED
            known = {r[0] for r in conn.execute("SELECT offer_key FROM offers")}
            last_price = dict(conn.execute(
                "SELECT o.offer_key, p.price FROM offers o JOIN price_history p "
                "ON p.offer_key = o.offer_key AND p.run_id = o.last_seen_run").fetchall())

            with conn.transaction():  # файл загрузится либо целиком, либо не загрузится совсем
                run_id = conn.execute(
                    "INSERT INTO load_runs (source, file_name, collected_at) VALUES (%s, %s, %s) RETURNING run_id",
                    (SOURCE, path.name, self.collected_at(path))).fetchone()[0]
                cols = offer_cols + ["first_seen_run", "last_seen_run", "is_active"]
                update = ", ".join(f"{c} = EXCLUDED.{c}" for c in offer_cols if c != "offer_key")
                with conn.cursor() as cur:
                    cur.executemany(
                        f"INSERT INTO offers ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
                        f"ON CONFLICT (offer_key) DO UPDATE SET {update}, "
                        "last_seen_run = EXCLUDED.last_seen_run, is_active = TRUE",
                        [[r[c] for c in offer_cols] + [run_id, run_id, True] for r in rows])
                    cur.executemany(
                        "INSERT INTO price_history (offer_key, run_id, price, agent_fee, utilities_included, "
                        "updated_on_site) VALUES (%s, %s, %s, %s, %s, %s)",
                        [[r["offer_key"], run_id] + [r[c] for c in PRICE_FIELDS] for r in rows])
                # Кого нет в этом сборе, отмечаем неактивными, но не удаляем
                conn.execute("UPDATE offers SET is_active = FALSE WHERE last_seen_run <> %s", (run_id,))
                new = sum(1 for r in rows if r["offer_key"] not in known)
                changed = sum(1 for r in rows if r["offer_key"] in last_price
                              and last_price[r["offer_key"]] != r["price"])
                conn.execute("UPDATE load_runs SET offers_count = %s, new_offers = %s, price_changes = %s "
                             "WHERE run_id = %s", (len(rows), new, changed, run_id))
        print(f"{path.name}: загружено {len(rows)}, новых {new}, изменилась цена у {changed}")
        return run_id

    @staticmethod
    def export_silver():
        """Выгружает актуальные объявления серебряного слоя в CSV для репозитория."""
        with connect() as conn:
            cur = conn.execute("SELECT * FROM v_offers_current ORDER BY offer_key")
            df = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
        SILVER_CSV.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(SILVER_CSV, index=False, encoding="utf-8-sig")
        print(f"Серебряный слой: {SILVER_CSV.relative_to(PROJECT_DIR)}, строк {len(df)}")
        return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", help="файл бронзового слоя")
    args = parser.parse_args()
    lake = DataLakeManager()
    lake.load_silver(args.file)
    lake.export_silver()
