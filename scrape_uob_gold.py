#!/usr/bin/env python3
"""Read UOB Malaysia gold prices (loaded by JavaScript) and append them to data/uob_gold_prices.csv."""
import csv, re, sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

URL = "https://www.uob.com.my/online-rates/gold-prices.page"
CSV_PATH = Path("data/uob_gold_prices.csv")
DEBUG = Path("debug")
FIELDS = ["date", "time", "item", "size", "selling", "buying", "effective_from"]


def num(s):
    s = re.sub(r"[^\d.]", "", (s or "").replace(",", ""))
    try:
        return float(s) if s else None
    except ValueError:
        return None


def parse_rows(rows):
    """rows: list of lists of cell text -> list of (item, size, selling, buying)."""
    out, last_item = [], ""
    for cells in rows:
        cells = [(c or "").strip() for c in cells]
        if len(cells) >= 4:
            item, size = cells[0] or last_item, cells[1]
        elif len(cells) == 3:  # item cell merged with the row above
            item, size = last_item, cells[0]
        else:
            continue
        sell, buy = num(cells[-2]), num(cells[-1])
        if not item or sell is None or buy is None:
            continue
        last_item = item
        out.append((item, size, sell, buy))
    return out


def scrape():
    from playwright.sync_api import sync_playwright
    DEBUG.mkdir(exist_ok=True)
    seen = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(locale="en-MY")
        page.on("response", lambda r: seen.append(f"{r.status} {r.request.resource_type} {r.url}"))
        page.goto(URL, wait_until="networkidle", timeout=60000)
        try:
            page.wait_for_function(
                r"() => [...document.querySelectorAll('table tr')].some(r => /\d+\.\d{2}/.test(r.innerText))",
                timeout=45000)
        except Exception as e:
            print("Table did not fill in time:", e)
        rows = page.eval_on_selector_all(
            "table tr", "els => els.map(tr => [...tr.querySelectorAll('td')].map(td => td.innerText))")
        body = page.inner_text("body")
        (DEBUG / "network.txt").write_text("\n".join(seen))
        (DEBUG / "page.html").write_text(page.content())
        page.screenshot(path=str(DEBUG / "page.png"), full_page=True)
        browser.close()
    m = re.search(r"with effect from\s*[:\-]?\s*(.{0,40})", body, re.I | re.S)
    effective = m.group(1).strip().split("\n")[0] if m else ""
    return parse_rows(rows), effective


def main():
    parsed, effective = scrape()
    if not parsed:
        print("No prices found. See debug/ files.")
        sys.exit(1)
    now = datetime.now(ZoneInfo("Asia/Kuala_Lumpur"))
    today, hhmm = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
    CSV_PATH.parent.mkdir(exist_ok=True)
    old = []
    if CSV_PATH.exists():
        with CSV_PATH.open(newline="") as f:
            old = [r for r in csv.DictReader(f) if r["date"] != today]  # re-runs overwrite today
    new = [dict(date=today, time=hhmm, item=i, size=s, selling=sl, buying=b, effective_from=effective)
           for i, s, sl, b in parsed]
    with CSV_PATH.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(old + new)
    print(f"Saved {len(new)} prices for {today}")


if __name__ == "__main__":
    main()
