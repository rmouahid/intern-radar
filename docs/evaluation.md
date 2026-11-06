# Evaluating the LLM triage

The triage decides which offers the candidate sees. This page measures it
against hand labels: precision (shown offers the candidate wanted) and
recall (wanted offers that were shown), for two prompt variants.

```bash
poetry run intern-radar eval sample --n 100          # eval/triage/offers.jsonl
# label every offer in the web app: Plus → Évaluation du tri (/eval)
poetry run intern-radar eval run --prompt v1         # current production prompt
poetry run intern-radar eval run --prompt v2         # anchored ai_relevance levels
poetry run intern-radar eval report                  # docs/eval.md
```

- **Sample**: offers the LLM already triaged in the production database,
  30 % from the notified band, 30 % from the digest band and 40 % below or
  excluded, so that both errors (shown but unwanted, wanted but hidden) can
  occur. `--seed` makes the draw reproducible.
- **Label**: one question per offer, without seeing its score: would I want
  intern-radar to show me this offer? "Je ne sais pas" leaves it unlabelled
  (it comes back at the end and is excluded from the metrics).
- **Run**: the labelled offers are triaged again with the chosen prompt, in
  batches of 10 like production, then scored by `ranking.final_score` with
  the profile's weights and thresholds. *Shown* means a score at or above
  the digest threshold, *notified* at or above the immediate threshold. An
  offer the model leaves unanswered counts as not shown.
- **Prompts**: `v1` is `scorer.INSTRUCTIONS`, used in production; `v2`
  (`INSTRUCTIONS_V2`) differs only by anchored levels for `ai_relevance`,
  the field that weighs most in the score. Each run costs about 10 LLM calls
  per 100 offers on the subscription quota; tokens and cost are saved with
  the predictions in `eval/triage/runs/`.
