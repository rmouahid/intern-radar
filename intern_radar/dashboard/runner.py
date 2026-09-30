"""Start the scheduled run from the dashboard, through systemd.

The dashboard never runs the pipeline itself: it asks systemd to start the
same `intern-radar-run.service` the timer uses, so a run started by hand
gets the same environment, logs and timeout, and systemd never starts a
second instance while one is active.
"""

import subprocess
from collections.abc import Callable
from dataclasses import dataclass

UNIT = "intern-radar-run.service"
Runner = Callable[..., subprocess.CompletedProcess]


@dataclass(frozen=True)
class RunStatus:
    running: bool
    result: str  # systemd Result of the last run ("success", "exit-code"…)
    started: str  # e.g. "Wed 2026-09-30 18:00:22 UTC", "" if never
    finished: str
    summary: str  # last "fetched=… scored=…" line, "" if unknown


def run_status(runner: Runner = subprocess.run) -> RunStatus:
    shown = runner(
        [
            "systemctl",
            "show",
            UNIT,
            "-p",
            "ActiveState",
            "-p",
            "Result",
            "-p",
            "ExecMainStartTimestamp",
            "-p",
            "ExecMainExitTimestamp",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    fields = dict(
        line.split("=", 1) for line in shown.stdout.splitlines() if "=" in line
    )
    journal = runner(
        ["journalctl", "-u", UNIT, "-n", "40", "--no-pager", "-o", "cat"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    summaries = [
        line for line in journal.stdout.splitlines() if line.startswith("fetched=")
    ]
    return RunStatus(
        running=fields.get("ActiveState") in ("active", "activating"),
        result=fields.get("Result", ""),
        started=fields.get("ExecMainStartTimestamp", ""),
        finished=fields.get("ExecMainExitTimestamp", ""),
        summary=summaries[-1] if summaries else "",
    )


def start_run(runner: Runner = subprocess.run) -> bool:
    """Ask systemd to start a run now; False when systemd refuses."""
    proc = runner(
        ["systemctl", "start", "--no-block", UNIT],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return proc.returncode == 0
