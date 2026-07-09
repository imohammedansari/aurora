"""Pytest scaffold for the Aurora SRE Monocle test suite.

Aurora is a distributed docker-compose system (Flask API + Celery worker +
Postgres / Weaviate / Redis / Vault), so its agent runs inside the containers,
not in this process. Two consequences shape this suite:

* Offline tests replay recorded good-trace fixtures (fast, no stack needed).
* The live test (opt-in, ``AURORA_RUN_LIVE=1``) drives the *running* stack over
  its REST API and asserts on the trace the run emits, which it fetches from the
  Celery worker container. ``run_aurora`` below is that entry.

All credentials (``X-User-ID`` / ``X-Org-ID`` / ``X-Internal-Secret``) are read
from the repo's gitignored ``.env`` -- never hard-coded here.
"""
import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from urllib import request as _request

HERE = Path(__file__).resolve().parent
TRACES = HERE / "traces"
REPO_ROOT = HERE.parent.parent

try:  # optional: the live test needs the .env; offline tests don't
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

_BASE = os.getenv("AURORA_BASE_URL", "http://localhost:5080").rstrip("/") + "/chat_api"
_WORKER = os.getenv("AURORA_WORKER_CONTAINER", "aurora-sre-celery_worker-1")
_TRACE_DIR = os.getenv("AURORA_TRACE_DIR", "/shared/.monocle")


def _headers():
    uid, org, sec = (os.getenv("AURORA_TEST_USER_ID"), os.getenv("AURORA_TEST_ORG_ID"),
                     os.getenv("INTERNAL_API_SECRET"))
    if not (uid and org and sec):
        raise RuntimeError(
            "Live Aurora run needs AURORA_TEST_USER_ID, AURORA_TEST_ORG_ID and "
            "INTERNAL_API_SECRET in the repo .env")
    return {"Content-Type": "application/json", "X-User-ID": uid,
            "X-Org-ID": org, "X-Internal-Secret": sec}


def _api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = _request.Request(_BASE + path, data=data, headers=_headers(), method=method)
    with _request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read() or "{}")


def _worker_traces():
    """Set of trace file paths currently in the worker container's output dir."""
    out = subprocess.run(
        ["docker", "exec", _WORKER, "sh", "-c", f"ls -1 {_TRACE_DIR}/*.json 2>/dev/null"],
        capture_output=True, text=True)
    return {ln for ln in out.stdout.splitlines() if ln.strip()}


def run_aurora(query: str, mode: str = "chat") -> str:
    """Drive the running Aurora stack once and return a path to the trace it emits.

    Creates a session, posts the query, waits for the background (Celery) run to
    write a fresh trace in the worker container, then copies that trace out to a
    temp file for the test to load. Raises if the stack/worker is unreachable so
    the (opt-in) live test errors loudly rather than asserting on a stale trace.
    """
    before = _worker_traces()
    session = _api("POST", "/sessions", {"title": f"monocle-live-{uuid.uuid4().hex[:8]}"})
    sid = session["id"]
    _api("POST", f"/sessions/{sid}/messages", {"message": query, "mode": mode})

    # A single run emits several trace files: thin http.process spans plus the
    # rich agent trace. Poll until the one carrying our query AND an
    # agentic.invocation span appears (that's the agent run, written on
    # completion), then copy it out.
    dest = Path(os.getenv("TMPDIR", "/tmp")) / f"aurora_live_{sid}.json"
    marker = query[:40]
    deadline = time.time() + 300
    while time.time() < deadline:
        time.sleep(4)
        for path in sorted(_worker_traces() - before):
            cat = subprocess.run(["docker", "exec", _WORKER, "cat", path],
                                 capture_output=True, text=True)
            if cat.returncode != 0 or not cat.stdout or marker not in cat.stdout:
                continue
            try:
                spans = json.loads(cat.stdout)
            except ValueError:
                continue
            if any(sp.get("attributes", {}).get("span.type") == "agentic.invocation"
                   for sp in spans):
                dest.write_text(cat.stdout)
                return str(dest)
    raise RuntimeError("Aurora run emitted no agent trace (agentic.invocation) for the query")
