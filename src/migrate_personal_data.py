"""
Разовый перенос: старые сырые файлы с персональными данными -> бронзовый слой без них,
затем пересоздание базы и загрузка очищенных файлов в том же порядке.
"""

import json
from pathlib import Path

from db import connect
from lake import BRONZE_DIR, DataLakeManager
from quality import QualityGate
from security import PersonalDataGuard

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


def migrate():
    guard = PersonalDataGuard()
    BRONZE_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(RAW_DIR.glob("offers_*.jsonl")):
        target = BRONZE_DIR / path.name
        with open(path, encoding="utf-8") as src, open(target, "w", encoding="utf-8") as dst:
            for line in src:
                dst.write(json.dumps(guard.sanitize_offer(json.loads(line)), ensure_ascii=False) + "\n")
        print(f"{path.name}: {path.stat().st_size / 1e6:.0f} МБ -> {target.stat().st_size / 1e6:.0f} МБ")
    with connect() as conn:
        conn.execute("DROP VIEW IF EXISTS v_offers_current")
        conn.execute("DROP TABLE IF EXISTS offers_model, model_runs, metro_stations, price_history, offers, "
                     "load_runs, quality_checks, pipeline_runs CASCADE")
    lake = DataLakeManager()
    for path in sorted(BRONZE_DIR.glob("offers_*.jsonl")):
        df = lake.read_bronze(path)
        report = QualityGate(path.name).check(df, lake.collected_at(path), lake.previous_count(),
                                              stop_on_error=False)
        print(report[["check_name", "value", "threshold", "status", "details"]].to_string(index=False))
        lake.load_silver(path, df)
    lake.export_silver()


if __name__ == "__main__":
    migrate()
