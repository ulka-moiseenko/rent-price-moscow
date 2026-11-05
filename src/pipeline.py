"""
Конвейер данных: один запуск выполняет все этапы по порядку.

1. Резервная копия базы и модели.
2. Сбор свежих объявлений в бронзовый слой без персональных данных.
3. Контроль качества. При ошибке файл откладывается в data/bronze/rejected и в базу не попадает.
4. Загрузка в серебряный слой: новые объявления добавляются, изменения цен попадают в историю,
   снятые объявления отмечаются неактивными. Выгрузка в data/silver.
5. Обновление справочника станций и подготовка золотого слоя.
6. Переобучение модели. Прежняя модель сохраняется в models/archive; если новая ошибается заметно
   сильнее (MAPE выше более чем на 10 процентов), прежняя возвращается на место.

Журнал пишется в logs/pipeline.log и таблицу pipeline_runs. При ошибке следующие этапы не выполняются.

Запуск (полный, около полутора часов):
    venv\\Scripts\\python.exe src\\pipeline.py
Без сбора, на уже загруженных данных:
    venv\\Scripts\\python.exe src\\pipeline.py --skip-collect
Перед запуском программа просит подтверждение, потому что меняет данные и модель.
Без вопроса, например при запуске по расписанию:
    venv\\Scripts\\python.exe src\\pipeline.py --yes
"""

import argparse
import json
import logging
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from backup import create_backup
from db import connect
from lake import BRONZE_DIR, SILVER_CSV, DataLakeManager
from quality import QualityError, QualityGate

PROJECT_DIR = Path(__file__).resolve().parent.parent
MODEL_DIR = PROJECT_DIR / "models"
LOG_PATH = PROJECT_DIR / "logs" / "pipeline.log"
MODEL_FILES = ("model.joblib", "control_linear.joblib", "model_info.json")
MAX_WORSE = 1.10       # во сколько раз новая модель может быть хуже прежней


def make_logger():
    LOG_PATH.parent.mkdir(exist_ok=True)
    logger = logging.getLogger("pipeline")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
        for handler in (logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler(sys.stdout)):
            handler.setFormatter(fmt)
            logger.addHandler(handler)
    return logger


class PipelineRunner:
    """Выполняет этапы конвейера и ведёт журнал."""

    def __init__(self, max_pages=25, skip_collect=False):
        self.max_pages, self.skip_collect = max_pages, skip_collect
        self.log = make_logger()
        self.started = datetime.now()
        self.lake = DataLakeManager()

    def run_script(self, script, *args):
        self.log.info("Этап %s %s", script, " ".join(args))
        subprocess.run([sys.executable, str(PROJECT_DIR / "src" / script), *args], check=True, cwd=PROJECT_DIR)

    def collect_and_load(self):
        """Сбор, контроль качества и загрузка. Возвращает False, если файл отклонён."""
        before = set(BRONZE_DIR.glob("offers_*.jsonl"))
        self.run_script("collect_yandex.py", "--max-pages", str(self.max_pages))
        new = sorted(set(BRONZE_DIR.glob("offers_*.jsonl")) - before)
        if not new:
            raise RuntimeError("сбор не создал файл с объявлениями")
        path = new[-1]
        df = self.lake.read_bronze(path)
        reference = None
        if SILVER_CSV.exists():
            import pandas as pd
            reference = pd.read_csv(SILVER_CSV, encoding="utf-8-sig", low_memory=False)
        self.log.info("Собрано %d объявлений, в прошлом сборе %d", len(df), self.lake.previous_count())
        try:
            report = QualityGate(path.name).check(df, self.lake.collected_at(path), self.lake.previous_count(), reference)
        except QualityError as error:
            rejected = BRONZE_DIR / "rejected"
            rejected.mkdir(exist_ok=True)
            shutil.move(path, rejected / path.name)
            self.log.warning("Контроль качества не пройден (%s). Файл отложен в %s, база и модель не изменены", error, rejected)
            return False
        for row in report[report["status"] == "внимание"].itertuples():
            self.log.warning("Внимание: %s = %.3f", row.check_name, row.value)
        self.lake.load_silver(path, df)
        self.lake.export_silver()
        return True

    def train_with_check(self):
        """Переобучение: прежняя модель архивируется и возвращается, если новая заметно хуже."""
        info_path = MODEL_DIR / "model_info.json"
        archive = MODEL_DIR / "archive" / f"{datetime.now():%Y-%m-%d_%H%M}"
        archive.mkdir(parents=True)
        for name in MODEL_FILES:
            shutil.copy2(MODEL_DIR / name, archive / name)
        old = json.loads(info_path.read_text(encoding="utf-8"))["ошибки на тесте"]["MAPE"]
        self.run_script("train.py")
        new = json.loads(info_path.read_text(encoding="utf-8"))["ошибки на тесте"]["MAPE"]
        self.log.info("MAPE на тесте: прежняя модель %.2f, новая %.2f", old, new)
        if new > old * MAX_WORSE:
            for name in MODEL_FILES:
                shutil.copy2(archive / name, MODEL_DIR / name)
            self.log.warning("Новая модель заметно хуже: возвращена прежняя")
            return "возвращена прежняя модель"
        self.log.info("Новая модель принята")
        return "новая модель принята"

    def save_run(self, status, details):
        with connect() as conn:
            conn.execute("INSERT INTO pipeline_runs (started_at, status, details) VALUES (%s, %s, %s)",
                         (self.started, status, details))

    def run(self):
        self.log.info("Запуск конвейера")
        try:
            create_backup()
            self.log.info("Резервная копия создана")
            if not self.skip_collect and not self.collect_and_load():
                self.save_run("отклонён", "контроль качества не пройден")
                return
            self.run_script("build_metro.py")
            self.run_script("preprocess.py")
            details = self.train_with_check()
        except Exception as error:
            self.log.error("Конвейер остановлен: %s", error)
            self.save_run("ошибка", str(error)[:500])
            raise SystemExit(1)
        self.save_run("завершён", details)
        self.log.info("Конвейер завершён. Чтобы приложение взяло новую модель, перезапустите его")


def confirm():
    """Защита от случайного запуска: продолжаем только после явного ответа."""
    print("Конвейер обновит данные в базе и модель, это занимает около полутора часов.")
    try:
        answer = input("Для запуска введите ДА (или YES), для отмены нажмите Enter: ")
    except EOFError:
        answer = ""
    return answer.strip().upper() in ("ДА", "YES")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-collect", action="store_true", help="не собирать данные с сайта")
    parser.add_argument("--max-pages", type=int, default=25, help="страниц на сегмент при сборе")
    parser.add_argument("--yes", action="store_true", help="запуск без вопроса (для расписания)")
    args = parser.parse_args()
    if not args.yes and not confirm():
        print("Запуск отменён, ничего не изменилось.")
    else:
        PipelineRunner(args.max_pages, args.skip_collect).run()
