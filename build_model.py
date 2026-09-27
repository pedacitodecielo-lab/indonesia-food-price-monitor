"""Build the analytics model in DuckDB (SQL) and export a star schema for Power BI.

Input:  prices_daily.csv (from scrape_pihps.py)
Output: food_prices.duckdb, plus model/ CSVs:
  dim_commodity, dim_region, dim_date   dimensions
  fact_price                            one row per commodity x region x day
  kpi_latest                            latest price, WoW / MoM / YoY change, volatility, alert flag
  kpi_disparity                         province price vs the national average, latest day
  kpi_lebaran                           price change in the 30 days before each Lebaran
  dq_checks                             data-quality results

Lebaran (Idul Fitri) dates follow the government calendar. The 2026 date is 21 March 2026,
from the official sidang isbat.
"""
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
OUT = HERE / "model"
OUT.mkdir(exist_ok=True)
LEBARAN = ["2022-05-02", "2023-04-22", "2024-04-10", "2025-03-31", "2026-03-21"]
ALERT_WOW = 0.10  # flag a commodity when its price moved more than 10% in a week

con = duckdb.connect(str(HERE / "food_prices.duckdb"))
con.execute(f"CREATE OR REPLACE TABLE raw_prices AS SELECT * FROM read_csv_auto('{(HERE / 'prices_daily.csv').as_posix()}')")

sql = f"""
-- dimensions ------------------------------------------------------------
CREATE OR REPLACE TABLE dim_commodity AS
SELECT DISTINCT CAST(com_id AS INTEGER) AS com_id, commodity, "group" AS commodity_group
FROM raw_prices;

CREATE OR REPLACE TABLE dim_region AS
SELECT DISTINCT region, level FROM raw_prices;

CREATE OR REPLACE TABLE lebaran AS
SELECT CAST(d AS DATE) AS lebaran_date FROM (VALUES {", ".join(f"('{d}')" for d in LEBARAN)}) t(d);

CREATE OR REPLACE TABLE dim_date AS
WITH days AS (
  SELECT CAST(range AS DATE) AS date
  FROM range((SELECT MIN(date) FROM raw_prices), (SELECT MAX(date) FROM raw_prices) + INTERVAL 1 DAY, INTERVAL 1 DAY)
)
SELECT d.date, year(d.date) AS year, month(d.date) AS month, strftime(d.date, '%Y-%m') AS year_month,
       dayofweek(d.date) AS weekday,
       (SELECT MIN(l.lebaran_date) FROM lebaran l WHERE l.lebaran_date >= d.date) - d.date AS days_to_lebaran
FROM days d;

-- fact ------------------------------------------------------------------
CREATE OR REPLACE TABLE fact_price AS
SELECT CAST(date AS DATE) AS date, CAST(com_id AS INTEGER) AS com_id, region, price
FROM raw_prices;

-- KPIs: latest national and provincial moves ------------------------------
CREATE OR REPLACE TABLE kpi_latest AS
WITH last_day AS (SELECT MAX(date) AS d FROM fact_price),
p AS (
  SELECT f.*, (SELECT d FROM last_day) AS last_d FROM fact_price f
),
pick AS (
  SELECT com_id, region,
    arg_max(price, date) FILTER (WHERE date <= last_d)                      AS price_now,
    arg_max(price, date) FILTER (WHERE date <= last_d - INTERVAL 7 DAY)     AS price_7d,
    arg_max(price, date) FILTER (WHERE date <= last_d - INTERVAL 30 DAY)    AS price_30d,
    arg_max(price, date) FILTER (WHERE date <= last_d - INTERVAL 365 DAY)   AS price_1y,
    MAX(last_d) AS as_of
  FROM p GROUP BY com_id, region
),
vol AS (
  SELECT com_id, region, stddev_samp(ret) AS vol_90d
  FROM (
    SELECT com_id, region, date, price / lag(price) OVER (PARTITION BY com_id, region ORDER BY date) - 1 AS ret
    FROM fact_price
  ) WHERE date > (SELECT d FROM last_day) - INTERVAL 90 DAY
  GROUP BY com_id, region
)
SELECT pick.*, price_now / price_7d - 1 AS wow, price_now / price_30d - 1 AS mom, price_now / price_1y - 1 AS yoy,
       vol.vol_90d, abs(price_now / price_7d - 1) > {ALERT_WOW} AS alert_wow
FROM pick LEFT JOIN vol USING (com_id, region);

-- KPIs: regional disparity on the latest day ------------------------------
CREATE OR REPLACE TABLE kpi_disparity AS
WITH latest AS (
  SELECT com_id, region, arg_max(price, date) AS price
  FROM fact_price WHERE date > (SELECT MAX(date) FROM fact_price) - INTERVAL 14 DAY
  GROUP BY com_id, region
),
nat AS (SELECT com_id, price AS national FROM latest WHERE region = 'Semua Provinsi')
SELECT l.com_id, l.region, l.price, n.national, l.price / n.national - 1 AS gap_vs_national
FROM latest l JOIN nat n USING (com_id)
WHERE l.region <> 'Semua Provinsi';

-- KPIs: Lebaran effect (national) ----------------------------------------
CREATE OR REPLACE TABLE kpi_lebaran AS
SELECT f.com_id, year(l.lebaran_date) AS year, l.lebaran_date,
       arg_max(f.price, f.date) FILTER (WHERE f.date <= l.lebaran_date - INTERVAL 30 DAY) AS price_d30,
       arg_max(f.price, f.date) FILTER (WHERE f.date <  l.lebaran_date)                   AS price_d1,
       price_d1 / price_d30 - 1 AS change_30d_before
FROM fact_price f JOIN lebaran l ON f.date BETWEEN l.lebaran_date - INTERVAL 45 DAY AND l.lebaran_date
WHERE f.region = 'Semua Provinsi'
GROUP BY f.com_id, l.lebaran_date;

-- data quality -------------------------------------------------------------
CREATE OR REPLACE TABLE dq_checks AS
SELECT 'rows' AS check_name, CAST(COUNT(*) AS VARCHAR) AS result FROM fact_price
UNION ALL SELECT 'duplicate commodity-region-day rows',
  CAST(COUNT(*) - COUNT(DISTINCT (com_id, region, date)) AS VARCHAR) FROM fact_price
UNION ALL SELECT 'non-positive prices', CAST(COUNT(*) FILTER (WHERE price <= 0) AS VARCHAR) FROM fact_price
UNION ALL SELECT 'daily jumps above 50% (possible entry errors)', CAST(COUNT(*) AS VARCHAR) FROM (
  SELECT price / lag(price) OVER (PARTITION BY com_id, region ORDER BY date) - 1 AS r FROM fact_price
) WHERE abs(r) > 0.5
UNION ALL SELECT 'date range', CAST(MIN(date) AS VARCHAR) || ' to ' || CAST(MAX(date) AS VARCHAR) FROM fact_price
UNION ALL SELECT 'regions', CAST(COUNT(DISTINCT region) AS VARCHAR) FROM fact_price
UNION ALL SELECT 'commodities', CAST(COUNT(DISTINCT com_id) AS VARCHAR) FROM fact_price;
"""
con.execute(sql)

for t in ["dim_commodity", "dim_region", "dim_date", "fact_price", "kpi_latest", "kpi_disparity", "kpi_lebaran", "dq_checks"]:
    con.execute(f"COPY {t} TO '{(OUT / (t + '.csv')).as_posix()}' (HEADER, DELIMITER ',')")
print(con.execute("SELECT * FROM dq_checks").fetchdf().to_string(index=False))
print(con.execute("""
  SELECT c.commodity, k.price_now, round(k.wow*100,1) wow_pct, round(k.mom*100,1) mom_pct, round(k.yoy*100,1) yoy_pct, k.alert_wow
  FROM kpi_latest k JOIN dim_commodity c USING (com_id) WHERE region = 'Semua Provinsi' ORDER BY yoy_pct DESC
""").fetchdf().to_string(index=False))
