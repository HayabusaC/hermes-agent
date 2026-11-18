"""The fork's activity-windowed dashboard reads (``activity_*``, see persistence/conversation/usage.py).

Upstream's dashboard reads window on ``sessions.started_at``. This fork's panel windows on the
session's LAST ACTIVITY instead (a conversation opened days ago that is still spending belongs in
"today"), carries the invoice-first ``cost`` per model row so the rows sum to ``total_cost``, and
windows auxiliary rows on their own ``last_seen`` (an aux call happens throughout a session).
These cases pin that behaviour on the SQLite store.
"""
import time

import pytest

from persistence.sqlite._holder import StoreHolder
from persistence.sqlite.conversation._store.sessions import create_session
from persistence.sqlite.conversation._store.usage import record_auxiliary_usage, update_token_counts
from persistence_assembly import open_persistence_reader

HOUR = 3600.0
DAY = 86400.0


@pytest.fixture
def store(tmp_path):
    """A store with two sessions started 2-3 days ago but active within the last hours (one settled
    by invoice), and one aux call inside the older session."""
    holder = StoreHolder(tmp_path / "state.db")
    now = time.time()
    create_session(holder, "s-unsettled", source="cli")
    update_token_counts(holder, "s-unsettled", input_tokens=1000, output_tokens=100, model="main-model",
                        billing_provider="nous", estimated_cost_usd=1.0, api_call_count=1)
    create_session(holder, "s-settled", source="cli")
    update_token_counts(holder, "s-settled", input_tokens=500, output_tokens=50, model="main-model",
                        billing_provider="nous", estimated_cost_usd=0.5, actual_cost_usd=0.8,
                        cost_status="actual", api_call_count=1)
    record_auxiliary_usage(holder, "s-unsettled", "compression", model="main-model",
                           billing_provider="nous", input_tokens=200, output_tokens=20,
                           estimated_cost_usd=0.2)
    with holder._lock:
        holder._conn.execute("UPDATE sessions SET started_at = ?, last_activity_at = ? WHERE id = ?",
                             (now - 3 * DAY, now - HOUR, "s-unsettled"))
        holder._conn.execute("UPDATE sessions SET started_at = ?, last_activity_at = ? WHERE id = ?",
                             (now - 2 * DAY, now - 2 * HOUR, "s-settled"))
        holder._conn.commit()
    with open_persistence_reader(holder.db_path) as opened:
        yield opened


def _cutoff() -> float:
    """The panel's 1-day view: neither seeded session started inside it."""
    return time.time() - DAY


def test_activity_daily_usage_buckets_on_activity_not_start(store):
    cutoff = _cutoff()
    day = time.strftime("%Y-%m-%d", time.localtime())
    rows = store.usage_analytics.activity_daily_usage(active_after=cutoff)
    assert [(r["day"], r["sessions"], r["input_tokens"]) for r in rows] == [(day, 2, 1500)]
    # The same window on upstream's started_at read drops both sessions: neither started today.
    assert store.usage_analytics.daily_usage(started_after=cutoff) == []


def test_activity_totals_apply_the_invoice_first_cost(store):
    cutoff = _cutoff()
    totals = store.usage_analytics.activity_session_usage_totals(active_after=cutoff)
    assert totals["total_sessions"] == 2
    assert totals["total_estimated_cost"] == pytest.approx(1.5)
    assert totals["total_actual_cost"] == pytest.approx(0.8)
    # A settled session contributes its invoice, never its estimate too: 1.0 + 0.8, not 1.5 + 0.8.
    assert totals["total_cost"] == pytest.approx(1.8)
    assert "total_cost" not in store.usage_analytics.session_usage_totals(started_after=cutoff)


def test_activity_by_model_carries_provider_and_cost(store):
    rows = store.usage_analytics.activity_session_usage_by_model(active_after=_cutoff())
    assert [(r["model"], r["provider"], r["cost"], r["input_tokens"], r["cache_write_tokens"]) for r in rows] == [
        ("main-model", "nous", pytest.approx(1.8), 1500, 0)
    ]


def test_activity_aux_rows_window_on_their_own_last_seen(store):
    cutoff = _cutoff()
    rows = store.usage_analytics.activity_auxiliary_usage_by_model_task(active_after=cutoff)
    assert [(r["model"], r["task"], r["input_tokens"]) for r in rows] == [("main-model", "compression", 200)]
    # The aux call sits in a session that started three days ago, so upstream's started_at window
    # never sees it even though it was billed an hour ago.
    assert store.usage_analytics.auxiliary_usage_by_model_task(started_after=cutoff) == []
