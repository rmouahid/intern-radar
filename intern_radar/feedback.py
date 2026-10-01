"""The candidate's 👍/👎 on offers, summarised for the scoring prompt.

The summary is bounded (entries per side and characters) so that the prompt,
sent with every scoring batch, stays small whatever the history.
"""

from collections.abc import Sequence

from intern_radar.models import Job

MAX_PER_SIDE = 8
MAX_CHARS = 1200


def _line(job: Job, reason: str) -> str:
    line = f"- {job.company[:40]} — {job.title[:90]}"
    return f"{line} (reason: {reason[:120]})" if reason else line


def feedback_summary(
    entries: Sequence[tuple[Job, int, str, str]],
    per_side: int = MAX_PER_SIDE,
    max_chars: int = MAX_CHARS,
) -> str:
    """Latest liked and disliked offers as prompt text ("" when none).

    `entries` are (job, vote, reason, date), latest first.
    """
    liked = [_line(job, reason) for job, vote, reason, _ in entries if vote > 0]
    disliked = [_line(job, reason) for job, vote, reason, _ in entries if vote < 0]
    if not liked and not disliked:
        return ""
    # Each side gets half the budget, so likes never crowd out dislikes.
    budget = max_chars // 2 if liked and disliked else max_chars
    parts = []
    if liked:
        parts.append(_block("Offers the candidate liked:", liked[:per_side], budget))
    if disliked:
        parts.append(
            _block("Offers the candidate disliked:", disliked[:per_side], budget)
        )
    return "\n".join(parts)


def _block(heading: str, lines: list[str], budget: int) -> str:
    text = heading
    for line in lines:
        if len(text) + 1 + len(line) > budget:
            break
        text += "\n" + line
    return text
