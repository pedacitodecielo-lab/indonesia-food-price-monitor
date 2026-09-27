"""Render a documentation image of a real scraper run: request, raw JSON and run log.

Input: the run log (scrape_run.log) and one cached PIHPS response in raw/.
Output: images/00_scraping_run.png
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent.parent
LOG = Path(sys.argv[1])
RAW = HERE / "raw" / "com16_20260701_20260927.json"   # Cabai Rawit Merah, current quarter
OUT = HERE / "images" / "00_scraping_run.png"

BG, PANEL, BORDER = "#F4F1EA", "#1E2327", "#E2DCCD"
INK, MUTED, GREEN, ORANGE, BLUE, WHITE = "#1F2A30", "#51606B", "#7BD389", "#F2A65A", "#8AB4F8", "#E8EAED"
F = "C:/Windows/Fonts/"
title_f = ImageFont.truetype(F + "segoeuib.ttf", 34)
sub_f = ImageFont.truetype(F + "segoeui.ttf", 20)
head_f = ImageFont.truetype(F + "segoeuib.ttf", 20)
mono = ImageFont.truetype(F + "consola.ttf", 17)

W, H = 1800, 1140
img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)
d.text((50, 36), "How the data was collected: a real run of scrape_pihps.py", font=title_f, fill=INK)
d.text((50, 84), "Source: PIHPS Nasional, Bank Indonesia (bi.go.id/hargapangan), traditional-market prices. "
                 "Run on 27 Sep 2026.", font=sub_f, fill=MUTED)


def panel(x, y, w, h, heading, lines):
    d.rounded_rectangle((x, y, x + w, y + h), radius=14, fill=PANEL, outline=BORDER)
    d.text((x + 20, y + 14), heading, font=head_f, fill=WHITE)
    ty = y + 52
    for text, color in lines:
        d.text((x + 20, ty), text, font=mono, fill=color)
        ty += 24


request = [
    ("# 1 request = 1 commodity x 1 quarter", MUTED),
    ("GET https://www.bi.go.id/hargapangan/WebSite/", BLUE),
    ("    TabelHarga/GetGridDataKomoditas", BLUE),
    ("  price_type_id = 1        # traditional markets", WHITE),
    ("  comcat_id     = com_16   # Cabai Rawit Merah", WHITE),
    ("  start_date    = 2026-07-01", WHITE),
    ("  end_date      = 2026-09-27", WHITE),
    ("", WHITE),
    ("# polite scraping", MUTED),
    ("  - robots.txt allows the path", GREEN),
    ("  - 2 s pause between requests", GREEN),
    ("  - stop on HTTP 403 / 429 / 503", GREEN),
    ("  - past quarters cached in raw/ (399 files)", GREEN),
    ("  - honest User-Agent, no personal data", GREEN),
]
panel(50, 130, 820, 440, "1. Request", request)

rows = json.loads(RAW.read_text(encoding="utf-8"))
nat = rows[0]
dates = [k for k in nat if "/" in k][-3:]
raw_lines = [("[", WHITE), ("  {", WHITE),
             (f'    "no": "{nat["no"]}", "name": "{nat["name"]}", "level": {nat["level"]},', ORANGE)]
raw_lines += [(f'    "{k}": "{nat[k]}",', ORANGE) for k in dates]
raw_lines += [("    ...  one column per working day", MUTED), ("  },", WHITE)]
for r in rows[1:3]:
    k = dates[-1]
    raw_lines.append((f'  {{ "name": "{r["name"].strip()}", "level": {r["level"]}, "{k}": "{r[k]}", ... }},', ORANGE))
raw_lines += [(f"  ...  {len(rows)} rows: national + provinces", MUTED), ("]", WHITE), ("", WHITE),
              ("-> to_long(): wide dates -> (date, region, price)", GREEN),
              ('   "96,450" -> 96450.0, "-" dropped', GREEN)]
panel(900, 130, 850, 440, "2. Raw JSON response (Cabai Rawit Merah, national row)", raw_lines)

log = [l.rstrip() for l in LOG.read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()]
log = [l for l in log if not l.startswith("dtype")]
elapsed = next((l for l in log if l.startswith("elapsed")), None)
log = [l for l in log if not l.startswith("elapsed")]
show = log[:1] + log[1:5] + ["  ..."] + log[16:22]
log_lines = [("> python scrape_pihps.py", BLUE)] + [(l, WHITE) for l in show]
log_lines += [("", WHITE), ("rows by level:  national 25,804  |  province 838,431", GREEN),
              ("date range:     2022-01-03 to 2026-09-25", GREEN)]
if elapsed:
    log_lines.append((f"run time:       {float(elapsed.split(':')[1]):.0f} s", GREEN))
panel(50, 600, 1700, 470, "3. Run log (terminal output)", log_lines)

d.text((50, 1090), "Output: prices_daily.csv (864,235 rows)  ->  DuckDB SQL model  ->  Power BI report",
       font=sub_f, fill=MUTED)
img.save(OUT)
print(OUT)
