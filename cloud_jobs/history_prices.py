"""Collect official monthly closing prices on GitHub's standard runner, without AI."""
import argparse
import calendar
from datetime import date, datetime, timedelta, timezone
import json
import gzip
from http.client import IncompleteRead
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SITE = "https://zhewei-twstock-monthly-high-tracker.skywei.chatgpt.site"
ROOT = Path(__file__).resolve().parents[1] / "cloud-data"
LAST_REQUEST = 0.0


def fetch(url, delay=1.5, body=None):
    global LAST_REQUEST
    for attempt in range(3):
        time.sleep(max(0, delay - (time.monotonic() - LAST_REQUEST)))
        LAST_REQUEST = time.monotonic()
        try:
            headers={"Accept": "application/json", "Accept-Encoding": "gzip", "User-Agent": "ZheweiOfficialHistory/1.0"}
            if body is not None:
                headers["Content-Type"]="application/json"
            with urlopen(Request(url, data=json.dumps(body).encode() if body is not None else None, headers=headers), timeout=30) as response:
                content = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    content = gzip.decompress(content)
                return json.loads(content.decode("utf-8-sig"))
        except HTTPError as error:
            if error.code != 429 or attempt == 2:
                raise
            time.sleep(max(30, min(120, int(error.headers.get("Retry-After", "30")))))
        except (IncompleteRead, URLError, TimeoutError, ConnectionError, json.JSONDecodeError):
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))
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


def individual_quote(body, ym, source, emerging=False):
    if re.search("沒有符合條件的資料", str(body.get("stat", ""))):
        return None
    if str(body.get("stat", "")).lower() != "ok":
        raise ValueError("Official individual quote unavailable")
    table = body.get("tables", [body])[0]
    fields = [re.sub(r"\s", "", field) for field in table.get("fields", [])]
    name = "成交均價" if emerging else "收盤價" if "收盤價" in fields else "收盤"
    index = fields.index(name)
    quotes=[]
    for row in table.get("data", []):
        parts=str(row[0]).split("/")
        day=date(int(parts[0])+(1911 if int(parts[0])<1911 else 0),int(parts[1]),int(parts[2]))
        if day.strftime("%Y%m") != ym:
            raise ValueError("Individual price month mismatch")
        value=str(row[index]).replace(",", "").strip()
        basis="esb_average" if emerging else "close"
        if emerging and (not re.fullmatch(r"\d+(?:\.\d+)?",value) or float(value)<=0):
            second=next((i for i,field in enumerate(fields) if i>index and field=="成交均價"),None)
            if second is not None:
                value=str(row[second]).replace(",", "").strip();basis="esb_external_average"
        if re.fullmatch(r"\d+(?:\.\d+)?", value) and float(value)>0:
            quotes.append({"price":float(value),"date":day.isoformat(),"basis":basis,"source":source})
    return max(quotes,key=lambda quote:quote["date"]) if quotes else None


def supplemental():
    try:
        requests=fetch(SITE+"/api/history-requests").get("requests", [])
    except HTTPError as error:
        if error.code==404:
            return
        raise
    companies=json.loads((ROOT/"profiles.json").read_text(encoding="utf-8")).get("companies",{}) if (ROOT/"profiles.json").exists() else {}
    for request in requests[:4]:
        code,market,end=request.get("code",""),request.get("market",""),request.get("end","")
        if not re.fullmatch(r"\d{4}",code) or market not in ["listed","otc"] or not re.fullmatch(r"\d{6}",end):
            continue
        target=ROOT/"companies"/(code+".json")
        extra=json.loads(target.read_text(encoding="utf-8")) if target.exists() else {"version":1,"code":code,"quotes":{},"absent":[],"revenues":{},"revenueAbsent":[]}
        checked=0
        end_index=int(end[:4])*12+int(end[4:])
        for offset in range(120):
            index=end_index-offset;ym=f"{(index-1)//12:04d}{(index-1)%12+1:02d}"
            if ym < companies.get(code,"000000"):
                continue
            pack=ROOT/"markets"/(ym+".json")
            covered=pack.exists() and code in json.loads(pack.read_text(encoding="utf-8"))["quotes"]
            price_needed=not covered and ym not in extra["quotes"] and ym not in extra["absent"]
            revenue_needed=ym in request.get("months",[]) and ym not in extra["revenues"] and ym not in extra["revenueAbsent"]
            if not price_needed and not revenue_needed:
                continue
            if price_needed:
                date_query=ym[:4]+"/"+ym[4:]+"/01"
                urls={"listed":f"https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={ym}01&stockNo={code}","otc":f"https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock?code={code}&date={date_query}&response=json"}
                quote=None
                for kind in [market,"otc" if market=="listed" else "listed"]:
                    quote=individual_quote(fetch(urls[kind]),ym,urls[kind])
                    if quote:
                        break
                if not quote:
                    url=f"https://www.tpex.org.tw/www/zh-tw/emerging/historical?type=Monthly&code={code}&date={date_query}&response=json"
                    quote=individual_quote(fetch(url),ym,url,True)
                if quote:
                    extra["quotes"][ym]=quote
                else:
                    extra["absent"].append(ym)
            if revenue_needed:
                result=fetch("https://mops.twse.com.tw/mops/api/t05st10_ifrs",body={"companyId":code,"dataType":"2","year":str(int(ym[:4])-1911),"month":str(int(ym[4:])),"subsidiaryCompanyId":""})
                if result.get("code")==406:
                    extra["revenueAbsent"].append(ym)
                elif result.get("code")==200 and result.get("result",{}).get("yymm")==str(int(ym[:4])-1911).zfill(3)+ym[4:]:
                    if any(row[0]=="本月" for row in result["result"].get("data",[])):
                        extra["revenues"][ym]=result
                else:
                    raise ValueError("Supplemental monthly revenue unavailable")
            checked+=1
            if checked>=6:
                break
        if checked:
            write_json(target,extra)
            print(f"Supplemented {code}: {checked} official monthly checks",flush=True)


def collect(limit=12):
    policy = fetch(SITE + "/api/scheduled-refresh")
    if policy.get("policy", {}).get("allowed") is not True:
        print("Outside the owner's Taipei calendar window; no official data fetched.")
        return 0
    now = datetime.now(timezone(timedelta(hours=8)))
    end = now.year * 12 + now.month - 1
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
    try:
        profiles()
    except (IncompleteRead, URLError, TimeoutError, ConnectionError, ValueError) as error:
        print("Company profile lookup postponed: " + str(error), flush=True)
    supplemental()
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args()
    if not 1 <= args.limit <= 120:
        raise SystemExit("Invalid batch limit")
    collect(args.limit)

