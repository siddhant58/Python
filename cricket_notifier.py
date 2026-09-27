"""Polls CricketData.org (cricapi.com) for a live India vs West Indies ODI
and fires a Windows toast notification at the end of every over and on
every wicket.

Run on the Windows machine where you want the toasts to appear:

    pip install requests plyer win11toast
    set CRICKETDATA_API_KEY=your_key_here      (PowerShell: $env:CRICKETDATA_API_KEY="...")
    python cricket_notifier.py

win11toast is optional and Windows-only; the script falls back to plyer
(also cross-platform) if it isn't installed.
"""

import os
import sys
import time
import logging

import requests

API_KEY_ENV_VAR = "CRICKETDATA_API_KEY"
BASE_URL = "https://api.cricapi.com/v1"
POLL_SECONDS = 45
TEAM_A = "india"
TEAM_B = "west indies"
MATCH_TYPE = "odi"
REQUEST_TIMEOUT = 15

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("cricket_notifier")


def notify(title: str, message: str) -> None:
    try:
        from win11toast import toast

        toast(title, message)
        return
    except Exception:
        pass

    try:
        from plyer import notification

        notification.notify(title=title, message=message, timeout=15)
    except Exception as exc:
        log.warning("Could not show a toast notification (%s): %s | %s", exc, title, message)


def get_api_key() -> str:
    api_key = os.environ.get(API_KEY_ENV_VAR)
    if not api_key:
        log.error("Environment variable %s is not set.", API_KEY_ENV_VAR)
        sys.exit(1)
    return api_key


def find_live_match(api_key: str):
    resp = requests.get(
        f"{BASE_URL}/currentMatches",
        params={"apikey": api_key, "offset": 0},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    for match in data.get("data", []):
        teams = [t.lower() for t in match.get("teams", [])]
        match_type = (match.get("matchType") or "").lower()
        if match_type != MATCH_TYPE:
            continue
        if any(TEAM_A in t for t in teams) and any(TEAM_B in t for t in teams):
            return match
    return None


def get_match_info(api_key: str, match_id: str):
    resp = requests.get(
        f"{BASE_URL}/match_info",
        params={"apikey": api_key, "offset": 0, "id": match_id},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    return payload.get("data")


def format_over_message(inning_name: str, runs: int, overs: float, wickets: int, over_runs: int, over_wkts: int) -> str:
    run_rate = runs / overs if overs else 0.0
    wkt_note = f", {over_wkts} wkt(s) fell this over" if over_wkts else ""
    return (
        f"{inning_name}: {runs}/{wickets} in {overs} overs "
        f"(RR {run_rate:.2f}). This over: {over_runs} run(s){wkt_note}."
    )


def poll_loop(api_key: str, match_id: str, match_name: str) -> None:
    # per-innings tracking, keyed by innings label (e.g. "India Inning 1")
    state = {}

    log.info("Watching %s (id=%s)", match_name, match_id)
    notify("Cricket tracker started", f"Now watching: {match_name}")

    while True:
        try:
            info = get_match_info(api_key, match_id)
            if not info:
                log.warning("No match_info payload; will retry.")
            else:
                status = (info.get("status") or "").lower()
                for score in info.get("score", []) or []:
                    inning_name = score.get("inning", "Unknown inning")
                    runs = score.get("r", 0)
                    wickets = score.get("w", 0)
                    overs = score.get("o", 0.0)

                    prev = state.get(
                        inning_name,
                        {"int_over": 0, "runs_at_over": 0, "wkts_at_over": 0, "wickets": 0},
                    )

                    # Wicket notification: fires as soon as the wicket count
                    # increases, independent of over completion.
                    if wickets > prev["wickets"]:
                        notify(
                            f"WICKET! {inning_name}",
                            format_over_message(
                                inning_name, runs, overs, wickets,
                                over_runs=runs - prev["runs_at_over"],
                                over_wkts=wickets - prev["wkts_at_over"],
                            ),
                        )

                    # End-of-over notification: fires when the completed-over
                    # count (floor of overs) increases.
                    int_over = int(overs)
                    if int_over > prev["int_over"]:
                        over_runs = runs - prev["runs_at_over"]
                        over_wkts = wickets - prev["wkts_at_over"]
                        notify(
                            f"Over {int_over} complete - {inning_name}",
                            format_over_message(inning_name, runs, overs, wickets, over_runs, over_wkts),
                        )
                        prev["runs_at_over"] = runs
                        prev["wkts_at_over"] = wickets
                        prev["int_over"] = int_over

                    prev["wickets"] = wickets
                    state[inning_name] = prev

                if "won" in status or "abandoned" in status or info.get("matchEnded"):
                    notify("Match finished", info.get("status", "The match has ended."))
                    log.info("Match ended (%s). Stopping.", status)
                    break

        except requests.RequestException as exc:
            log.warning("API request failed: %s", exc)
        except Exception:
            log.exception("Unexpected error while polling; continuing.")

        time.sleep(POLL_SECONDS)


def main() -> None:
    api_key = get_api_key()

    match = find_live_match(api_key)
    if not match:
        log.error("No live India vs West Indies ODI found right now. Exiting.")
        sys.exit(1)

    poll_loop(api_key, match["id"], match.get("name", "India vs West Indies"))


if __name__ == "__main__":
    main()
