# Aurora SRE behavioural tests (Monocle Test Tools)

Trace-based tests for Aurora's LangGraph RCA (root-cause analysis) agent. Monocle
records each investigation as a structured trace — the agent invocation, every
tool call, token usage, and timings — and each test asserts against that trace:
which agent ran, which tools it called, what it was asked, and its token/duration
cost.

Aurora is a **distributed docker-compose system** (Flask API + Celery worker +
Postgres / Weaviate / Redis / Vault), so the agent runs inside its containers,
not in the test process. That shapes the suite:

- **Offline tests** replay recorded good-trace fixtures — fast, no stack needed.
- **The live test** drives the *running* stack over its REST API and asserts on
  the trace the run emits (fetched from the Celery worker). It's **opt-in**.

## Layout

- `test_aurora.py` — two offline tests + one live test
- `conftest.py` — trace paths + `run_aurora()` (drives the live stack, returns the emitted trace)
- `traces/` — recorded good-trace fixtures the offline tests replay
- `requirements.txt` — dependencies

## Tests

| Test | Scenario | What it asserts |
|---|---|---|
| `test_aurora_rca_redis_latency` | RCA of a redis pool-exhaustion incident | terminal_exec, knowledge_base_search, write_findings; `does_not_call` web_search; budget |
| `test_aurora_rca_web_search` | RCA that reaches out to the web | + web_search; budget |
| `test_aurora_live` | Live run against the running stack | agent + input + budget |

## Run

```bash
pip install -r requirements.txt
pytest tests/monocle/ -k "not live"       # offline, no stack, no keys

# Live (opt-in): needs the Aurora stack up + these in the repo .env:
#   AURORA_TEST_USER_ID, AURORA_TEST_ORG_ID, INTERNAL_API_SECRET
AURORA_RUN_LIVE=1 pytest tests/monocle/
```

The live test creates a session, posts a query to `:5080/chat_api`, waits for the
background run to complete, then pulls the emitted trace from the worker container
and asserts on it. It skips by default so keyless CI stays green.

## Add your own test

1. Run an incident under Monocle and capture the trace (`.monocle/` by default).
2. Move it into `traces/` and load it with
   `monocle_trace_asserter.with_trace_source("file", trace_path=path)`.
3. Assert with the fluent API — `called_agent(...)`, `called_tool(...)`,
   `under_token_limit(...)`, `under_duration(..., span_type="workflow")` — and add
   it alongside the others.

## Evaluations (optional)

Each offline test carries a commented-out `check_eval("hallucination", ...)`.
Monocle can run evaluation checks against a trace; set `OKAHU_API_KEY` and
uncomment to enable.
