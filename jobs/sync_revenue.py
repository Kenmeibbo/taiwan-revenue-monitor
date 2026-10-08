"""Update the public Sites cache without invoking an AI model."""
import argparse
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SITE = "https://zhewei-twstock-monthly-high-tracker.skywei.chatgpt.site"


def captured_result(result):
    return result.get("previous", result) if result.get("skipped") else result


def deferred_reports(result):
    capture = captured_result(result)
    if "deferred" in capture:
        return capture["deferred"]
    return [report for item in capture.get("results", []) for report in item.get("live", {}).get("deferred", [])]


def write_job_summary(result):
    """Report partial coverage without treating unavailable company reports as a system outage."""
    import os
    capture = captured_result(result)
    deferred = deferred_reports(result)
    state = "running" if result.get("reason") == "running" else "partial" if deferred else "up-to-date"
    print(json.dumps({"dataStatus": state, "deferred": deferred}, ensure_ascii=True))
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        lines = ["## Revenue synchronization", "", "Data coverage: " + state,
                 "Last check: " + str(capture.get("completedAt", "unknown"))]
        if deferred:
            lines += ["", "The following official reports remain pending; stored data was retained:"]
            lines += ["- " + item["companyId"] + ": " + item["reason"] for item in deferred]
        with Path(summary_path).open("a", encoding="utf-8") as stream:
            stream.write("\n".join(lines) + "\n")


def request_json(path, method="GET"):
    request = Request(SITE + path, data=b"" if method == "POST" else None,
                      method=method, headers={"Accept": "application/json",
                                             "User-Agent": "ZheweiRevenueScheduler/1.0"})
    try:
        with urlopen(request, timeout=240) as response:
            return json.load(response)
    except HTTPError as error:
        try:
            result = json.loads(error.read())
            if isinstance(result, dict) and result.get("state") == "complete" and result.get("results"):
                return result
            detail = result.get("errors")
        except (ValueError, AttributeError):
            detail = None
        raise RuntimeError(f"Site returned HTTP {error.code}: {detail or error.reason}") from error


def eligible(policy):
    if policy.get("timezone") != "Asia/Taipei" or policy.get("intervalMinutes") != 5 or policy.get("allDay") is not True:
        raise RuntimeError("Unexpected collection policy; refuse to update")
    return policy.get("allowed") is True


def checkpoint(result, path):
    """Save one genuine successful synchronization receipt per calendar month."""
    captured = captured_result(result)
    if captured.get("state") != "complete" or captured.get("errors"):
        return
    month = captured["policy"]["date"][:6]
    target = Path(path)
    data_status = "partial" if deferred_reports(result) else "up-to-date"
    if target.exists():
        previous = json.loads(target.read_text(encoding="utf-8"))
        if previous.get("month") == month and previous.get("dataStatus", "up-to-date") == data_status:
            return
    receipt = {"month": month, "site": SITE, "completedAt": captured["completedAt"],
               "slot": captured["policy"]["slot"], "results": captured["results"], "dataStatus": data_status}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def pending_reports(result):
    capture = result.get("previous", result) if result.get("skipped") else result
    for item in capture.get("results", []):
        if "live" in item:
            return item["live"].get("pending", 0)
    return 0


def live_progress(result):
    capture = result.get("previous", result) if result.get("skipped") else result
    return next((item["live"] for item in capture.get("results", []) if "live" in item), {})


def refresh():
    started = time.monotonic()
    result = request_json("/api/scheduled-refresh", "POST")
    for _ in range(14):
        if result.get("reason") == "running" or pending_reports(result) == 0 or time.monotonic() - started > 300 or (not result.get("skipped") and live_progress(result).get("updated") == 0):
            break
        result = request_json("/api/scheduled-refresh?drain=1", "POST")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Check deployment/policy without writing data")
    parser.add_argument("--checkpoint", default=".github/revenue-sync-status.json")
    args = parser.parse_args()
    policy_result = request_json("/api/scheduled-refresh")
    allowed = eligible(policy_result["policy"])
    if args.check or not allowed:
        print(json.dumps(policy_result, ensure_ascii=True))
        return
    result = refresh()
    capture = captured_result(result)
    if capture.get("errors"):
        raise RuntimeError("Official source update failed: " + str(capture["errors"]))
    print(json.dumps(result, ensure_ascii=True))
    write_job_summary(result)
    checkpoint(result, args.checkpoint)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, URLError, ValueError, KeyError) as error:
        raise SystemExit(str(error)) from error

