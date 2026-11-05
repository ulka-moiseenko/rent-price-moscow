"""
Приложение «Прогноз стоимости аренды квартиры в Москве».

Пользователь выбирает параметры квартиры в форме и получает цену, ценовой класс, диапазон
и итог самопроверки прогноза.

Запуск (из папки проекта):
    venv\\Scripts\\streamlit.exe run app.py
или двойной щелчок по файлу «Запустить приложение.bat». Адрес страницы: http://localhost:8501.
"""

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from geo import OKRUGS  # noqa: E402
from geocode import geocode  # noqa: E402
from predictor import BUILDING, RENOVATION, TRANSPORT, Flat, RentPredictor  # noqa: E402

st.set_page_config(page_title="Прогноз аренды квартиры", page_icon="🏠", layout="wide")

WINE, WINE_DARK, GRAPHITE, STEEL, SILVER, GREEN, AMBER = ("#8E1B3A", "#5E0F26", "#2B2E35", "#6B7280", "#D5D9DF",
                                                          "#2F7D5B", "#B8651B")
CLASS_COLORS = ["#E7C9D1", "#CF8FA1", "#AE4A66", "#8E1B3A"]
st.markdown(f"""
<style>
.stApp {{ background: linear-gradient(160deg, #F1F2F5 0%, #E2E5EA 55%, #D5D9DF 100%); }}
header[data-testid="stHeader"] {{ background: transparent; }}
.block-container {{ padding-top: 1.4rem; max-width: 1260px; }}
.hero {{ background: linear-gradient(120deg, {WINE_DARK} 0%, {WINE} 60%, #B33A5B 100%); border-radius: 16px;
         padding: 20px 28px; margin-bottom: 14px; box-shadow: 0 6px 18px rgba(94, 15, 38, .28); }}
.hero b {{ font-size: 1.8rem; color: #fff; }}
.hero span {{ display: block; color: #F1DCE2; font-size: .92rem; margin-top: 4px; }}
.tiles {{ display: flex; gap: 12px; margin-bottom: 18px; }}
.tile {{ flex: 1; border-radius: 14px; padding: 12px 16px; border: 1px solid #C4C9D1;
         background: linear-gradient(145deg, #FFFFFF 0%, #E9EBEF 100%); box-shadow: 0 2px 6px rgba(43, 46, 53, .10); }}
.tile small {{ color: {STEEL}; font-size: .78rem; display: block; }}
.tile b {{ color: {WINE}; font-size: 1.32rem; }}
.card {{ border-radius: 14px; padding: 16px 20px; margin-bottom: 14px; border: 1px solid #C4C9D1;
         background: linear-gradient(160deg, #FFFFFF 0%, #F0F1F4 100%); box-shadow: 0 3px 10px rgba(43, 46, 53, .12); }}
.card h4 {{ margin: 0 0 10px 0; padding: 0 0 7px 0; color: {WINE}; font-size: .84rem; letter-spacing: .06em;
            text-transform: uppercase; border-bottom: 2px solid {WINE}; }}
.price-card {{ background: linear-gradient(130deg, {GRAPHITE} 0%, #43474F 100%); border: none; }}
.price-card h4 {{ color: {SILVER}; border-color: {SILVER}; }}
.price {{ font-size: 2.8rem; font-weight: 800; color: #fff; line-height: 1.1; }}
.price-card .sub {{ color: {SILVER}; }}
.sub {{ color: {STEEL}; font-size: .94rem; }}
.scale {{ display: flex; gap: 5px; }}
.seg {{ flex: 1; border-radius: 9px; padding: 9px 4px; text-align: center; font-size: .78rem; color: {STEEL};
        background: #E4E6EA; }}
.seg b {{ display: block; font-size: .92rem; color: {GRAPHITE}; }}
.seg.on {{ color: #fff; box-shadow: 0 2px 6px rgba(94, 15, 38, .35); }}
.seg.on b {{ color: #fff; }}
.check {{ font-size: .9rem; padding: 4px 0; color: {GRAPHITE}; }}
.badge {{ display: inline-block; padding: 3px 14px; border-radius: 20px; color: #fff; font-weight: 700; font-size: .84rem;
          margin-bottom: 6px; }}
div[data-testid="stVerticalBlockBorderWrapper"] {{ background: linear-gradient(160deg, #FFFFFF 0%, #EEF0F3 100%);
        border-color: #C4C9D1 !important; border-radius: 14px; box-shadow: 0 3px 10px rgba(43, 46, 53, .12); }}
.section {{ color: {WINE}; font-weight: 700; font-size: 1rem; border-left: 4px solid {WINE}; padding-left: 8px; margin: 6px 0; }}
div[data-baseweb="select"] > div, div[data-baseweb="input"], div[data-testid="stNumberInputContainer"] {{ background: #fff !important; }}
.stButton button[kind="primary"] {{ background: linear-gradient(120deg, {WINE_DARK}, {WINE}); border: none; font-weight: 700; }}
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_predictor():
    """Модель и справочники загружаются один раз при запуске приложения."""
    return RentPredictor()


@st.cache_data(show_spinner="Ищу адрес на карте")
def find_address(address):
    return geocode(address)


def rub(x):
    return f"{x:,.0f} ₽".replace(",", " ")


def num(x, digits=1):
    return f"{x:.{digits}f}".replace(".", ",")


predictor = get_predictor()
info = predictor.info
gold = predictor.train
stations = sorted(predictor.resolver.stations.index)
ROOMS = ["Студия", "1", "2", "3", "4", "5 и более"]
MODES = ["Округ или удалённость", "Станция метро", "Адрес"]
OKRUG_OPTIONS = ["Любой"] + list(OKRUGS)

st.markdown(f"""<div class="hero"><b>Прогноз стоимости аренды квартиры в Москве</b>
<span>Выберите параметры квартиры: система рассчитает цену в месяц и ценовой класс.</span></div>
<div class="tiles">
<div class="tile"><small>Медианная цена в данных</small><b>{rub(gold['price'].median())}</b></div>
<div class="tile"><small>Медиана за 1 кв. м</small><b>{rub((gold['price'] / gold['area_total']).median())}</b></div>
<div class="tile"><small>Объявлений в обучении</small><b>{info['объявлений в обучении']:,}</b></div>
<div class="tile"><small>Средняя ошибка на тесте</small><b>{num(info['ошибки на тесте']['MAPE'])} процента</b></div>
<div class="tile"><small>Модель обучена</small><b>{datetime.fromisoformat(info['обучена']):%d.%m.%Y}</b></div>
</div>""".replace(f"{info['объявлений в обучении']:,}", f"{info['объявлений в обучении']:,}".replace(",", " ")),
            unsafe_allow_html=True)

left, right = st.columns([5, 6], gap="large")

with left, st.container(border=True):
    st.markdown('<div class="section">Квартира</div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    rooms = c1.selectbox("Число комнат", ROOMS, index=2)
    area = c2.number_input("Общая площадь, кв. м", 12.0, 300.0, 50.0, 1.0)
    c1, c2 = st.columns(2)
    floor = c1.number_input("Этаж", 1, 95, 5)
    floors = c2.number_input("Этажей в доме", 1, 100, 17)
    renovation = st.selectbox("Ремонт", list(RENOVATION))
    st.markdown('<div class="section">Дом</div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    building = c1.selectbox("Тип дома", list(BUILDING))
    year_known = st.checkbox("Год постройки известен", value=True)
    year = c2.number_input("Год постройки", 1800, 2030, 2010, disabled=not year_known)
    st.markdown('<div class="section">Расположение</div>', unsafe_allow_html=True)
    mode = st.radio("Как указать расположение", MODES, horizontal=True, label_visibility="collapsed")
    okrug, use_distance, distance, station, address = "ЗАО", False, 10.0, "Тверская", ""
    if mode == MODES[0]:
        okrug = st.selectbox("Административный округ", OKRUG_OPTIONS, index=OKRUG_OPTIONS.index("ЗАО"))
        use_distance = st.checkbox("Указать удалённость от центра")
        if use_distance:
            distance = st.slider("Удалённость от центра, км", 0.0, 50.0, 10.0, 0.5)
    elif mode == MODES[1]:
        station = st.selectbox("Станция метро или МЦК/МЦД", stations, index=stations.index("Тверская"))
    else:
        address = st.text_input("Адрес дома", placeholder="Москва, улица Новый Арбат, 15",
                                help="Адрес отправляется в службу OpenStreetMap. Номер квартиры указывать не нужно.")
    c1, c2 = st.columns(2)
    minutes = c1.number_input("Минут до метро", 1, 60, 10)
    transport = c2.radio("Как добираться", list(TRANSPORT), horizontal=True)
    calc = st.button("Рассчитать цену", type="primary", use_container_width=True)


def resolve_location():
    resolver = predictor.resolver
    if mode == MODES[1]:
        return resolver.by_station(station)
    if mode == MODES[2]:
        if not address.strip():
            raise ValueError("укажите адрес дома")
        place = find_address(address.strip())
        if not place:
            raise ValueError("адрес не найден или служба карт недоступна; выберите станцию или округ")
        return resolver.by_coordinates(place["lat"], place["lon"], place["name"])
    chosen = None if okrug == "Любой" else okrug
    if chosen is None and not use_distance:
        raise ValueError("выберите округ или укажите удалённость от центра")
    return resolver.by_filter(chosen, distance if use_distance else None)


with right:
    if calc or st.query_params.get("calc") == "1":
        flat = Flat(area_total=area, rooms=ROOMS.index(rooms), floor=floor, floors_total=floors,
                    built_year=year if year_known else None, metro_minutes=minutes, metro_transport=transport,
                    renovation=renovation, building_type=building)
        try:
            st.session_state["result"] = predictor.predict(flat, resolve_location())
            st.session_state["result_area"] = area
            st.session_state.pop("error", None)
        except ValueError as error:
            st.session_state["error"] = str(error)
            st.session_state.pop("result", None)

    if "error" in st.session_state:
        st.error(f"Проверьте параметры: {st.session_state['error']}")
    result = st.session_state.get("result")
    if result is None:
        st.markdown("""<div class="card"><h4>Результат</h4><div class="sub">Заполните параметры и нажмите
        «Рассчитать цену». Здесь появятся цена аренды, ценовой класс и итог самопроверки.</div></div>""",
                    unsafe_allow_html=True)
    else:
        loc = result["location"]
        bounds = info["классы"]["границы"]
        ranges = [f"до {bounds[0] / 1000:.0f} тыс.", f"{bounds[0] / 1000:.0f}–{bounds[1] / 1000:.0f} тыс.",
                  f"{bounds[1] / 1000:.0f}–{bounds[2] / 1000:.0f} тыс.", f"от {bounds[2] / 1000:.0f} тыс."]
        segs = ""
        for i, name in enumerate(info["классы"]["названия"]):
            active = i == result["class_number"]
            style = f' style="background:{CLASS_COLORS[i]}"' if active else ""
            segs += f'<div class="seg{" on" if active else ""}"{style}><b>{name}</b>{ranges[i]}</div>'
        st.markdown(f"""<div class="card price-card"><h4>Цена аренды в месяц</h4>
        <div class="price">{rub(result['price'])}</div>
        <div class="sub">Примерный диапазон {rub(result['low'])} – {rub(result['high'])}. Фактическая цена попадает в него
        примерно в 6 случаях из 10. Цена 1 кв. м {rub(result['price'] / st.session_state['result_area'])}.</div></div>
        <div class="card"><h4>Ценовой класс: {result['class_name']}</h4><div class="scale">{segs}</div></div>""",
                    unsafe_allow_html=True)
        check = result["check"]
        color = GREEN if check["status"] == "норма" else AMBER
        rows = "".join(f'<div class="check">{"✔" if ok else "⚠"} <b>{name}</b>: {text}</div>'
                       for name, ok, text in check["items"])
        st.markdown(f"""<div class="card"><h4>Самопроверка прогноза</h4>
        <span class="badge" style="background:{color}">{check['status'].capitalize()}</span>{rows}</div>""",
                    unsafe_allow_html=True)
        place = f"{loc.description}. До центра {num(loc.dist_center_km)} км, округ {loc.okrug}."
        st.markdown(f'<div class="card"><h4>Расположение</h4><div class="sub">{place}</div></div>', unsafe_allow_html=True)
        st.map(pd.DataFrame({"lat": [loc.latitude], "lon": [loc.longitude]}), zoom=11 if loc.exact else 10, height=240,
               color=WINE)
        if not loc.exact:
            st.caption("Точка показывает типичное расположение объявлений для выбранного условия, а не конкретный дом.")
