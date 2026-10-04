"""Storage: TimescaleDB (Tiger Data) when DATABASE_URL is set, else local SQLite.

Timestamps are epoch seconds in the Python API. In Postgres they are TIMESTAMPTZ columns
on hypertables (checks, passive, doses); in SQLite they are REAL.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time

from . import config

log = logging.getLogger("taptrack.storage")

TABLES = {
    "doses": "id {pk}, ts {ts} NOT NULL, med TEXT, source TEXT",
    "checks": ("id {pk}, ts {ts} NOT NULL, patient_id TEXT, score REAL, level TEXT, minutes_since_dose REAL, "
               "source TEXT, complete INTEGER, tests {js}, metrics {js}, results {js}"),
    "passive": "id {pk}, ts {ts} NOT NULL, rms_mg REAL, dominant_hz REAL, minutes_since_dose REAL, source TEXT",
    "outbox": "id {pk}, ts {ts} NOT NULL, kind TEXT, status TEXT, payload {js}",
    "actions": "id {pk}, ts {ts} NOT NULL, kind TEXT, detail {js}",
    "settings": "key TEXT PRIMARY KEY, value {js}",
}
HYPERTABLES = ("doses", "checks", "passive")
JSON_COLS = {"tests", "metrics", "results", "payload", "detail", "value"}


class Storage:
    def __init__(self, url: str | None = None, sqlite_path=None):
        self.url = config.DATABASE_URL if url is None else url
        self.lock = threading.RLock()
        if self.url:
            import psycopg

            self.pg = True
            self.conn = psycopg.connect(self.url, autocommit=True)
            self.kind = "timescale"
        else:
            self.pg = False
            path = sqlite_path or config.SQLITE_PATH
            self.conn = sqlite3.connect(str(path), check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.kind = "sqlite"
        self._init()

    # ------------------------------------------------------------------ plumbing
    def _sql(self, q: str) -> str:
        if self.pg:
            q = q.replace("?", "%s").replace("TS_IN", "to_timestamp(%s)")
            return q.replace("TS(ts)", "extract(epoch from ts)")
        return q.replace("TS_IN", "?").replace("TS(ts)", "ts")

    def _exec(self, q: str, params=()):
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(self._sql(q), params)
            if not self.pg:
                self.conn.commit()
            return cur

    def _rows(self, q: str, params=()) -> list[dict]:
        with self.lock:
            cur = self._exec(q, params)
            cols = [d[0] for d in cur.description]
            out = []
            for r in cur.fetchall():
                d = dict(zip(cols, r))
                for k in JSON_COLS & d.keys():
                    if isinstance(d[k], str):
                        d[k] = json.loads(d[k])
                if "ts" in d and d["ts"] is not None:
                    d["ts"] = float(d["ts"])
                out.append(d)
            return out

    def _init(self):
        if self.pg:
            subs = {"pk": "BIGSERIAL", "ts": "TIMESTAMPTZ", "js": "JSONB"}
        else:
            subs = {"pk": "INTEGER PRIMARY KEY AUTOINCREMENT", "ts": "REAL", "js": "TEXT"}
        for name, cols in TABLES.items():
            spec = cols.format(**subs)
            if self.pg and name in HYPERTABLES:
                # hypertables need the time column in any unique index
                spec = spec.replace("id BIGSERIAL", "id BIGSERIAL") + ", PRIMARY KEY (id, ts)"
            self._exec(f"CREATE TABLE IF NOT EXISTS {name} ({spec})")
            if name != "settings":
                self._exec(f"CREATE INDEX IF NOT EXISTS {name}_ts ON {name} (ts)")
        if self.pg:
            try:
                self._exec("CREATE EXTENSION IF NOT EXISTS timescaledb")
                for t in HYPERTABLES:
                    self._exec("SELECT create_hypertable(?, 'ts', if_not_exists => TRUE, migrate_data => TRUE)", (t,))
            except Exception as ex:  # plain Postgres still works
                log.warning("TimescaleDB hypertables unavailable: %s", ex)

    def _js(self, v):
        return json.dumps(v, default=float) if v is not None else None

    # ------------------------------------------------------------------ doses
    def add_dose(self, ts: float | None = None, med: str = "levodopa", source: str = "button") -> float:
        ts = ts or time.time()
        self._exec("INSERT INTO doses (ts, med, source) VALUES (TS_IN, ?, ?)", (ts, med, source))
        return ts

    def doses(self, since: float = 0, until: float = 9e12) -> list[dict]:
        return self._rows("SELECT id, TS(ts) AS ts, med, source FROM doses WHERE ts >= TS_IN AND ts < TS_IN ORDER BY ts",
                          (since, until))

    def last_dose_before(self, ts: float) -> float | None:
        r = self._rows("SELECT TS(ts) AS ts FROM doses WHERE ts <= TS_IN ORDER BY ts DESC LIMIT 1", (ts,))
        return r[0]["ts"] if r else None

    def minutes_since_dose(self, ts: float) -> float | None:
        d = self.last_dose_before(ts)
        return round((ts - d) / 60.0, 1) if d is not None else None

    # ------------------------------------------------------------------ checks
    def add_check(self, ts: float, score, level, tests, metrics, results, source="device",
                  complete=True, minutes_since_dose=None, patient_id=None) -> dict:
        if minutes_since_dose is None:
            minutes_since_dose = self.minutes_since_dose(ts)
        row = dict(ts=ts, patient_id=patient_id or config.PATIENT_ID, score=score, level=level,
                   minutes_since_dose=minutes_since_dose, source=source, complete=int(bool(complete)),
                   tests=tests, metrics=metrics, results=results)
        js = "?::jsonb" if self.pg else "?"
        cur = self._exec(
            "INSERT INTO checks (ts, patient_id, score, level, minutes_since_dose, source, complete, tests, metrics, results) "
            f"VALUES (TS_IN, ?, ?, ?, ?, ?, ?, {js}, {js}, {js})" + (" RETURNING id" if self.pg else ""),
            (ts, row["patient_id"], score, level, minutes_since_dose, source, row["complete"],
             self._js(tests), self._js(metrics), self._js(results)))
        row["id"] = cur.fetchone()[0] if self.pg else cur.lastrowid
        return row

    def checks(self, since: float = 0, until: float = 9e12, source: str | None = None) -> list[dict]:
        q = ("SELECT id, TS(ts) AS ts, patient_id, score, level, minutes_since_dose, source, complete, tests, metrics "
             "FROM checks WHERE ts >= TS_IN AND ts < TS_IN")
        params = [since, until]
        if source:
            q += " AND source = ?"
            params.append(source)
        return self._rows(q + " ORDER BY ts", params)

    def latest_check(self) -> dict | None:
        r = self._rows("SELECT id, TS(ts) AS ts, score, level, minutes_since_dose, source, tests, metrics, results "
                       "FROM checks ORDER BY ts DESC LIMIT 1")
        return r[0] if r else None

    # ------------------------------------------------------------------ passive tremor
    def add_passive(self, ts, rms_mg, dominant_hz=None, source="device", minutes_since_dose=None):
        if minutes_since_dose is None:
            minutes_since_dose = self.minutes_since_dose(ts)
        self._exec("INSERT INTO passive (ts, rms_mg, dominant_hz, minutes_since_dose, source) VALUES (TS_IN, ?, ?, ?, ?)",
                   (ts, rms_mg, dominant_hz, minutes_since_dose, source))
        return {"ts": ts, "rms_mg": rms_mg, "dominant_hz": dominant_hz, "minutes_since_dose": minutes_since_dose}

    def passive(self, since: float = 0, until: float = 9e12) -> list[dict]:
        return self._rows("SELECT TS(ts) AS ts, rms_mg, dominant_hz, minutes_since_dose, source FROM passive "
                          "WHERE ts >= TS_IN AND ts < TS_IN ORDER BY ts", (since, until))

    # ------------------------------------------------------------------ outbox / actions / settings
    def add_outbox(self, kind: str, payload: dict, status: str = "queued"):
        js = "?::jsonb" if self.pg else "?"
        self._exec(f"INSERT INTO outbox (ts, kind, status, payload) VALUES (TS_IN, ?, ?, {js})",
                   (time.time(), kind, status, self._js(payload)))

    def outbox(self, limit: int = 50) -> list[dict]:
        return self._rows("SELECT id, TS(ts) AS ts, kind, status, payload FROM outbox ORDER BY ts DESC LIMIT ?", (limit,))

    def add_action(self, kind: str, detail: dict):
        js = "?::jsonb" if self.pg else "?"
        self._exec(f"INSERT INTO actions (ts, kind, detail) VALUES (TS_IN, ?, {js})", (time.time(), kind, self._js(detail)))

    def actions(self, limit: int = 50) -> list[dict]:
        return self._rows("SELECT id, TS(ts) AS ts, kind, detail FROM actions ORDER BY ts DESC LIMIT ?", (limit,))

    def get_setting(self, key: str, default=None):
        r = self._rows("SELECT value FROM settings WHERE key = ?", (key,))
        return r[0]["value"] if r else default

    def set_setting(self, key: str, value):
        js = "?::jsonb" if self.pg else "?"
        self._exec(f"DELETE FROM settings WHERE key = ?", (key,))
        self._exec(f"INSERT INTO settings (key, value) VALUES (?, {js})", (key, self._js(value)))

    def clear_source(self, source: str):
        for t in ("checks", "passive", "doses"):
            self._exec(f"DELETE FROM {t} WHERE source = ?", (source,))

    def count(self, table: str) -> int:
        return int(self._rows(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"])


_store: Storage | None = None


def get_store() -> Storage:
    """Process-wide store; falls back to SQLite if the Postgres URL is unreachable."""
    global _store
    if _store is None:
        try:
            _store = Storage()
        except Exception as ex:
            log.error("DATABASE_URL unusable (%s); falling back to SQLite", ex)
            _store = Storage(url="")
    return _store
