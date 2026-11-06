"""Precision and recall of the LLM triage against hand labels (`intern-radar eval`).

1. `eval sample` draws offers the LLM already triaged from the database,
   stratified by their current score so that every outcome is represented,
   into `eval/triage/offers.jsonl`.
2. The candidate labels each offer in the web app (`/eval`): would I want to
   see this offer, yes or no. The label is written back into the same file.
3. `eval run --prompt v1|v2` triages the labelled offers again with one
   prompt variant (same model, same batches of 10 as production) and saves
   the predictions with the token usage in `eval/triage/runs/`.
4. `eval report` compares the runs in `docs/eval.md`.

An offer is predicted positive when its final score reaches the digest
threshold (it would be shown to the candidate); the stricter "notified"
decision uses the immediate threshold.
"""

import json
import os
import random
import sqlite3
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from intern_radar.config import Profile
from intern_radar.description import clean_description
from intern_radar.models import Job
from intern_radar.ranking import final_score, with_rule_based_visa
from intern_radar.scorer import DESCRIPTION_LIMIT, Scorer

BATCH = 10  # offers per LLM call, as in production
# Share of the sample drawn from each score band (high, middle, low or
# excluded); a band with too few offers leaves its share to the others.
BANDS = (("high", 0.3), ("middle", 0.3), ("low", 0.4))


@dataclass
class EvalOffer:
    id: str
    company: str
    tier: str
    title: str
    location: str
    url: str
    posted_at: str | None
    description: str
    label: bool | None = None  # True: the candidate wants to see it

    def job(self) -> Job:
        return Job(
            id=self.id,
            company=self.company,
            tier=self.tier,  # type: ignore[arg-type]
            title=self.title,
            location=self.location,
            url=self.url,
            description=self.description,
            source=self.id.split(":", 1)[0],
            posted_at=self.posted_at,
        )


def _band(score: float | None, digest: float, immediate: float) -> str:
    if score is not None and score >= immediate:
        return "high"
    if score is not None and score >= digest:
        return "middle"
    return "low"


def sample_offers(
    db_path: str, n: int, digest: float, immediate: float, seed: int = 0
) -> list[EvalOffer]:
    """`n` triaged offers, stratified by score band, in a reproducible order."""
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = db.execute(
            "SELECT id, company, tier, title, location, url, posted_at, description,"
            " score FROM jobs WHERE assessment IS NOT NULL ORDER BY id"
        ).fetchall()
    finally:
        db.close()
    bands: dict[str, list[tuple]] = {name: [] for name, _ in BANDS}
    for row in rows:
        bands[_band(row[8], digest, immediate)].append(row)
    rng = random.Random(seed)
    chosen: list[tuple] = []
    for name, share in BANDS:
        want = round(n * share)
        chosen += rng.sample(bands[name], min(want, len(bands[name])))
    rest = [row for row in rows if row not in chosen]
    chosen += rng.sample(rest, min(n - len(chosen), len(rest)))
    rng.shuffle(chosen)
    return [
        EvalOffer(
            id=row[0],
            company=row[1],
            tier=row[2],
            title=row[3],
            location=row[4] or "",
            url=row[5],
            posted_at=row[6],
            description=clean_description(row[7] or "")[:DESCRIPTION_LIMIT],
        )
        for row in chosen[:n]
    ]


def load_offers(path: Path) -> list[EvalOffer]:
    with path.open(encoding="utf-8") as f:
        return [EvalOffer(**json.loads(line)) for line in f if line.strip()]


def save_offers(path: Path, offers: list[EvalOffer]) -> None:
    """Written to a temporary file then renamed: a crash never truncates labels."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        "".join(json.dumps(asdict(o), ensure_ascii=False) + "\n" for o in offers),
        encoding="utf-8",
    )
    os.replace(tmp, path)


@dataclass
class Prediction:
    id: str
    score: float | None
    ai_relevance: int | None
    shown: bool  # score >= digest threshold
    notified: bool  # score >= immediate threshold


@dataclass
class Run:
    prompt: str
    model: str
    predictions: list[Prediction]
    usage: dict[str, float] = field(default_factory=dict)  # tokens and cost


def run_prompt(
    offers: list[EvalOffer], scorer: Scorer, profile: Profile
) -> list[Prediction]:
    """Triage the offers in batches of 10 and score them like the pipeline."""
    digest, immediate = profile.thresholds.digest, profile.thresholds.immediate
    predictions = []
    for start in range(0, len(offers), BATCH):
        batch = offers[start : start + BATCH]
        assessments = scorer.assess([offer.job() for offer in batch])
        for offer in batch:
            assessment = assessments.get(offer.id)
            if assessment is None:  # unanswered: counted as not shown
                predictions.append(Prediction(offer.id, None, None, False, False))
                continue
            assessment = with_rule_based_visa(
                assessment, offer.location, profile.self_sponsored_countries
            )
            score = final_score(
                offer.tier,  # type: ignore[arg-type]
                assessment,
                profile.weights,
                profile.thresholds.min_relevance,
                profile.visa_penalties,
            )
            predictions.append(
                Prediction(
                    offer.id,
                    score,
                    assessment.ai_relevance,
                    score is not None and score >= digest,
                    score is not None and score >= immediate,
                )
            )
    return predictions


def confusion(
    labels: dict[str, bool],
    predictions: list[Prediction],
    decision: Callable[[Prediction], bool],
) -> dict[str, float]:
    """Counts, precision, recall and F1 of one decision on labelled offers."""
    tp = fp = fn = tn = 0
    for p in predictions:
        if p.id not in labels:
            continue
        predicted, wanted = decision(p), labels[p.id]
        tp += predicted and wanted
        fp += predicted and not wanted
        fn += wanted and not predicted
        tn += not predicted and not wanted
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": precision, "recall": recall, "f1": f1}  # fmt: skip


def save_run(path: Path, run: Run) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "prompt": run.prompt,
        "model": run.model,
        "usage": run.usage,
        "predictions": [asdict(p) for p in run.predictions],
    }
    path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")


def load_run(path: Path) -> Run:
    data = json.loads(path.read_text(encoding="utf-8"))
    return Run(
        data["prompt"],
        data["model"],
        [Prediction(**p) for p in data["predictions"]],
        data.get("usage", {}),
    )


def render_report(offers: list[EvalOffer], runs: list[Run], command: str) -> str:
    """docs/eval.md: one row per run, for the shown and notified decisions."""
    labels = {o.id: o.label for o in offers if o.label is not None}
    positives = sum(labels.values())
    lines = [
        "# LLM triage evaluation",
        "",
        "_Generated by `intern-radar eval report`; do not edit by hand._",
        "",
        f"- {len(labels)} offers labelled by hand ({positives} the candidate wants"
        f" to see, {len(labels) - positives} not), drawn from the production"
        " database among offers the LLM had triaged, stratified by score band",
        "- An offer is *shown* when its final score reaches the digest threshold,"
        " *notified* when it reaches the immediate threshold",
        "- Each run triages the same offers in batches of 10, like production",
        "",
        "Reproduce:",
        "",
        "```bash",
        command,
        "```",
        "",
        "| Prompt | Model | Decision | Precision | Recall | F1 | TP | FP | FN"
        " | Tokens | Cost |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for run in runs:
        tokens = int(run.usage.get("tokens", 0))
        cost = run.usage.get("cost", 0.0)
        for name, decision in (
            ("shown", lambda p: p.shown),
            ("notified", lambda p: p.notified),
        ):
            m = confusion(labels, run.predictions, decision)
            lines.append(
                f"| {run.prompt} | {run.model} | {name} | {m['precision']:.2f}"
                f" | {m['recall']:.2f} | {m['f1']:.2f} | {m['tp']} | {m['fp']}"
                f" | {m['fn']} | {tokens:,} | ${cost:.2f} |"
            )
    return "\n".join(lines) + "\n"


def usage_recorder() -> tuple[dict[str, float], Callable[[dict[str, Any]], None]]:
    """A dict summing tokens and cost, and the callback that fills it."""
    totals: dict[str, float] = {"tokens": 0, "cost": 0.0, "calls": 0}

    def record(usage: dict[str, Any]) -> None:
        totals["tokens"] += usage.get("input", 0) + usage.get("output", 0)
        totals["cost"] += usage.get("cost", 0.0)
        totals["calls"] += 1

    return totals, record
