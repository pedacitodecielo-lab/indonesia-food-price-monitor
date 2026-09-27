"""Scrape daily food prices from Bank Indonesia's PIHPS Nasional (bi.go.id/hargapangan).

What it collects
- 21 strategic commodities (rice, chicken, beef, eggs, shallots, garlic, chillies, cooking oil, sugar)
- traditional-market prices (price_type_id=1), national average plus every province
- daily working-day prices from START to today

How it behaves
- It uses the same public JSON endpoint the "Tabel Harga" page calls. No login is needed,
  and bi.go.id/robots.txt allows the path.
- It sends one request per commodity per quarter, waits 2 seconds between requests,
  and caches every response in raw/. It stops immediately on HTTP 403, 429 or 503.
- It identifies itself honestly as a personal research project.

Data (c) PIHPS Nasional / Bank Indonesia. This is used for a non-commercial portfolio with
attribution, and the raw responses are not redistributed.
"""
import json
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
RAW.mkdir(exist_ok=True)
BASE = "https://www.bi.go.id/hargapangan/WebSite"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; personal research project)"}
START = date(2022, 1, 1)
PRICE_TYPE = 1  # traditional markets


def get(url, params=None):
    for attempt in range(4):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=90)
        except requests.RequestException:
            time.sleep(10 * (attempt + 1))
            continue
        if r.status_code in (403, 429, 503):
            raise SystemExit(f"HTTP {r.status_code}: the server asks us to stop")
        r.raise_for_status()
        time.sleep(2)
        return r.json()
    raise RuntimeError(f"unreachable after retries: {url}")


def commodities():
    tree = get(f"{BASE}/Home/GetCommoditiesTree")["data"]
    groups = {t["TreeID"]: t["TreeName"].strip() for t in tree if t["ParentID"] is None}
    return [dict(com_id=t["TreeID"].split("_")[1], commodity=t["TreeName"].strip(), group=groups[t["ParentID"]])
            for t in tree if t["ParentID"] is not None]


def quarters(start, end):
    d = start
    while d <= end:
        q_first = (d.month - 1) // 3 * 3 + 1
        nxt = date(d.year + 1, 1, 1) if q_first == 10 else date(d.year, q_first + 3, 1)
        yield d, min(nxt - timedelta(days=1), end)
        d = nxt


def fetch(com_id, start, end, today):
    cache = RAW / f"com{com_id}_{start:%Y%m%d}_{end:%Y%m%d}.json"
    # past quarters never change, so cache them; the current quarter is always refreshed
    if cache.exists() and end < today - timedelta(days=7):
        return json.loads(cache.read_text(encoding="utf-8"))
    params = dict(price_type_id=PRICE_TYPE, comcat_id=f"com_{com_id}", province_id="", regency_id="",
                  showKota="false", showPasar="false", tipe_laporan=1,
                  start_date=start.isoformat(), end_date=end.isoformat())
    data = get(f"{BASE}/TabelHarga/GetGridDataKomoditas", params)["data"]
    cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def to_long(rows, com):
    out = []
    for row in rows:
        region = row["name"].strip()
        for k, v in row.items():
            if "/" not in k:
                continue
            val = str(v).replace(",", "").strip()
            if val in ("", "-", "0"):
                continue
            out.append(dict(date=pd.to_datetime(k, format="%d/%m/%Y"), region=region,
                            level="national" if row["level"] == 0 else "province",
                            price=float(val), **com))
    return out


def main():
    today = date.today()
    coms = commodities()
    print(f"{len(coms)} commodities")
    records = []
    for com in coms:
        for s, e in quarters(START, today):
            records += to_long(fetch(com["com_id"], s, e, today), com)
        print(f"  {com['commodity']}: {len(records):,} rows so far")
    df = pd.DataFrame(records).drop_duplicates(["date", "region", "com_id"])
    df.to_csv(HERE / "prices_daily.csv", index=False)
    print(df.groupby("level").size(), df.date.min(), df.date.max(), sep="\n")


if __name__ == "__main__":
    main()
