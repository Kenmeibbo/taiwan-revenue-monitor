"""Update the public Sites cache without invoking an AI model."""
import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SITE = "https://zhewei-twstock-monthly-high-tracker.skywei.chatgpt.site"
TAIPEI = timezone(timedelta(hours=8))


def request_json(path, method="GET"):
    request = Request(SITE + path, data=b"" if method == "POST" else None,
                      method=method, headers={"Accept": "application/json",
                                             "User-Agent": "ZheweiRevenueScheduler/1.0"})
    try:
        with urlopen(request, timeout=240) as response:
            return json.load(response)
    except HTTPError as error:
        try:
            detail = json.loads(error.read()).get("errors")
        except (ValueError, AttributeError):
            detail = None
        raise RuntimeError(f"Site returned HTTP {error.code}: {detail or error.reason}") from error


def eligible(policy):
    if policy.get("timezone") != "Asia/Taipei" or policy.get("hours") != [8, 11, 14, 17, 20, 23]:
        raise RuntimeError("Unexpected collection policy; refuse to update")
    return policy.get("allowed") is True


def checkpoint(result, path):
    """Save one genuine successful synchronization receipt per calendar month."""
    captured = result.get("previous", result) if result.get("skipped") else result
    if captured.get("state") != "complete" or captured.get("errors"):
        return
    month = captured["policy"]["date"][:6]
    target = Path(path)
    if target.exists() and json.loads(target.read_text(encoding="utf-8")).get("month") == month:
        return
    receipt = {"month": month, "site": SITE, "completedAt": captured["completedAt"],
               "slot": captured["policy"]["slot"], "results": captured["results"]}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Check deployment/policy without writing data")
    parser.add_argument("--checkpoint", default=".github/revenue-sync-status.json")
    args = parser.parse_args()
    # No overnight network call, even if manually dispatched from GitHub.
    if not args.check and datetime.now(TAIPEI).hour not in [8, 11, 14, 17, 20, 23]:
        print(json.dumps({"skipped": True, "reason": "outside-hour"}))
        return
    policy_result = request_json("/api/scheduled-refresh")
    allowed = eligible(policy_result["policy"])
    if args.check or not allowed:
        print(json.dumps(policy_result, ensure_ascii=True))
        return
    result = request_json("/api/scheduled-refresh", "POST")
    if result.get("errors"):
        raise RuntimeError("Official source update failed: " + str(result["errors"]))
    print(json.dumps(result, ensure_ascii=True))
    checkpoint(result, args.checkpoint)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, URLError, ValueError, KeyError) as error:
        raise SystemExit(str(error)) from error
