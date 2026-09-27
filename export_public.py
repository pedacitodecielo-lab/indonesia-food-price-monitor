"""Write the aggregated, shareable outputs to public/.

The daily raw prices stay local: PIHPS data is (c) Bank Indonesia. Only derived figures
are published: KPI tables, monthly averages, the Lebaran effect and the data-quality log.
"""
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
PUB = HERE / "public"
PUB.mkdir(exist_ok=True)
con = duckdb.connect(str(HERE / "food_prices.duckdb"), read_only=True)

queries = {
    "monthly_national.csv": """
        SELECT c.commodity_group, c.commodity, strftime(f.date, '%Y-%m') AS month, round(avg(f.price)) AS avg_price
        FROM fact_price f JOIN dim_commodity c USING (com_id)
        WHERE f.region = 'Semua Provinsi' GROUP BY ALL ORDER BY commodity, month""",
    "kpi_latest.csv": """
        SELECT c.commodity, k.region, k.as_of, k.price_now, round(k.wow, 4) AS wow, round(k.mom, 4) AS mom,
               round(k.yoy, 4) AS yoy, round(k.vol_90d, 4) AS vol_90d, k.alert_wow
        FROM kpi_latest k JOIN dim_commodity c USING (com_id) ORDER BY commodity, region""",
    "kpi_disparity.csv": """
        SELECT c.commodity, d.region, d.price, d.national, round(d.gap_vs_national, 4) AS gap_vs_national
        FROM kpi_disparity d JOIN dim_commodity c USING (com_id) ORDER BY commodity, gap_vs_national DESC""",
    "kpi_lebaran.csv": """
        SELECT c.commodity, l.year, l.lebaran_date, l.price_d30, l.price_d1, round(l.change_30d_before, 4) AS change_30d_before
        FROM kpi_lebaran l JOIN dim_commodity c USING (com_id) ORDER BY commodity, year""",
    "dq_checks.csv": "SELECT * FROM dq_checks",
}
for name, q in queries.items():
    con.execute(f"COPY ({q}) TO '{(PUB / name).as_posix()}' (HEADER, DELIMITER ',')")
print("public/:", ", ".join(queries))
