import asyncio
import json
import sqlite3
import threading
from datetime import datetime
from typing import Callable, Optional

from db import DB_PATH


FINAL_PROVIDER_STATUSES = {
    "completed",
    "answered",
    "failed",
    "missed",
    "busy",
    "no_answer",
    "not_answered",
    "cancelled",
    "canceled",
    "dropped",
}
ACTIVE_CONTACT_STATUSES = ("dialing", "active")
FAILED_PROVIDER_STATUSES = {
    "failed",
    "missed",
    "busy",
    "no_answer",
    "not_answered",
    "cancelled",
    "canceled",
}


def first_value(data: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = data.get(key)
        if value:
            return str(value)
    return ""


def extract_number(item) -> str:
    if isinstance(item, dict):
        return first_value(
            item,
            (
                "customer_number",
                "customerNumber",
                "destination_number",
                "destination",
                "phone_number",
                "phone",
                "mobile_number",
                "mobile",
                "number",
            ),
        ).strip().lstrip("+")
    return str(item).strip().lstrip("+")


def extract_agent(item) -> str:
    if isinstance(item, dict):
        return first_value(
            item,
            (
                "caller_id",
                "callerId",
                "agent_number",
                "agentNumber",
                "phone_number",
                "phone",
                "mobile_number",
                "mobile",
                "number",
            ),
        ).strip().lstrip("+")
    return str(item).strip().lstrip("+")


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def extract_bulk_payload(body: dict) -> tuple[list[str], list[str], str | None]:
    raw_numbers = (
        body.get("numbers")
        or body.get("contacts")
        or body.get("leads")
        or body.get("phone_numbers")
        or body.get("customer_numbers")
        or []
    )
    raw_agents = (
        body.get("agents")
        or body.get("assigned_agents")
        or body.get("caller_ids")
        or body.get("agent_ids")
        or []
    )

    if isinstance(raw_numbers, str):
        raw_numbers = [raw_numbers]
    if isinstance(raw_agents, str):
        raw_agents = [raw_agents]

    numbers = [extract_number(item) for item in raw_numbers]
    agents = [extract_agent(item) for item in raw_agents]

    caller_id = body.get("caller_id", "")
    if caller_id and not agents:
        agents = [str(caller_id).strip().lstrip("+")]

    numbers = [number for number in numbers if number]
    agents = dedupe_preserve_order([agent for agent in agents if agent])

    if not body.get("allow_duplicate_contacts", False):
        unique_numbers = dedupe_preserve_order(numbers)
        if len(unique_numbers) != len(numbers):
            return numbers, agents, "duplicate contact numbers in payload; pass allow_duplicate_contacts=true to override"

    return numbers, agents, None


class BatchCallManager:
    def __init__(self, dialer: Callable[[str, Optional[str]], dict]):
        self._dialer = dialer
        self._lock = threading.RLock()
        self._loop = None
        self._init_db()

    def set_loop(self, loop):
        self._loop = loop

    def _connect(self):
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS batch_jobs (
                    job_id TEXT PRIMARY KEY,
                    agent_ids TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'running',
                    total INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS batch_contacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    customer_number TEXT NOT NULL,
                    agent_id TEXT DEFAULT NULL,
                    batch_no INTEGER DEFAULT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    session_id TEXT DEFAULT NULL,
                    call_sid TEXT DEFAULT NULL,
                    provider_status TEXT DEFAULT NULL,
                    result_json TEXT DEFAULT NULL,
                    started_at TEXT DEFAULT NULL,
                    finished_at TEXT DEFAULT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(job_id, position),
                    FOREIGN KEY(job_id) REFERENCES batch_jobs(job_id)
                );

                CREATE INDEX IF NOT EXISTS idx_batch_contacts_job_status
                    ON batch_contacts(job_id, status);
                CREATE INDEX IF NOT EXISTS idx_batch_contacts_session
                    ON batch_contacts(session_id);
                CREATE INDEX IF NOT EXISTS idx_batch_contacts_numbers
                    ON batch_contacts(customer_number, agent_id, status);
                """
            )

    def create_job(self, job_id: str, numbers: list[str], agents: list[str]) -> dict:
        now = datetime.now().isoformat()
        clean_numbers = [str(n).strip().lstrip("+") for n in numbers if str(n).strip()]
        clean_agents = [str(a).strip().lstrip("+") for a in agents if str(a).strip()]
        if not clean_numbers:
            return {"success": False, "error": "numbers list is required"}
        if not clean_agents:
            return {"success": False, "error": "at least one caller_id/agent is required"}

        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO batch_jobs(job_id, agent_ids, status, total, created_at, updated_at)
                VALUES (?, ?, 'running', ?, ?, ?)
                """,
                (job_id, json.dumps(clean_agents), len(clean_numbers), now, now),
            )
            conn.executemany(
                """
                INSERT INTO batch_contacts(job_id, position, customer_number, status, updated_at)
                VALUES (?, ?, ?, 'pending', ?)
                """,
                [(job_id, i, number, now) for i, number in enumerate(clean_numbers)],
            )

        self.kick(job_id)
        return {
            "success": True,
            "job_id": job_id,
            "queued": len(clean_numbers),
            "agents": clean_agents,
            "batch_size": len(clean_agents),
        }

    def status(self, job_id: str) -> dict:
        with self._connect() as conn:
            job = conn.execute("SELECT * FROM batch_jobs WHERE job_id=?", (job_id,)).fetchone()
            if not job:
                return {"success": False, "error": "job not found"}
            counts = conn.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM batch_contacts
                WHERE job_id=?
                GROUP BY status
                """,
                (job_id,),
            ).fetchall()
        return {
            "success": True,
            "job_id": job_id,
            "status": job["status"],
            "total": job["total"],
            "agents": json.loads(job["agent_ids"]),
            "counts": {row["status"]: row["count"] for row in counts},
        }

    def kick(self, job_id: str):
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self.advance(job_id), self._loop)
        else:
            threading.Thread(target=lambda: asyncio.run(self.advance(job_id)), daemon=True).start()

    async def advance(self, job_id: str):
        to_dial = []
        with self._lock, self._connect() as conn:
            job = conn.execute("SELECT * FROM batch_jobs WHERE job_id=?", (job_id,)).fetchone()
            if not job or job["status"] != "running":
                return

            active_count = conn.execute(
                """
                SELECT COUNT(*) FROM batch_contacts
                WHERE job_id=? AND status IN (?, ?)
                """,
                (job_id, *ACTIVE_CONTACT_STATUSES),
            ).fetchone()[0]
            if active_count:
                return

            pending = conn.execute(
                """
                SELECT * FROM batch_contacts
                WHERE job_id=? AND status='pending'
                ORDER BY position
                LIMIT ?
                """,
                (job_id, len(json.loads(job["agent_ids"]))),
            ).fetchall()
            if not pending:
                now = datetime.now().isoformat()
                conn.execute(
                    "UPDATE batch_jobs SET status='completed', updated_at=? WHERE job_id=?",
                    (now, job_id),
                )
                print(f"[Batch:{job_id}] completed all contacts")
                return

            agents = json.loads(job["agent_ids"])
            batch_no = (pending[0]["position"] // max(1, len(agents))) + 1
            now = datetime.now().isoformat()
            for row, agent in zip(pending, agents):
                conn.execute(
                    """
                    UPDATE batch_contacts
                    SET status='dialing', agent_id=?, batch_no=?, started_at=?, updated_at=?
                    WHERE id=? AND status='pending'
                    """,
                    (agent, batch_no, now, now, row["id"]),
                )
                to_dial.append((row["id"], row["customer_number"], agent))

        print(f"[Batch:{job_id}] launching batch with {len(to_dial)} call(s)")
        await asyncio.gather(*(self._dial_contact(job_id, contact_id, number, agent) for contact_id, number, agent in to_dial))
        self.kick(job_id)

    async def _dial_contact(self, job_id: str, contact_id: int, number: str, agent: str):
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(None, self._dialer, number, agent)
            payload = json.dumps(result)
            now = datetime.now().isoformat()
            if result.get("success"):
                call_sid = self._extract_call_sid(result)
                with self._lock, self._connect() as conn:
                    conn.execute(
                        """
                        UPDATE batch_contacts
                        SET call_sid=COALESCE(?, call_sid), result_json=?, updated_at=?
                        WHERE id=? AND status='dialing'
                        """,
                        (call_sid, payload, now, contact_id),
                    )
                print(f"[Batch:{job_id}] dialed {number} on agent {agent}")
            else:
                self._finish_contact(contact_id, "failed", payload)
        except Exception as e:
            self._finish_contact(contact_id, "failed", json.dumps({"error": str(e)}))

    def register_session(self, customer_number: str, agent_id: str, session_id: str, call_sid: str = ""):
        now = datetime.now().isoformat()
        customer_number = str(customer_number).strip().lstrip("+")
        agent_id = str(agent_id).strip().lstrip("+")
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM batch_contacts
                WHERE customer_number=? AND agent_id=? AND status='dialing'
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (customer_number, agent_id),
            ).fetchone()
            if not row:
                return
            conn.execute(
                """
                UPDATE batch_contacts
                SET status='active', session_id=?, call_sid=COALESCE(NULLIF(?, ''), call_sid), updated_at=?
                WHERE id=?
                """,
                (session_id, call_sid or "", now, row["id"]),
            )

    def on_call_completed(self, session_id: str, status: str, call_info: dict):
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id, job_id FROM batch_contacts WHERE session_id=? AND status IN (?, ?)",
                (session_id, *ACTIVE_CONTACT_STATUSES),
            ).fetchone()
        if not row:
            return
        self._finish_contact(row["id"], status, json.dumps(call_info or {}))
        self.kick(row["job_id"])

    def on_provider_status(self, data: dict):
        status = self._extract_status(data)
        call_sid = self._extract_first(data, ("call_id", "callSid", "call_sid", "sid", "uuid"))
        session_id = self._extract_first(data, ("session_id", "streamSid", "stream_sid"))
        if status not in FINAL_PROVIDER_STATUSES:
            return

        with self._lock, self._connect() as conn:
            row = None
            if session_id:
                row = conn.execute(
                    "SELECT id, job_id FROM batch_contacts WHERE session_id=? AND status IN (?, ?)",
                    (session_id, *ACTIVE_CONTACT_STATUSES),
                ).fetchone()
            if not row and call_sid:
                row = conn.execute(
                    "SELECT id, job_id FROM batch_contacts WHERE call_sid=? AND status IN (?, ?)",
                    (call_sid, *ACTIVE_CONTACT_STATUSES),
                ).fetchone()
            if not row:
                return

        self._finish_contact(row["id"], status, json.dumps(data))
        self.kick(row["job_id"])

    def _finish_contact(self, contact_id: int, provider_status: str, result_json: str):
        now = datetime.now().isoformat()
        final_status = "failed" if provider_status in FAILED_PROVIDER_STATUSES else "completed"
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE batch_contacts
                SET status=?, provider_status=?, result_json=COALESCE(?, result_json),
                    finished_at=COALESCE(finished_at, ?), updated_at=?
                WHERE id=? AND status IN (?, ?)
                """,
                (final_status, provider_status, result_json, now, now, contact_id, *ACTIVE_CONTACT_STATUSES),
            )

    def _extract_call_sid(self, result: dict) -> str:
        data = result.get("data") if isinstance(result, dict) else {}
        if isinstance(data, dict):
            return str(
                data.get("call_id")
                or data.get("callSid")
                or data.get("call_sid")
                or data.get("sid")
                or data.get("uuid")
                or ""
            )
        return ""

    def _extract_status(self, data: dict) -> str:
        value = self._extract_first(data, ("call_status", "status", "event", "callStatus"))
        return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")

    def _extract_first(self, data: dict, keys: tuple[str, ...]):
        if not isinstance(data, dict):
            return ""
        for key in keys:
            if data.get(key):
                return data.get(key)
        nested = data.get("data")
        if isinstance(nested, dict):
            for key in keys:
                if nested.get(key):
                    return nested.get(key)
        return ""
