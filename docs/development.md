# Development guide

## Setup

```bash
poetry install                       # runtime + dev dependencies (pytest, ruff)
cp config/profile.example.yaml config/profile.yaml
poetry run pytest -q                 # 216 tests, offline, < 1 s
poetry run ruff check . && poetry run ruff format --check .
```

No network, LLM, Telegram or SMTP access is needed to run the tests.

## Repository layout

| Path | Content |
|---|---|
| `intern_radar/` | package (see the module map in [architecture.md](architecture.md#2-components)) |
| `tests/` | mirrors the package: `tests/sources/`, `tests/letters/`, `tests/test_<module>.py` |
| `tests/factories.py` | `make_job`, `make_assessment`, `make_profile`, `mock_client` |
| `config/` | `companies.yaml`, `profile.example.yaml` |
| `deploy/` | systemd units, logrotate |
| `docs/` | this documentation; `docs/superpowers/` holds the design specs and implementation plans of each feature |

## Conventions

- **Style**: ruff (`E`, `F`, `I`, `UP`, `B`), line length 88, `ruff format`.
  Type hints on public functions; dataclasses (frozen) for domain objects.
- **Language**: code, comments, docs and commits in English; user-facing
  Telegram and e-mail text in French.
- **Git Flow**: `main` (releases), `develop` (integration, default branch),
  `feature/<issue>-<description>`; one issue per change.
- **Conventional Commits**: `feat:`, `fix:`, `docs:`, `test:`, `build:`,
  `ci:`… imperative, ≤ 72 characters; the body explains *why*; `Closes #N`.
- **Linear history**: branches are rebased on `develop` and merged with
  "Rebase and merge"; no merge commits.
- **Pull requests**: title in Conventional Commits form; description with
  context, solution, test results and the issue it closes; CI (ruff +
  pytest) must pass.

## Testing strategy

| Layer | Approach |
|---|---|
| Pure logic (`prefilter`, `ranking`, `letters/checks`, formatters) | direct unit tests, including edge cases (multi-location, HTML escaping, caption limits) |
| Source adapters | `mock_client(routes)` answers with payloads that mirror the real API responses (captured from the live APIs); pagination and per-posting failures covered |
| LLM | `ScriptedBackend` / `FakeBackend` return prepared JSON; tests assert prompts, schemas and the handling of invalid or partial answers |
| Telegram, SMTP | fake clients recording calls; the Telegram client itself is tested against a mocked transport, including token redaction |
| Store | in-memory SQLite |
| Orchestration (`pipeline`, `letters/service`, `letters/inbox`) | end to end with fakes and an injected clock |
| CLI | Typer `CliRunner` with monkeypatched collaborators |

Workflow for any change: write the failing test, watch it fail for the
expected reason, implement the minimum, run the whole suite, commit.
Behaviour that depends on live services (a new board id, a prompt change)
is additionally checked by hand: `check-sources`, `run --dry-run`, or a real
`letter <job_id>` read back with `pypdf`.

## Adding a source

1. **Capture the API shape**: find the JSON endpoint the career site uses
   and note the fields for id, title, location, URL, date and description
   (list and detail calls).
2. **Write the test** in `tests/sources/test_<name>.py` with a minimal
   payload mirroring the real response: one internship to keep, one
   non-internship to drop, one known id to skip, and pagination if any.
3. **Implement** `intern_radar/sources/<name>.py`:

   ```python
   class ExampleSource:
       def __init__(self, client: httpx.Client) -> None:
           self._client = client

       def fetch(self, company: Company, known_ids: Container[str]) -> list[Job]:
           board = require_param(company, "board")
           listing = get_json(self._client, "GET", API.format(board=board))

           def convert(item: dict[str, Any]) -> Job | None:
               job_id = f"example:{board}:{item['id']}"
               if job_id in known_ids or not is_internship_title(item["title"]):
                   return None
               return Job(id=job_id, company=company.name, tier=company.tier, ...)

           return collect(company, listing.get("jobs", []), convert)
   ```

   - build ids as `<source>:<board>:<native id>` (stable, unique);
   - filter titles with `is_internship_title` and skip `known_ids` *before*
     any detail request;
   - call the network only through `get_json` (errors never leak query
     strings) and convert items through `collect` (one bad posting is
     skipped, not fatal);
   - cap pagination.
4. **Register** it in `SOURCE_NAMES` and `build_sources`
   (`intern_radar/sources/__init__.py`); `tests/sources/test_registry.py`
   checks both stay in sync.
5. **Configure** companies in `companies.yaml` and run
   `poetry run intern-radar check-sources`.

## Changing prompts

Prompts live next to their schema (`scorer.py`, `letters/writer.py`).
A prompt change is a behaviour change:

- keep the JSON schema and the Python validation in sync;
- add or update a test asserting the instruction is present;
- measure before and after on the same offers (tokens from the CLI
  envelope, quality by reading the output) and record the numbers in
  [pipeline.md §7](pipeline.md#7-llm-usage-and-cost-measured).

## Releasing and deploying

The production host runs the `develop` checkout:

```bash
git switch develop && git pull --ff-only
poetry install --only main
systemctl restart intern-radar-letters.service   # timers pick up the code on their next run
journalctl -u intern-radar-run -n 20
```

Releases to `main` follow Git Flow (`release/x.y.z` branch, version bump,
tag `vX.Y.Z`).
