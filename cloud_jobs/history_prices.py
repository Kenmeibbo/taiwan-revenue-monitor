"""Collect official monthly closing prices on GitHub's standard runner, without AI."""
import argparse
import calendar
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

SITE = "https://zhewei-twstock-monthly-high-tracker.skywei.chatgpt.site"
ROOT = Path(__file__).resolve().parents[1] / "cloud-data"
LAST_REQUEST = 0.0


def fetch(url, delay=1.5):
    global LAST_REQUEST
    for attempt in range(3):
        time.sleep(max(0, delay - (time.monotonic() - LAST_REQUEST)))
        LAST_REQUEST = time.monotonic()
        try:
            with urlopen(Request(url, headers={"Accept": "application/json", "User-Agent": "ZheweiOfficialHistory/1.0"}), timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code != 429 or attempt == 2:
                raise
            time.sleep(max(30, min(120, int(error.headers.get("Retry-After", "30")))))
    raise RuntimeError("Official history unavailable")


def parse_market(body, day, source):
    if re.search("沒有符合條件的資料", str(body.get("stat", ""))):
        return None
    if str(body.get("stat", "")).lower() != "ok" or body.get("date") != day.strftime("%Y%m%d"):
        raise ValueError("Official market date/status mismatch")
    table = next((table for table in body.get("tables", []) if "證券代號" in table.get("fields", []) or "代號" in table.get("fields", [])), None)
    if table is None:
        raise ValueError("Official company price table unavailable")
    fields = [re.sub(r"\s", "", field) for field in table["fields"]]
    code_index = fields.index("證券代號" if "證券代號" in fields else "代號")
    close_index = fields.index("收盤價" if "收盤價" in fields else "收盤")
    if not table.get("data"):
        return None
    quotes = {}
    for row in table["data"]:
        code = str(row[code_index])
        value = str(row[close_index]).replace(",", "").strip()
        if re.fullmatch(r"\d{4}", code) and re.fullmatch(r"\d+(?:\.\d+)?", value) and float(value) > 0:
            quotes[code] = {"price": float(value), "date": day.isoformat(), "basis": "close", "source": source}
    if len(quotes) < 100:
        raise ValueError("Official market report incomplete")
    return quotes


def market_month(ym, market):
    day = date(int(ym[:4]), int(ym[4:]), calendar.monthrange(int(ym[:4]), int(ym[4:]))[1])
    for _ in range(12):
        if day.weekday() < 5:
            if market == "listed":
                url = f"https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date={day:%Y%m%d}&type=ALLBUT0999"
            else:
                url = f"https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date={day:%Y/%m/%d}&response=json"
            quotes = parse_market(fetch(url), day, url)
            if quotes:
                return quotes
        day -= timedelta(days=1)
        if day.strftime("%Y%m") != ym:
            break
    raise ValueError("No verified month-end market report for " + ym)


def write_json(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, ensure_ascii=True, separators=(",", ":")) + "\n", encoding="utf-8")


def profiles():
    target = ROOT / "profiles.json"
    if target.exists():
        return
    companies = {}
    for market, url in [("listed", "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"), ("otc", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O")]:
        rows = fetch(url)
        if not isinstance(rows, list) or len(rows) < 100:
            raise ValueError("Official company profiles incomplete")
        for row in rows:
            code = str(row.get("公司代號", row.get("SecuritiesCompanyCode", "")))
            born = str(row.get("成立日期", row.get("DateOfIncorporation", "")))
            if re.fullmatch(r"\d{4}", code) and re.fullmatch(r"\d{8}", born):
                companies[code] = born[:6]
    write_json(target, {"version": 1, "companies": companies})


def collect(limit=12):
    policy = fetch(SITE + "/api/scheduled-refresh")
    if policy.get("policy", {}).get("allowed") is not True:
        print("Outside the owner's Taipei calendar window; no official data fetched.")
        return 0
    now = datetime.now(timezone(timedelta(hours=8)))
    end = now.year * 12 + now.month - 1
    profiles()
    count = 0
    for offset in range(120):
        index = end - offset
        ym = f"{(index - 1) // 12:04d}{(index - 1) % 12 + 1:02d}"
        target = ROOT / "markets" / (ym + ".json")
        if target.exists():
            continue
        listed = market_month(ym, "listed")
        otc = market_month(ym, "otc")
        quotes = dict(listed)
        for code, quote in otc.items():
            if code not in quotes or quote["date"] > quotes[code]["date"]:
                quotes[code] = quote
        write_json(target, {"version": 1, "ym": ym, "complete": True, "quotes": quotes})
        print(f"Saved {ym}: {len(quotes)} verified official closing prices", flush=True)
        count += 1
        if count >= limit:
            break
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args()
    if not 1 <= args.limit <= 120:
        raise SystemExit("Invalid batch limit")
    collect(args.limit)

