-- Схема базы данных объявлений об аренде квартир (Москва), СУБД PostgreSQL.
-- Серебряный слой: load_runs, offers, price_history. Золотой слой: offers_model.
-- Персональных данных в базе нет: номер объявления и адрес заменены псевдонимами.

-- 1. Журнал загрузок: одна строка = один сбор данных с сайта.
CREATE TABLE IF NOT EXISTS load_runs (
    run_id          SERIAL PRIMARY KEY,
    source          TEXT        NOT NULL,          -- источник данных
    file_name       TEXT        NOT NULL UNIQUE,   -- файл бронзового слоя (повторно не загружается)
    collected_at    TIMESTAMP   NOT NULL,          -- дата и время сбора
    loaded_at       TIMESTAMP   NOT NULL DEFAULT now(), -- дата и время загрузки в базу
    offers_count    INTEGER     NOT NULL DEFAULT 0, -- сколько объявлений в загрузке
    new_offers      INTEGER     NOT NULL DEFAULT 0, -- сколько из них новых
    price_changes   INTEGER     NOT NULL DEFAULT 0  -- у скольких изменилась цена
);

-- 2. Объявления: характеристики квартиры, которые почти не меняются.
CREATE TABLE IF NOT EXISTS offers (
    offer_key        TEXT PRIMARY KEY,             -- псевдоним номера объявления
    building_key     TEXT NOT NULL,                -- псевдоним адреса дома
    in_moscow        BOOLEAN NOT NULL,             -- FALSE = Московская область
    rooms            SMALLINT,                     -- 0 = студия
    open_plan        BOOLEAN,
    area_total       NUMERIC(7, 2),                -- кв. м
    area_living      NUMERIC(7, 2),
    area_kitchen     NUMERIC(7, 2),
    ceiling_height   NUMERIC(5, 2),                -- м
    floor            SMALLINT,
    floors_total     SMALLINT,
    renovation       TEXT,
    has_furniture    BOOLEAN,
    has_fridge       BOOLEAN,
    has_washer       BOOLEAN,
    has_dishwasher   BOOLEAN,
    has_aircon       BOOLEAN,
    has_tv           BOOLEAN,
    has_internet     BOOLEAN,
    bathroom         TEXT,
    window_view      TEXT,
    is_apartments    BOOLEAN,
    built_year       SMALLINT,
    building_type    TEXT,
    has_lift         BOOLEAN,
    has_parking      BOOLEAN,
    pets_allowed     BOOLEAN,
    children_allowed BOOLEAN,
    min_rent_period  SMALLINT,                     -- минимальный срок аренды, мес.
    okrug            TEXT,
    district         TEXT,
    dist_center_km   NUMERIC(6, 2),                -- расстояние до центра Москвы, км
    latitude         DOUBLE PRECISION,             -- округлено до 3 знаков (около 100 м)
    longitude        DOUBLE PRECISION,
    metro            TEXT,
    metro_minutes    SMALLINT,
    metro_transport  TEXT,
    author_type      TEXT,
    created_on_site  TIMESTAMPTZ,                  -- дата размещения объявления
    first_seen_run   INTEGER NOT NULL REFERENCES load_runs(run_id),
    last_seen_run    INTEGER NOT NULL REFERENCES load_runs(run_id),
    is_active        BOOLEAN NOT NULL DEFAULT TRUE -- TRUE = было в последнем сборе
);

-- 3. История цен: цена объявления в каждом сборе.
CREATE TABLE IF NOT EXISTS price_history (
    offer_key          TEXT    NOT NULL REFERENCES offers(offer_key),
    run_id             INTEGER NOT NULL REFERENCES load_runs(run_id),
    price              INTEGER NOT NULL CHECK (price > 0), -- руб. в месяц
    agent_fee          NUMERIC(6, 2),                       -- комиссия агента
    utilities_included BOOLEAN,                             -- коммунальные платежи включены
    updated_on_site    TIMESTAMPTZ,                         -- дата обновления объявления на сайте
    PRIMARY KEY (offer_key, run_id)
);

-- 4. Результаты проверок качества данных.
CREATE TABLE IF NOT EXISTS quality_checks (
    checked_at  TIMESTAMP NOT NULL DEFAULT now(),
    source      TEXT NOT NULL,      -- проверенный файл или слой
    check_name  TEXT NOT NULL,      -- название проверки
    value       DOUBLE PRECISION,   -- измеренное значение
    threshold   DOUBLE PRECISION,   -- порог
    status      TEXT NOT NULL CHECK (status IN ('норма', 'внимание', 'ошибка')),
    details     TEXT
);

-- 5. Журнал запусков конвейера.
CREATE TABLE IF NOT EXISTS pipeline_runs (
    started_at  TIMESTAMP NOT NULL,
    finished_at TIMESTAMP NOT NULL DEFAULT now(),
    status      TEXT NOT NULL,      -- завершён, отклонён, ошибка
    details     TEXT
);

CREATE INDEX IF NOT EXISTS idx_price_history_run ON price_history(run_id);
CREATE INDEX IF NOT EXISTS idx_offers_active ON offers(is_active);
CREATE INDEX IF NOT EXISTS idx_offers_building ON offers(building_key);

-- 6. Представление для анализа и обучения модели:
--    активные объявления с ценой из последнего сбора.
CREATE OR REPLACE VIEW v_offers_current AS
SELECT o.*,
       p.price,
       p.agent_fee,
       p.utilities_included,
       p.updated_on_site
FROM offers o
JOIN price_history p
  ON p.offer_key = o.offer_key
 AND p.run_id = o.last_seen_run
WHERE o.is_active;

-- 7. Разграничение доступа: роль только для чтения.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rent_reader') THEN
        CREATE ROLE rent_reader NOLOGIN;
    END IF;
END $$;
GRANT USAGE ON SCHEMA public TO rent_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO rent_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO rent_reader;
