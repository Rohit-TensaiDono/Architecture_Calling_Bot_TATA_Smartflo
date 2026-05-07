"""
db.py — SQLite conversation logger for Mierae Solar Voice Bot

Tables:
  calls        — one row per call (session)
  conversations — one row per Q&A exchange within a call

Usage:
  from db import db
  db.create_call(session_id, mobile_number)
  db.add_exchange(session_id, question, answer, state)
  db.complete_call(session_id, lead_data)
"""

import sqlite3
import threading
from datetime import datetime
from contextlib import contextmanager

DB_PATH = "solar_calls.db"

# Thread-local storage for connections
_local = threading.local()
_completion_listeners = []
_completion_listeners_lock = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    """Get a thread-local database connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")   # Write-ahead logging — faster concurrent writes
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return _local.conn


@contextmanager
def _cursor():
    conn = _get_conn()
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


# ─────────────────────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────────────────────

CREATE_CALLS_TABLE = """
CREATE TABLE IF NOT EXISTS calls (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT    NOT NULL UNIQUE,
    mobile_number   TEXT    DEFAULT 'unknown',   -- This will be the caller / DID
    customer_number TEXT    DEFAULT 'unknown',   -- The actual customer
    call_sid        TEXT    DEFAULT '',
    started_at      TEXT    NOT NULL,
    ended_at        TEXT    DEFAULT NULL,
    call_status     TEXT    DEFAULT 'ongoing',   -- ongoing | completed | dropped
    -- Lead qualification data (collected during the call)
    property_type   TEXT    DEFAULT NULL,        -- independent | apartment | commercial
    bill_range      TEXT    DEFAULT NULL,        -- low | mid | high
    timeline        TEXT    DEFAULT NULL,        -- 1month | 1to3months | enquiry
    payment_pref    TEXT    DEFAULT NULL         -- full | loan
);
"""

CREATE_CONV_TABLE = """
CREATE TABLE IF NOT EXISTS conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    turn        INTEGER NOT NULL,               -- exchange number within the call (1-based)
    state       TEXT    NOT NULL,               -- e.g. STATE_1, STATE_2 …
    question    TEXT    NOT NULL,               -- bot's question / message
    answer      TEXT    NOT NULL,               -- caller's transcribed reply
    timestamp   TEXT    NOT NULL,
    FOREIGN KEY (session_id) REFERENCES calls(session_id)
);
"""

CREATE_IDX_SESSION = "CREATE INDEX IF NOT EXISTS idx_conv_session ON conversations(session_id);"
CREATE_IDX_MOBILE  = "CREATE INDEX IF NOT EXISTS idx_calls_mobile  ON calls(mobile_number);"


def init_db():
    """Create tables if they don't exist. Call once at startup."""
    with _cursor() as cur:
        cur.execute(CREATE_CALLS_TABLE)
        cur.execute(CREATE_CONV_TABLE)
        cur.execute(CREATE_IDX_SESSION)
        cur.execute(CREATE_IDX_MOBILE)
        
        # Migration: add customer_number if it doesn't exist in older databases
        try:
            cur.execute("ALTER TABLE calls ADD COLUMN customer_number TEXT DEFAULT 'unknown'")
        except sqlite3.OperationalError:
            pass # Column already exists
            
    print(f"[DB] Initialized — {DB_PATH}")


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def register_call_completion_listener(listener):
    """Register a callback invoked once when a call first reaches a final state."""
    with _completion_listeners_lock:
        _completion_listeners.append(listener)


class ConversationDB:

    def create_call(self, session_id: str, mobile_number: str = "unknown", customer_number: str = "unknown", call_sid: str = "") -> None:
        """Register a new call session in the database."""
        try:
            with _cursor() as cur:
                cur.execute(
                    """INSERT OR IGNORE INTO calls
                       (session_id, mobile_number, customer_number, call_sid, started_at, call_status)
                       VALUES (?, ?, ?, ?, ?, 'ongoing')""",
                    (session_id, mobile_number, customer_number, call_sid, datetime.now().isoformat())
                )
            print(f"[DB] Call created — session:{session_id[:8]}… DID:{mobile_number} Customer:{customer_number}")
        except Exception as e:
            print(f"[DB] create_call error: {e}")

    def update_mobile(self, session_id: str, mobile_number: str) -> None:
        """Update the mobile number for an existing session (useful when number arrives late)."""
        try:
            with _cursor() as cur:
                cur.execute(
                    "UPDATE calls SET mobile_number=? WHERE session_id=?",
                    (mobile_number, session_id)
                )
            print(f"[DB] Mobile updated — session:{session_id[:8]}… mobile:{mobile_number}")
        except Exception as e:
            print(f"[DB] update_mobile error: {e}")

    def add_exchange(self, session_id: str, question: str, answer: str, state: str, turn: int) -> None:
        """
        Log one Q&A exchange.
        - question : the bot's message (what the bot said / asked)
        - answer   : the caller's transcribed reply
        - state    : current bot state name (e.g. 'STATE_2')
        - turn     : exchange index (1-based, incremented by caller)
        """
        try:
            with _cursor() as cur:
                cur.execute(
                    """INSERT INTO conversations
                       (session_id, turn, state, question, answer, timestamp)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (session_id, turn, state, question, answer, datetime.now().isoformat())
                )
        except Exception as e:
            print(f"[DB] add_exchange error: {e}")

    def complete_call(self, session_id: str, lead_data: dict = None, status: str = "completed") -> bool:
        """
        Mark the call as complete and persist collected lead qualification data.
        lead_data keys: property_type, bill_range, timeline, payment
        """
        if lead_data is None:
            lead_data = {}
        try:
            with _cursor() as cur:
                cur.execute(
                    """UPDATE calls SET
                        ended_at      = ?,
                        call_status   = ?,
                        property_type = COALESCE(?, property_type),
                        bill_range    = COALESCE(?, bill_range),
                        timeline      = COALESCE(?, timeline),
                        payment_pref  = COALESCE(?, payment_pref)
                       WHERE session_id = ? AND call_status = 'ongoing'""",
                    (
                        datetime.now().isoformat(),
                        status,
                        lead_data.get("property_type"),
                        lead_data.get("bill_range"),
                        lead_data.get("timeline"),
                        lead_data.get("payment"),
                        session_id,
                    )
                )
                changed = cur.rowcount > 0
            if not changed:
                print(f"[DB] Call completion ignored - session:{session_id[:8]} already final or missing")
                return False
            print(f"[DB] Call completed — session:{session_id[:8]}… status:{status} lead:{lead_data}")

            def _send_webhook():
                try:
                    import requests
                    call_info = self.get_call(session_id)
                    conv_info = self.get_conversation(session_id)
                    
                    qa_dict = {}
                    if conv_info:
                        for row in conv_info:
                            qa_dict[row["question"]] = row["answer"]
                            
                    payload = {
                        "session_id": session_id,
                        "mobile_no": call_info.get("mobile_number") if call_info else "unknown",
                        "call_status": call_info.get("call_status") if call_info else status,
                        "customer_number": call_info.get("customer_number") if call_info else "unknown",
                        "call_id": call_info.get("call_sid") if call_info else "",
                        "qa_dict": qa_dict
                    }
                    
                    import os
                    webhook_url = os.getenv("WEBHOOK_URL", "https://exactable-magniloquently-lavada.ngrok-free.dev/webhook/call")
                    print(f"[Webhook] Sending call data for {session_id}, payload: {payload}")
                    resp = requests.post(webhook_url, json=payload, timeout=10)
                    print(f"[Webhook] Sent call data for {session_id}, call_id: {payload['call_id']}, status: {resp.status_code} and  response body: {resp.text}")
                except Exception as e:
                    print(f"[Webhook] Failed to send call data: {e}")
                    
            import threading
            threading.Thread(target=_send_webhook, daemon=True).start()

            call_info = self.get_call(session_id)
            with _completion_listeners_lock:
                listeners = list(_completion_listeners)
            for listener in listeners:
                try:
                    listener(session_id, status, call_info or {})
                except Exception as e:
                    print(f"[DB] completion listener error: {e}")

            return True

        except Exception as e:
            print(f"[DB] complete_call error: {e}")
            return False

    def get_call(self, session_id: str) -> dict | None:
        """Fetch call record by session_id."""
        try:
            conn = _get_conn()
            row = conn.execute(
                "SELECT * FROM calls WHERE session_id=?", (session_id,)
            ).fetchone()
            return dict(row) if row else None
        except Exception as e:
            print(f"[DB] get_call error: {e}")
            return None

    def get_conversation(self, session_id: str) -> list[dict]:
        """Fetch all Q&A exchanges for a call, ordered by turn."""
        try:
            conn = _get_conn()
            rows = conn.execute(
                "SELECT * FROM conversations WHERE session_id=? ORDER BY turn",
                (session_id,)
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            print(f"[DB] get_conversation error: {e}")
            return []

    def get_calls_by_mobile(self, mobile_number: str) -> list[dict]:
        """Fetch all call records for a given mobile number."""
        try:
            conn = _get_conn()
            rows = conn.execute(
                "SELECT * FROM calls WHERE mobile_number=? ORDER BY started_at DESC",
                (mobile_number,)
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            print(f"[DB] get_calls_by_mobile error: {e}")
            return []

    def get_recent_calls(self, limit: int = 50) -> list[dict]:
        """Fetch recent call records with their conversation count."""
        try:
            conn = _get_conn()
            rows = conn.execute(
                """SELECT c.*, COUNT(cv.id) as exchanges
                   FROM calls c
                   LEFT JOIN conversations cv ON c.session_id = cv.session_id
                   GROUP BY c.session_id
                   ORDER BY c.started_at DESC
                   LIMIT ?""",
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            print(f"[DB] get_recent_calls error: {e}")
            return []


# ── Singleton ──
db = ConversationDB()

# Initialize tables on import
init_db()

# ── Stale Call Cleanup Loop ──
def _cleanup_stale_calls_loop():
    import time
    from datetime import datetime
    while True:
        try:
            conn = _get_conn()
            rows = conn.execute(
                "SELECT session_id, started_at FROM calls WHERE call_status = 'ongoing'"
            ).fetchall()
            now = datetime.now()
            for row in rows:
                try:
                    started = datetime.fromisoformat(row["started_at"])
                    if (now - started).total_seconds() > 600:  # 10 minutes
                        print(f"[DB] Call stuck in ongoing for >10 mins, force-dropping: {row['session_id']}")
                        db.complete_call(row["session_id"], status="dropped")
                except Exception as e:
                    pass
        except Exception as e:
            print(f"[DB] Cleanup loop error: {e}")
        time.sleep(60)

import threading
threading.Thread(target=_cleanup_stale_calls_loop, daemon=True).start()
