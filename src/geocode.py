"""
Поиск координат по адресу квартиры.

Адрес отправляется в открытую службу Nominatim (данные OpenStreetMap), только когда пользователь
его ввёл. Если служба недоступна или адрес не найден, приложение сообщает об этом.
"""

import requests

URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "VKR-rent-price-moscow/1.0"}


def geocode(address):
    """Адрес -> {"lat", "lon", "name"} или None, если адрес не найден или служба недоступна."""
    text = address if "моск" in address.lower() else f"{address}, Москва"
    try:
        resp = requests.get(URL, params={"q": text, "format": "json", "limit": 1, "countrycodes": "ru"},
                            headers=HEADERS, timeout=10)
        resp.raise_for_status()
        found = resp.json()
    except (requests.RequestException, ValueError):
        return None
    if not found:
        return None
    return {"lat": float(found[0]["lat"]), "lon": float(found[0]["lon"]), "name": found[0]["display_name"]}
