from __future__ import annotations

import csv
import html
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.error import URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
PUBLIC_DIR = ROOT / "public"
DATA_DIR = Path(os.environ.get("REVENUE_DATA_DIR", str(ROOT / "data"))).resolve()
SNAPSHOT_DIR = DATA_DIR / "snapshots"
RAW_DIR = DATA_DIR / "raw"
IMPORT_DIR = DATA_DIR / "import"
STATUS_FILE = DATA_DIR / "status.json"

MARKETS = {
    "listed": {
        "label": "\u4e0a\u5e02",
        "code": "L",
        "url": "https://mopsfin.twse.com.tw/opendata/t187ap05_L.csv",
    },
    "otc": {
        "label": "\u4e0a\u6ac3",
        "code": "O",
        "url": "https://mopsfin.twse.com.tw/opendata/t187ap05_O.csv",
    },
}

CSV_FIELDS = {
    "published": "\u51fa\u8868\u65e5\u671f",
    "data_ym": "\u8cc7\u6599\u5e74\u6708",
    "company_id": "\u516c\u53f8\u4ee3\u865f",
    "company_name": "\u516c\u53f8\u540d\u7a31",
    "industry": "\u7522\u696d\u5225",
    "monthly": "\u71df\u696d\u6536\u5165-\u7576\u6708\u71df\u6536",
    "previous_month": "\u71df\u696d\u6536\u5165-\u4e0a\u6708\u71df\u6536",
    "last_year_month": "\u71df\u696d\u6536\u5165-\u53bb\u5e74\u7576\u6708\u71df\u6536",
    "mom_pct": "\u71df\u696d\u6536\u5165-\u4e0a\u6708\u6bd4\u8f03\u589e\u6e1b(%)",
    "yoy_pct": "\u71df\u696d\u6536\u5165-\u53bb\u5e74\u540c\u6708\u589e\u6e1b(%)",
    "accumulated": "\u7d2f\u8a08\u71df\u696d\u6536\u5165-\u7576\u6708\u7d2f\u8a08\u71df\u6536",
    "note": "\u5099\u8a3b",
}

MOPS_IFRS_URL = "https://mops.twse.com.tw/mops/web/ajax_t05st10_ifrs"
MOPSOV_IFRS_URL = "https://mopsov.twse.com.tw/mops/web/ajax_t05st10_ifrs"
MOPSOV_SUMMARY_URL = "https://mopsov.twse.com.tw/nas/t21/{folder}/t21sc03_{roc_year}_{month}.html"
SYNC_INTERVAL_SECONDS = int(os.environ.get("REVENUE_SYNC_SECONDS", "10800"))
HTTP_TIMEOUT_SECONDS = int(os.environ.get("REVENUE_HTTP_TIMEOUT", "30"))
PARTIAL_SYNC_STATE: Dict[str, dict] = {}
PARTIAL_SYNC_LOCK = threading.Lock()
HISTORY_SYNC_STATE: Dict[str, dict] = {}
HISTORY_SYNC_LOCK = threading.Lock()


def ensure_dirs() -> None:
    for path in (PUBLIC_DIR, DATA_DIR, SNAPSHOT_DIR, RAW_DIR, IMPORT_DIR):
        path.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_status() -> dict:
    if not STATUS_FILE.exists():
        return {"lastSync": None, "markets": {}, "errors": []}
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"lastSync": None, "markets": {}, "errors": ["status.json unreadable"]}


def write_status(status: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    STATUS_FILE.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_number(value: object) -> Optional[int]:
    cleaned = str(value or "").replace(",", "").strip()
    if not cleaned or cleaned in {"-", "--", "NA", "N/A"}:
        return None
    try:
        return int(float(cleaned))
    except ValueError:
        return None


def normalize_pct(value: object) -> str:
    return str(value or "").replace("%", "").strip()


def roc_to_ad_yyyymm(roc_yyyymm: str) -> str:
    text = re.sub(r"\D", "", str(roc_yyyymm or ""))
    if len(text) < 5:
        return text
    return f"{int(text[:-2]) + 1911:04d}{int(text[-2:]):02d}"


def ad_to_roc_yyyymm(yyyymm: str) -> tuple[str, str]:
    return str(int(yyyymm[:4]) - 1911), yyyymm[4:6]


def ad_to_display(yyyymm: str) -> str:
    if len(yyyymm) != 6:
        return yyyymm
    return f"{yyyymm[:4]}-{yyyymm[4:]}"


def month_index(yyyymm: str) -> int:
    return int(yyyymm[:4]) * 12 + int(yyyymm[4:6])


def previous_month_yyyymm() -> str:
    today = datetime.now()
    year = today.year
    month = today.month - 1
    if month == 0:
        year -= 1
        month = 12
    return f"{year:04d}{month:02d}"


def current_query_month_yyyymm() -> str:
    today = datetime.now()
    return f"{today.year:04d}{today.month - 1:02d}" if today.month > 1 else f"{today.year - 1:04d}12"


def month_options() -> List[str]:
    ensure_dirs()
    months = {
        match.group("ym")
        for path in SNAPSHOT_DIR.glob("*.json")
        for match in [re.match(r"(?:listed|otc)_(?P<ym>\d{6})\.json$", path.name)]
        if match
    }
    end = current_query_month_yyyymm()
    end_year = int(end[:4])
    end_month = int(end[4:6])
    for year in range(end_year - 10, end_year + 1):
        for month in range(1, 13):
            if year == end_year and month > end_month:
                continue
            months.add(f"{year:04d}{month:02d}")
    return sorted(months, reverse=True)


def parse_revenue_csv(content: bytes, market: str) -> List[dict]:
    text = content.decode("utf-8-sig")
    rows: List[dict] = []
    reader = csv.DictReader(text.splitlines())
    for raw in reader:
        data_ym_roc = (raw.get(CSV_FIELDS["data_ym"]) or "").strip().strip('"')
        revenue = normalize_number(raw.get(CSV_FIELDS["monthly"], ""))
        company_id = (raw.get(CSV_FIELDS["company_id"]) or "").strip()
        if not data_ym_roc or not company_id or revenue is None:
            continue
        rows.append(
            {
                "market": market,
                "marketLabel": MARKETS[market]["label"],
                "dataYmRoc": data_ym_roc,
                "dataYm": roc_to_ad_yyyymm(data_ym_roc),
                "dataYmDisplay": ad_to_display(roc_to_ad_yyyymm(data_ym_roc)),
                "publishedRocDate": (raw.get(CSV_FIELDS["published"]) or "").strip(),
                "companyId": company_id,
                "companyName": (raw.get(CSV_FIELDS["company_name"]) or "").strip(),
                "industry": (raw.get(CSV_FIELDS["industry"]) or "").strip(),
                "monthlyRevenue": revenue,
                "previousMonthRevenue": normalize_number(raw.get(CSV_FIELDS["previous_month"], "")),
                "lastYearMonthRevenue": normalize_number(raw.get(CSV_FIELDS["last_year_month"], "")),
                "momPct": normalize_pct(raw.get(CSV_FIELDS["mom_pct"], "")),
                "yoyPct": normalize_pct(raw.get(CSV_FIELDS["yoy_pct"], "")),
                "accumulatedRevenue": normalize_number(raw.get(CSV_FIELDS["accumulated"], "")),
                "note": (raw.get(CSV_FIELDS["note"]) or "").strip(),
                "isNewHigh": False,
                "historicalSameMonthCount": 0,
                "historicalSameMonthMax": None,
                "revenueGap": None,
            }
        )
    return rows


def fetch_url(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 revenue-sync/1.0"})
    with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return response.read()


def decode_mops(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp950", "big5", "utf-8"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="ignore")


def post_form(url: str, data: dict) -> str:
    encoded = urlencode(data).encode("utf-8")
    request = Request(
        url,
        data=encoded,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0 revenue-sync/1.0",
            "Referer": "https://mops.twse.com.tw/mops/web/t05st10_ifrs",
        },
    )
    with urlopen(request, timeout=min(HTTP_TIMEOUT_SECONDS, 8)) as response:
        return response.read().decode("utf-8", errors="ignore")


def clean_html_cell(value: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(no_tags)).strip()


def extract_th_value(page: str, label: str) -> str:
    pattern = re.compile(
        rf"<th[^>]*>\s*{re.escape(label)}\s*</th>\s*<td[^>]*>(?P<value>.*?)</td>",
        re.I | re.S,
    )
    match = pattern.search(page)
    return clean_html_cell(match.group("value")) if match else ""


def fetch_company_month(base_row: dict, yyyymm: str) -> Optional[dict]:
    roc_year, month = ad_to_roc_yyyymm(yyyymm)
    payload = {
        "encodeURIComponent": "1",
        "step": "1",
        "firstin": "1",
        "off": "1",
        "queryName": "co_id",
        "inpuType": "co_id",
        "TYPEK": "all",
        "isnew": "false",
        "co_id": base_row["companyId"],
        "year": roc_year,
        "month": month,
    }
    page = post_form(MOPSOV_IFRS_URL, payload)
    monthly = normalize_number(extract_th_value(page, "\u672c\u6708"))
    if monthly is None:
        return None
    previous_month = normalize_number(extract_th_value(page, "\u4e0a\u6708"))
    last_year_month = normalize_number(extract_th_value(page, "\u53bb\u5e74\u540c\u671f"))
    yoy_pct = normalize_pct(extract_th_value(page, "\u589e\u6e1b\u767e\u5206\u6bd4"))
    accumulated = normalize_number(extract_th_value(page, "\u672c\u5e74\u7d2f\u8a08"))
    return {
        **base_row,
        "dataYm": yyyymm,
        "dataYmDisplay": ad_to_display(yyyymm),
        "dataYmRoc": f"{roc_year}{month}",
        "publishedRocDate": "",
        "monthlyRevenue": monthly,
        "previousMonthRevenue": previous_month,
        "lastYearMonthRevenue": last_year_month,
        "momPct": "",
        "yoyPct": yoy_pct,
        "accumulatedRevenue": accumulated,
        "note": "\u516c\u958b\u8cc7\u8a0a\u89c0\u6e2c\u7ad9\u9010\u516c\u53f8\u5373\u6642\u67e5\u8a62",
    }


def fetch_summary_month(market: str, yyyymm: str) -> List[dict]:
    roc_year, month = ad_to_roc_yyyymm(yyyymm)
    folder = "sii" if market == "listed" else "otc"
    url = MOPSOV_SUMMARY_URL.format(folder=folder, roc_year=roc_year, month=int(month))
    page = decode_mops(fetch_url(url))
    rows: List[dict] = []
    for row_html in re.findall(r"<tr\s+align=right>(.*?)</tr>", page, flags=re.I | re.S):
        cells = [clean_html_cell(cell) for cell in re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.I | re.S)]
        if len(cells) < 10:
            continue
        company_id = cells[0].strip()
        if not re.fullmatch(r"\d{4,6}", company_id):
            continue
        revenue = normalize_number(cells[2])
        if revenue is None:
            continue
        rows.append(
            {
                "market": market,
                "marketLabel": MARKETS[market]["label"],
                "dataYmRoc": f"{roc_year}{month}",
                "dataYm": yyyymm,
                "dataYmDisplay": ad_to_display(yyyymm),
                "publishedRocDate": "",
                "companyId": company_id,
                "companyName": cells[1].strip(),
                "industry": "",
                "monthlyRevenue": revenue,
                "previousMonthRevenue": normalize_number(cells[3]),
                "lastYearMonthRevenue": normalize_number(cells[4]),
                "momPct": normalize_pct(cells[5]),
                "yoyPct": normalize_pct(cells[6]),
                "accumulatedRevenue": normalize_number(cells[7]),
                "note": cells[10].strip() if len(cells) > 10 else "",
                "isNewHigh": False,
                "historicalSameMonthCount": 0,
                "historicalSameMonthMax": None,
                "revenueGap": None,
            }
        )
    return rows


def sync_summary_month(yyyymm: str) -> dict:
    result = {"month": yyyymm, "markets": {}, "errors": []}
    for market in MARKETS:
        try:
            rows = fetch_summary_month(market, yyyymm)
            if rows:
                existing = snapshots_for_month(yyyymm).get(market)
                industry_by_id = {
                    row["companyId"]: row.get("industry", "")
                    for row in (existing or {}).get("rows", [])
                    if row.get("industry")
                }
                if not industry_by_id:
                    latest_snapshot = latest_snapshot_for_market(market)
                    for latest_row in (latest_snapshot or {}).get("rows", []):
                        if latest_row.get("industry"):
                            industry_by_id.setdefault(latest_row["companyId"], latest_row["industry"])
                for row in rows:
                    row["industry"] = industry_by_id.get(row["companyId"], row.get("industry", ""))
                save_snapshot(market, rows, partial=yyyymm >= current_query_month_yyyymm())
            result["markets"][market] = len(rows)
        except Exception as exc:
            result["markets"][market] = 0
            result["errors"].append(f"{market} summary failed: {exc}")
    return result


def ensure_same_month_history(yyyymm: str, years: int = 10) -> dict:
    current_year = int(yyyymm[:4])
    month = yyyymm[4:6]
    result = {"requested": [], "fetched": [], "errors": []}
    for year in range(current_year - years, current_year):
        target = f"{year:04d}{month}"
        result["requested"].append(target)
        existing = snapshots_for_month(target)
        if all(market in existing for market in MARKETS):
            continue
        summary = sync_summary_month(target)
        result["fetched"].append({target: summary.get("markets", {})})
        result["errors"].extend(summary.get("errors", []))
        time.sleep(0.15)
    return result


def yyyymm_from_index(index: int) -> str:
    year = index // 12
    month = index % 12
    if month == 0:
        year -= 1
        month = 12
    return f"{year:04d}{month:02d}"


def ensure_rolling_month_history(yyyymm: str, years: int = 10) -> dict:
    current = month_index(yyyymm)
    start = current - years * 12
    result = {"requested": [], "fetched": [], "errors": []}
    for idx in range(start, current):
        target = yyyymm_from_index(idx)
        result["requested"].append(target)
        existing = snapshots_for_month(target)
        if all(market in existing for market in MARKETS):
            continue
        summary = sync_summary_month(target)
        result["fetched"].append({target: summary.get("markets", {})})
        result["errors"].extend(summary.get("errors", []))
        time.sleep(0.08)
    return result


def missing_rolling_history_months(yyyymm: str, years: int = 10) -> List[str]:
    current = month_index(yyyymm)
    start = current - years * 12
    missing: List[str] = []
    for idx in range(start, current):
        target = yyyymm_from_index(idx)
        existing = snapshots_for_month(target)
        if not all(market in existing for market in MARKETS):
            missing.append(target)
    return missing


def start_history_sync(yyyymm: str, years: int = 10) -> dict:
    key = f"{yyyymm}_{years}"
    missing = missing_rolling_history_months(yyyymm, years)
    with HISTORY_SYNC_LOCK:
        state = HISTORY_SYNC_STATE.get(key)
        if state and state.get("running"):
            return state
        if not missing:
            state = {"month": yyyymm, "years": years, "running": False, "missing": 0, "finishedAt": now_iso()}
            HISTORY_SYNC_STATE[key] = state
            return state
        state = {
            "month": yyyymm,
            "years": years,
            "running": True,
            "missing": len(missing),
            "startedAt": now_iso(),
        }
        HISTORY_SYNC_STATE[key] = state

    def runner() -> None:
        fetched: List[dict] = []
        errors: List[str] = []
        for target in missing:
            summary = sync_summary_month(target)
            fetched.append({target: summary.get("markets", {})})
            errors.extend(summary.get("errors", []))
            with HISTORY_SYNC_LOCK:
                HISTORY_SYNC_STATE[key] = {
                    **state,
                    "running": True,
                    "remaining": max(0, len(missing) - len(fetched)),
                    "fetched": fetched[-5:],
                    "errors": errors[-5:],
                }
            time.sleep(0.08)
        with HISTORY_SYNC_LOCK:
            HISTORY_SYNC_STATE[key] = {
                **state,
                "running": False,
                "remaining": 0,
                "fetchedCount": len(fetched),
                "errors": errors[-10:],
                "finishedAt": now_iso(),
            }

    threading.Thread(target=runner, daemon=True).start()
    return state


def history_sync_state(yyyymm: str, years: int = 10) -> dict:
    key = f"{yyyymm}_{years}"
    with HISTORY_SYNC_LOCK:
        return dict(HISTORY_SYNC_STATE.get(key, {}))


def snapshot_path(market: str, data_ym: str) -> Path:
    return SNAPSHOT_DIR / f"{market}_{data_ym}.json"


def save_snapshot(market: str, rows: List[dict], raw_content: Optional[bytes] = None, partial: bool = False) -> Optional[str]:
    if not rows:
        return None
    data_ym = rows[0]["dataYm"]
    if raw_content is not None:
        (RAW_DIR / f"{market}_{data_ym}.csv").write_bytes(raw_content)
    payload = {
        "market": market,
        "marketLabel": MARKETS[market]["label"],
        "dataYm": data_ym,
        "dataYmDisplay": ad_to_display(data_ym),
        "savedAt": now_iso(),
        "partial": partial,
        "rows": rows,
    }
    snapshot_path(market, data_ym).write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return data_ym


def import_local_snapshots() -> List[str]:
    imported: List[str] = []
    pattern = re.compile(r"(?P<market>listed|otc|L|O)[_-]?(?P<ym>\d{5,6})", re.I)
    for file_path in IMPORT_DIR.glob("*.csv"):
        match = pattern.search(file_path.stem)
        if not match:
            continue
        market_token = match.group("market").upper()
        market = "listed" if market_token in {"L", "LISTED"} else "otc"
        rows = parse_revenue_csv(file_path.read_bytes(), market)
        if not rows:
            continue
        data_ym = save_snapshot(market, rows, file_path.read_bytes())
        if data_ym:
            imported.append(f"{market}_{data_ym}")
    return imported


def sync_once() -> dict:
    ensure_dirs()
    status = read_status()
    status["lastSyncStarted"] = now_iso()
    status.setdefault("markets", {})
    status["errors"] = []
    imported = import_local_snapshots()

    for market, info in MARKETS.items():
        try:
            raw = fetch_url(info["url"])
            rows = parse_revenue_csv(raw, market)
            data_ym = save_snapshot(market, rows, raw)
            status["markets"][market] = {
                "label": info["label"],
                "latestDataYm": data_ym,
                "latestDataYmDisplay": ad_to_display(data_ym or ""),
                "latestRows": len(rows),
                "sourceUrl": info["url"],
                "updatedAt": now_iso(),
            }
        except (URLError, TimeoutError, OSError, UnicodeDecodeError) as exc:
            status["errors"].append(f"{info['label']} sync failed: {exc}")

    try:
        target_month = previous_month_yyyymm()
        status["latestPartialSummary"] = sync_summary_month(target_month)
    except Exception as exc:
        status["errors"].append(f"partial summary sync failed: {exc}")

    status["lastSync"] = now_iso()
    status["imported"] = imported
    write_status(status)
    return status


def load_snapshot(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def iter_snapshots(reverse: bool = False) -> Iterable[dict]:
    ensure_dirs()
    for path in sorted(SNAPSHOT_DIR.glob("*.json"), reverse=reverse):
        payload = load_snapshot(path)
        if payload:
            yield payload


def snapshot_count() -> int:
    ensure_dirs()
    return sum(1 for _ in SNAPSHOT_DIR.glob("*.json"))


def snapshots_for_month(yyyymm: str) -> Dict[str, dict]:
    found: Dict[str, dict] = {}
    for market in MARKETS:
        payload = load_snapshot(snapshot_path(market, yyyymm))
        if payload:
            found[market] = payload
    return found


def latest_snapshot_for_market(market: str) -> Optional[dict]:
    paths = sorted(SNAPSHOT_DIR.glob(f"{market}_*.json"), reverse=True)
    for path in paths:
        payload = load_snapshot(path)
        if payload:
            return payload
    return None


def latest_snapshots_by_market() -> Dict[str, dict]:
    latest: Dict[str, dict] = {}
    for market in MARKETS:
        snapshot = latest_snapshot_for_market(market)
        if snapshot:
            latest[market] = snapshot
    return latest


def history_for_company(
    snapshots: Iterable[dict], market: str, company_id: str, current_ym: str, years: int
) -> List[dict]:
    current_idx = month_index(current_ym)
    lower_bound = current_idx - years * 12
    history: List[dict] = []
    for snapshot in snapshots:
        data_ym = snapshot.get("dataYm", "")
        if len(data_ym) != 6 or data_ym == current_ym:
            continue
        data_idx = month_index(data_ym)
        if data_idx < lower_bound or data_idx >= current_idx:
            continue
        if snapshot.get("market") != market:
            continue
        for row in snapshot.get("rows", []):
            if row.get("companyId") == company_id:
                history.append({"dataYm": data_ym, "revenue": row.get("monthlyRevenue") or 0})
                break
    return history


def history_stats_by_company(snapshots: Iterable[dict], current_ym: str, years: int) -> Dict[tuple, dict]:
    current_idx = month_index(current_ym)
    lower_bound = current_idx - years * 12
    stats: Dict[tuple, dict] = {}
    for snapshot in snapshots:
        data_ym = snapshot.get("dataYm", "")
        if len(data_ym) != 6 or data_ym == current_ym:
            continue
        data_idx = month_index(data_ym)
        if data_idx < lower_bound or data_idx >= current_idx:
            continue
        market = snapshot.get("market")
        if not market:
            continue
        for row in snapshot.get("rows", []):
            revenue = row.get("monthlyRevenue")
            if revenue is None:
                continue
            key = (market, row.get("companyId"))
            current = stats.get(key)
            count = 1 if current is None else current["count"] + 1
            if current is None or revenue > current["max"]:
                stats[key] = {"count": count, "max": revenue, "maxYm": data_ym}
            else:
                current["count"] = count
    return stats


def annotate_highs(rows: List[dict], yyyymm: str, years: int = 10) -> List[dict]:
    history_stats = history_stats_by_company(iter_snapshots(), yyyymm, years)
    annotated: List[dict] = []
    for row in rows:
        stats = history_stats.get((row["market"], row["companyId"]))
        historical_max = stats["max"] if stats else None
        is_high = historical_max is not None and row["monthlyRevenue"] > historical_max
        annotated.append(
            {
                **row,
                "historicalSameMonthCount": stats["count"] if stats else 0,
                "historicalSameMonthMax": historical_max,
                "historicalSameMonthMaxYm": stats["maxYm"] if stats else None,
                "revenueGap": row["monthlyRevenue"] - historical_max if historical_max is not None else None,
                "isNewHigh": is_high,
            }
        )
    return annotated


def build_base_company_rows() -> Dict[str, List[dict]]:
    latest = latest_snapshots_by_market()
    return {market: snapshot.get("rows", []) for market, snapshot in latest.items()}


def sync_partial_month(yyyymm: str, force: bool = False) -> dict:
    status = read_status()
    status.setdefault("partialMonths", {})
    existing = snapshots_for_month(yyyymm)
    if existing and not force:
        return {"month": yyyymm, "markets": {m: len(s.get("rows", [])) for m, s in existing.items()}, "skipped": True}

    summary = sync_summary_month(yyyymm)
    if sum(summary.get("markets", {}).values()) > 0:
        status["partialMonths"][yyyymm] = {**summary, "updatedAt": now_iso(), "source": "mopsov-summary"}
        write_status(status)
        return summary

    base_by_market = build_base_company_rows()
    result = {"month": yyyymm, "markets": {}, "errors": []}
    for market, base_rows in base_by_market.items():
        rows: List[dict] = []
        consecutive_failures = 0
        for base_row in base_rows:
            try:
                fetched = fetch_company_month(base_row, yyyymm)
                if fetched:
                    rows.append(fetched)
                    if len(rows) % 25 == 0:
                        save_snapshot(market, rows, partial=True)
                consecutive_failures = 0
                time.sleep(0.25)
            except Exception as exc:  # keep partial sync moving
                result["errors"].append(f"{market} {base_row.get('companyId')} failed: {exc}")
                consecutive_failures += 1
                if consecutive_failures >= 40 and not rows:
                    result["errors"].append(f"{market} stopped after 40 consecutive source errors")
                    break
        if rows:
            save_snapshot(market, rows, partial=True)
        result["markets"][market] = len(rows)

    status["partialMonths"][yyyymm] = {**result, "updatedAt": now_iso()}
    write_status(status)
    return result


def start_partial_sync(yyyymm: str, force: bool = False) -> dict:
    with PARTIAL_SYNC_LOCK:
        state = PARTIAL_SYNC_STATE.get(yyyymm)
        if state and state.get("running"):
            return state
        state = {"month": yyyymm, "running": True, "startedAt": now_iso(), "force": force}
        PARTIAL_SYNC_STATE[yyyymm] = state

    def runner() -> None:
        try:
            result = sync_partial_month(yyyymm, force=force)
            with PARTIAL_SYNC_LOCK:
                PARTIAL_SYNC_STATE[yyyymm] = {
                    **result,
                    "running": False,
                    "startedAt": state["startedAt"],
                    "finishedAt": now_iso(),
                }
        except Exception as exc:
            with PARTIAL_SYNC_LOCK:
                PARTIAL_SYNC_STATE[yyyymm] = {
                    "month": yyyymm,
                    "running": False,
                    "startedAt": state["startedAt"],
                    "finishedAt": now_iso(),
                    "errors": [str(exc)],
                }

    threading.Thread(target=runner, daemon=True).start()
    return state


def partial_sync_state(yyyymm: str) -> dict:
    with PARTIAL_SYNC_LOCK:
        return dict(PARTIAL_SYNC_STATE.get(yyyymm, {}))


def revenue_payload(yyyymm: Optional[str], mode: str = "all", years: int = 10) -> dict:
    yyyymm = yyyymm or (month_options()[0] if month_options() else "")
    snapshots = snapshots_for_month(yyyymm)
    if not snapshots:
        start_partial_sync(yyyymm)
        snapshots = snapshots_for_month(yyyymm)

    rows: List[dict] = []
    partial = False
    for snapshot in snapshots.values():
        partial = partial or bool(snapshot.get("partial"))
        rows.extend(snapshot.get("rows", []))

    history_result = None
    missing_history = missing_rolling_history_months(yyyymm, years) if rows else []
    if rows:
        history_result = start_history_sync(yyyymm, years)
    if missing_history:
        rows = [
            {
                **row,
                "historicalSameMonthCount": 0,
                "historicalSameMonthMax": None,
                "historicalSameMonthMaxYm": None,
                "revenueGap": None,
                "isNewHigh": False,
            }
            for row in rows
        ]
    else:
        rows = annotate_highs(rows, yyyymm, years)
    high_count = sum(1 for row in rows if row.get("isNewHigh"))
    if mode == "highs":
        rows = [row for row in rows if row.get("isNewHigh")]
        rows.sort(key=lambda item: item.get("revenueGap") or 0, reverse=True)
    else:
        rows.sort(key=lambda item: (item.get("market"), item.get("companyId")))

    return {
        "generatedAt": now_iso(),
        "selectedMonth": yyyymm,
        "selectedMonthDisplay": ad_to_display(yyyymm),
        "years": years,
        "mode": mode,
        "partial": partial,
        "syncing": bool(partial_sync_state(yyyymm).get("running")),
        "syncState": partial_sync_state(yyyymm),
        "historySync": history_result,
        "historySyncing": bool(history_sync_state(yyyymm, years).get("running")),
        "historyComplete": not bool(missing_history),
        "historyMissingMonths": len(missing_history),
        "months": [{"value": item, "label": ad_to_display(item)} for item in month_options()],
        "snapshotCount": snapshot_count(),
        "companyCount": len(rows),
        "allCompanyCount": sum(len(snapshot.get("rows", [])) for snapshot in snapshots.values()),
        "highCount": high_count,
        "rows": rows,
    }


def json_response(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def static_response(handler: BaseHTTPRequestHandler, path: Path) -> None:
    if not path.exists() or not path.is_file():
        handler.send_error(404)
        return
    content_type = "text/html; charset=utf-8" if path.suffix == ".html" else "text/css; charset=utf-8"
    body = path.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class RevenueHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}", flush=True)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/api/status":
            json_response(self, read_status())
            return
        if parsed.path == "/api/months":
            json_response(self, {"months": [{"value": item, "label": ad_to_display(item)} for item in month_options()]})
            return
        if parsed.path == "/api/revenues":
            years = int(query.get("years", ["10"])[0])
            mode = query.get("mode", ["all"])[0]
            month = query.get("month", [None])[0]
            json_response(self, revenue_payload(month, mode=mode, years=max(1, min(years, 20))))
            return
        if parsed.path == "/api/highs":
            years = int(query.get("years", ["10"])[0])
            month = query.get("month", [None])[0]
            json_response(self, revenue_payload(month, mode="highs", years=max(1, min(years, 20))))
            return
        if parsed.path in {"/", "/index.html"}:
            static_response(self, PUBLIC_DIR / "index.html")
            return
        static_path = (PUBLIC_DIR / parsed.path.lstrip("/")).resolve()
        if PUBLIC_DIR.resolve() in static_path.parents:
            static_response(self, static_path)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/sync":
            json_response(self, sync_once())
            return
        if parsed.path == "/api/sync-month":
            query = parse_qs(parsed.query)
            month = query.get("month", [previous_month_yyyymm()])[0]
            force = query.get("force", ["0"])[0] == "1"
            json_response(self, start_partial_sync(month, force=force))
            return
        self.send_error(404)


def sync_loop() -> None:
    sync_once()
    while True:
        time.sleep(SYNC_INTERVAL_SECONDS)
        sync_once()


def main() -> None:
    ensure_dirs()
    port = int(os.environ.get("PORT", "8088"))
    host = os.environ.get("HOST", "127.0.0.1")
    server = ThreadingHTTPServer((host, port), RevenueHandler)
    thread = threading.Thread(target=sync_loop, daemon=True)
    thread.start()
    print(f"Revenue site running at http://{host}:{port}", flush=True)
    print(f"Auto sync interval: {SYNC_INTERVAL_SECONDS} seconds", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
