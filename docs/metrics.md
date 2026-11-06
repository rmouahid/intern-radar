# Operating metrics

Production database, 2026-10-07 to 2026-11-05 (Europe/Paris days), 30 days with at least one run. Regenerate with:

```bash
poetry run intern-radar metrics --out docs/metrics.md --chart docs/metrics.svg --start 2026-10-07 --end 2026-11-05
```

## Summary

| Metric | Value |
|---|---:|
| New internship postings per day (median) | 103 |
| Removed by the rules before the LLM | 63 % of 3264 |
| LLM tokens per day (median, every purpose) | 113,956 |
| LLM cost per day (median, API-equivalent) | $0.15 |
| Run duration p50 / p95 | 69 s / 5 min |
| Detection to Telegram notification p50 / p95 | 3 min / 48.1 h |

Rules run before any LLM call: internship-title regex, France-only locations, out-of-scope fields, past cycles, offers older than the age limit, aggregator copies of postings already stored.

## Per day

| Day | Runs | New postings | Sent to the LLM | Removed by rules | Notified | LLM tokens | LLM cost |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-10-07 | 8 | 114 | 32 | 72 % | 0 | 171,296 | $0.54 |
| 2026-10-08 | 8 | 177 | 51 | 71 % | 2 | 247,625 | $0.71 |
| 2026-10-09 | 8 | 163 | 55 | 66 % | 2 | 201,929 | $0.58 |
| 2026-10-10 | 8 | 133 | 41 | 69 % | 0 | 96,934 | $0.22 |
| 2026-10-11 | 8 | 79 | 31 | 61 % | 6 | 125,524 | $0.41 |
| 2026-10-12 | 8 | 103 | 64 | 38 % | 2 | 1,250,719 | $2.97 |
| 2026-10-13 | 8 | 161 | 65 | 60 % | 3 | 166,610 | $0.18 |
| 2026-10-14 | 8 | 164 | 55 | 66 % | 2 | 165,985 | $0.15 |
| 2026-10-15 | 8 | 120 | 41 | 66 % | 2 | 138,460 | $0.15 |
| 2026-10-16 | 8 | 135 | 37 | 73 % | 5 | 129,147 | $0.19 |
| 2026-10-17 | 8 | 78 | 17 | 78 % | 1 | 84,550 | $0.10 |
| 2026-10-18 | 8 | 46 | 8 | 83 % | 0 | 27,441 | $0.01 |
| 2026-10-19 | 8 | 93 | 46 | 51 % | 2 | 187,714 | $0.32 |
| 2026-10-20 | 8 | 84 | 48 | 43 % | 3 | 158,025 | $0.19 |
| 2026-10-21 | 8 | 77 | 43 | 44 % | 1 | 110,154 | $0.07 |
| 2026-10-22 | 8 | 92 | 35 | 62 % | 0 | 107,641 | $0.10 |
| 2026-10-23 | 8 | 129 | 57 | 56 % | 3 | 165,154 | $0.19 |
| 2026-10-24 | 8 | 69 | 19 | 72 % | 0 | 45,814 | $0.06 |
| 2026-10-25 | 8 | 62 | 24 | 61 % | 0 | 50,204 | $0.05 |
| 2026-10-26 | 8 | 72 | 35 | 51 % | 0 | 97,228 | $0.07 |
| 2026-10-27 | 8 | 85 | 34 | 60 % | 0 | 113,956 | $0.07 |
| 2026-10-28 | 8 | 103 | 41 | 60 % | 0 | 95,918 | $0.03 |
| 2026-10-29 | 8 | 99 | 36 | 64 % | 0 | 66,441 | $0.02 |
| 2026-10-30 | 8 | 103 | 55 | 47 % | 2 | 109,717 | $0.11 |
| 2026-10-31 | 8 | 75 | 11 | 85 % | 0 | 29,583 | $0.01 |
| 2026-11-01 | 8 | 112 | 31 | 72 % | 0 | 52,593 | $0.05 |
| 2026-11-02 | 8 | 55 | 21 | 62 % | 2 | 127,419 | $0.28 |
| 2026-11-03 | 8 | 238 | 85 | 64 % | 2 | 213,058 | $0.22 |
| 2026-11-04 | 9 | 116 | 34 | 71 % | 0 | 96,522 | $0.12 |
| 2026-11-05 | 8 | 127 | 63 | 50 % | 4 | 160,047 | $0.18 |

## Run duration per step (p50)

| Step | p50 |
|---|---:|
| collect | 48 s |
| score | 12 s |
| notify | 0 s |
| searches | 0 s |

## LLM usage by purpose

| Purpose | Input tokens | Output tokens | Cost (API-equivalent) |
|---|---:|---:|---:|
| chance | 1,926,468 | 60,807 | $5.56 |
| cv | 32,857 | 3,692 | $0.17 |
| letter | 38,467 | 4,587 | $0.19 |
| scoring | 2,043,902 | 682,628 | $2.43 |
