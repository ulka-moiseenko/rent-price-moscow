"""
Защита персональных данных.

В объявлениях встречаются имена авторов, их фото, зашифрованные телефоны и адреса домов.
В модели они не используются, поэтому уже при сборе в бронзовый слой попадает только белый
список полей. Адрес и номер объявления нужны для поиска повторов и обновления базы, поэтому
они заменяются псевдонимом: кодом HMAC-SHA256 с секретным ключом PII_KEY из файла .env.
Без ключа восстановить исходное значение или сопоставить его с другим набором нельзя.
Координаты округляются до трёх знаков, это около 100 м.
"""

import hashlib
import hmac
import os
import re
import secrets

from db import ENV_PATH, read_env

# Поля объявления, которые разрешено сохранять
TOP_FIELDS = ["area", "livingSpace", "kitchenSpace", "floorsOffered", "floorsTotal", "roomsTotal",
              "roomsTotalKey", "openPlan", "minRentPeriod", "agentFee", "utilitiesIncluded",
              "ceilingHeight", "creationDate", "updateDate", "price", "rentConditionsMap", "apartment",
              "house"]
BUILDING_FIELDS = ["builtYear", "buildingType", "improvements"]
FORBIDDEN_COLUMNS = {"url", "address", "description", "author_name", "phone", "offer_id"}
PHONE = r"(?:\+7|\b8)[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}"
EMAIL = r"[\w.\-]+@[\w\-]+\.\w+"
COORD_DIGITS = 3


class PersonalDataGuard:
    """Удаляет персональные данные и заменяет идентификаторы псевдонимами."""

    def __init__(self):
        read_env()
        if not os.environ.get("PII_KEY"):
            key = secrets.token_hex(32)
            with open(ENV_PATH, "a", encoding="utf-8") as f:
                f.write(f"\nPII_KEY={key}\n")
            os.environ["PII_KEY"] = key
        self._key = os.environ["PII_KEY"].encode()

    def pseudonym(self, value):
        """Постоянный псевдоним значения: одно и то же значение даёт один и тот же код."""
        return hmac.new(self._key, str(value).encode("utf-8"), hashlib.sha256).hexdigest()[:20]

    def sanitize_offer(self, offer):
        """Объявление с сайта -> запись бронзового слоя без персональных данных."""
        clean = {field: offer[field] for field in TOP_FIELDS if field in offer}
        loc = offer.get("location") or {}
        point = loc.get("point") or {}
        metro = loc.get("metro") or {}
        address = loc.get("address")
        clean["offerKey"] = self.pseudonym(offer.get("offerId"))
        clean["buildingKey"] = self.pseudonym(address) if address else clean["offerKey"]
        clean["inMoscow"] = "Московская область" not in (loc.get("geocoderAddress") or "")
        clean["authorType"] = (offer.get("author") or {}).get("category")
        clean["building"] = {k: v for k, v in (offer.get("building") or {}).items() if k in BUILDING_FIELDS}
        clean["location"] = {
            "point": {k: round(point[k], COORD_DIGITS) for k in ("latitude", "longitude") if point.get(k)},
            "metro": {k: metro[k] for k in ("name", "timeToMetro", "metroTransport") if k in metro},
            "metroList": [{k: m.get(k) for k in ("name", "latitude", "longitude")}
                          for m in loc.get("metroList") or []],
            "districts": [c.get("address") for c in (loc.get("structuredAddress") or {}).get("component", [])
                          if c.get("regionType") == "SUBJECT_FEDERATION_DISTRICT"],
        }
        return clean

    @staticmethod
    def find_personal_data(df):
        """Проверка таблицы: запрещённые столбцы и телефоны или почта в текстовых значениях."""
        problems = [f"столбец {c}" for c in df.columns if c in FORBIDDEN_COLUMNS]
        for col in df.select_dtypes(include=["object", "string"]).columns.difference(["offer_key", "building_key"]):
            values = df[col].dropna().astype(str)
            hits = values.str.contains(PHONE, regex=True).sum() + values.str.contains(EMAIL, regex=True).sum()
            if hits:
                problems.append(f"{col}: совпадений {int(hits)}")
        return problems
