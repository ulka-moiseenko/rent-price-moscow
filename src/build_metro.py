"""
Справочник станций метро: название, координаты, расстояние до центра.

Станции берутся из бронзового слоя, сохраняются в data/reference/metro_stations.csv и таблицу metro_stations.

Запуск:
    venv\\Scripts\\python.exe src\\build_metro.py
"""

import json
from pathlib import Path

import pandas as pd

from db import connect
from lake import BRONZE_DIR, distance_km

OUT_CSV = Path(__file__).resolve().parent.parent / "data" / "reference" / "metro_stations.csv"


def collect_stations():
    """Все станции из файлов бронзового слоя: название, координаты, сколько раз встретилась."""
    rows = []
    for path in sorted(BRONZE_DIR.glob("offers_*.jsonl")):
        with open(path, encoding="utf-8") as f:
            for line in f:
                for m in json.loads(line)["location"].get("metroList", []):
                    if m.get("latitude") and m.get("longitude"):
                        rows.append((m["name"], m["latitude"], m["longitude"]))
    df = pd.DataFrame(rows, columns=["name", "latitude", "longitude"])
    stations = (df.groupby("name").agg(latitude=("latitude", "median"), longitude=("longitude", "median"),
                                       mentions=("name", "size")).reset_index())
    stations["dist_center_km"] = [round(distance_km(a, b), 2) for a, b in zip(stations["latitude"], stations["longitude"])]
    return stations.sort_values("name").reset_index(drop=True)


def save(stations):
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    stations.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    with connect() as conn:
        conn.execute("DROP TABLE IF EXISTS metro_stations")
        conn.execute("""
            CREATE TABLE metro_stations (
                name TEXT PRIMARY KEY, latitude DOUBLE PRECISION NOT NULL, longitude DOUBLE PRECISION NOT NULL,
                mentions INTEGER NOT NULL, dist_center_km NUMERIC(6, 2) NOT NULL)""")
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO metro_stations VALUES (%s, %s, %s, %s, %s)",
                            [(r.name, float(r.latitude), float(r.longitude), int(r.mentions), float(r.dist_center_km))
                             for r in stations.itertuples()])
    print(f"Станций: {len(stations)}. Сохранено: {OUT_CSV.name} и таблица metro_stations")


if __name__ == "__main__":
    save(collect_stations())
