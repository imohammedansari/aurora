"""Trace-based behavioural tests for Aurora's SRE / RCA agent, using Monocle Test Tools.

Aurora runs on LangGraph inside a distributed docker-compose stack, so the RCA
output is a stream of graph events rather than one answer string -- behaviour is
validated through the tools the orchestrator calls (`terminal_exec`,
`knowledge_base_search`, `write_findings`, and `web_search` when it reaches out).

The two offline tests replay recorded good traces (fast, no stack). The live
test drives the running stack and asserts on the trace it emits; it is opt-in
(`AURORA_RUN_LIVE=1`) because it needs the full stack up + the `.env` credentials.

    pytest tests/monocle/ -k "not live"              # offline, no stack
    AURORA_RUN_LIVE=1 pytest tests/monocle/           # also the live run
"""
import os

import pytest
from monocle_test_tools import TraceAssertion

from conftest import TRACES, run_aurora

# Incident: API latency correlated with redis-cache connection-pool exhaustion.
# Real trace: 169,876 tokens, ~204s; terminal_exec x13, knowledge_base_search x28,
# write_findings x20.
TRACE_REDIS = str(TRACES / "monocle_trace_aurora-sre_e431fdad786686d660dbfa49c6082376_2026-07-08_00.08.38.json")
# Incident: application logs/config investigation that also reached out to the web.
# Real trace: 61,744 tokens, ~80s; web_search x2, terminal_exec x19,
# knowledge_base_search x5, write_findings x4 -- the run that exercises web_search.
TRACE_WEB = str(TRACES / "monocle_trace_aurora-sre_f9c328cb82748b17455e476943481918_2026-07-08_01.18.51.json")


# --- Offline: replay recorded good traces ---------------------------------

def test_aurora_rca_redis_latency(monocle_trace_asserter: TraceAssertion):
    """RCA of a redis connection-pool exhaustion incident (no web reach-out)."""
    monocle_trace_asserter.with_trace_source("file", trace_path=TRACE_REDIS)

    monocle_trace_asserter.called_agent("LangGraph")
    monocle_trace_asserter.called_tool("terminal_exec")
    monocle_trace_asserter.called_tool("knowledge_base_search")
    monocle_trace_asserter.called_tool("write_findings")
    monocle_trace_asserter.does_not_call_tool("web_search")
    monocle_trace_asserter.under_token_limit(250_000)
    monocle_trace_asserter.under_duration(300, units="seconds", span_type="workflow")

    # Eval layer (deferred -- set OKAHU_API_KEY and uncomment to enable):
    # monocle_trace_asserter.with_evaluation("okahu").check_eval("hallucination", "no_hallucination") \
    #     .check_eval("contextual_precision", "high_precision") \
    #     .check_eval("sentiment", "positive") \
    #     .check_eval("bias", "unbiased")


def test_aurora_rca_web_search(monocle_trace_asserter: TraceAssertion):
    """RCA that reaches out to the web -- exercises the web_search tool path."""
    monocle_trace_asserter.with_trace_source("file", trace_path=TRACE_WEB)

    monocle_trace_asserter.called_agent("LangGraph")
    monocle_trace_asserter.called_tool("terminal_exec")
    monocle_trace_asserter.called_tool("knowledge_base_search")
    monocle_trace_asserter.called_tool("write_findings")
    monocle_trace_asserter.called_tool("web_search")
    monocle_trace_asserter.under_token_limit(100_000)
    monocle_trace_asserter.under_duration(150, units="seconds", span_type="workflow")

    # monocle_trace_asserter.with_evaluation("okahu").check_eval("hallucination", "no_hallucination") \
    #     .check_eval("contextual_precision", "high_precision") \
    #     .check_eval("sentiment", "positive") \
    #     .check_eval("bias", "unbiased")


# --- Live: drive the running Aurora stack (opt-in) ------------------------

@pytest.mark.skipif(
    os.getenv("AURORA_RUN_LIVE") != "1",
    reason="live Aurora run is opt-in: set AURORA_RUN_LIVE=1 with the stack up",
)
def test_aurora_live(monocle_trace_asserter: TraceAssertion):
    """Live run against the stack; assert the agent ran and stayed in budget."""
    # "ask" = read-only agent ("chat" emits only a thin workflow span). Structure
    # + budget only, no tool asserts -- the live tool mix varies run to run.
    trace = run_aurora(
        "Investigate common root causes of elevated API latency and summarize them.",
        mode="ask",
    )
    monocle_trace_asserter.with_trace_source("file", trace_path=trace)

    monocle_trace_asserter.called_agent("LangGraph")
    monocle_trace_asserter.contains_input("latency")
    monocle_trace_asserter.under_token_limit(1_000_000)
    monocle_trace_asserter.under_duration(600, units="seconds", span_type="workflow")

    # monocle_trace_asserter.with_evaluation("okahu").check_eval("hallucination", "no_hallucination") \
    #     .check_eval("contextual_precision", "high_precision") \
    #     .check_eval("sentiment", "positive") \
    #     .check_eval("bias", "unbiased")
