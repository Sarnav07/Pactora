import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .crypto import PrivateStoreCipher


class Store:
    def __init__(self, directory: Path, cipher: PrivateStoreCipher):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        self.path = directory / "commerce.db"
        self.cipher = cipher
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        os.chmod(self.path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            PRAGMA secure_delete=ON;
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, state TEXT NOT NULL, expires INTEGER NOT NULL,
                details TEXT NOT NULL, quote TEXT, quote_hash TEXT, device_key TEXT,
                reservation INTEGER NOT NULL DEFAULT 0, chat INTEGER NOT NULL DEFAULT 0,
                result TEXT, vault TEXT, created INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
            INSERT OR IGNORE INTO meta VALUES ('spent_cents', 0);
            INSERT OR IGNORE INTO meta VALUES ('paused', 0);
            CREATE TABLE IF NOT EXISTS decisions (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        """)

    def paused(self):
        with self.lock:
            return bool(self.db.execute("SELECT value FROM meta WHERE key='paused'").fetchone()[0])

    def set_paused(self, paused):
        with self.transaction() as db:
            db.execute("UPDATE meta SET value=? WHERE key='paused'", (int(paused),))

    def decision(self, reference, updates):
        """One encrypted record per request binding, including identical retries."""
        with self.transaction() as db:
            row = db.execute("SELECT payload FROM decisions WHERE id=?", (reference,)).fetchone()
            value = (
                self.cipher.decrypt(row[0], "decision:" + reference)
                if row
                else {
                    "id": reference,
                    "created_at": int(time.time()),
                }
            )
            # An identical retry must not replace a finished decision with 'pending'.
            if row and updates.get("state") == "pending":
                return
            value.update(updates)
            db.execute(
                "INSERT OR REPLACE INTO decisions VALUES (?,?)",
                (
                    reference,
                    self.cipher.encrypt(value, "decision:" + reference),
                ),
            )

    def decisions(self):
        with self.lock:
            values = [
                self.cipher.decrypt(r[1], "decision:" + r[0])
                for r in self.db.execute("SELECT id,payload FROM decisions")
            ]
        return sorted(values, key=lambda v: (v["created_at"], v["id"]), reverse=True)

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield self.db
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def get(self, job_id: str):
        with self.lock:
            return self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()

    def jobs(self):
        with self.lock:
            return self.db.execute("SELECT * FROM jobs ORDER BY created DESC").fetchall()

    def cleanup(self):
        """Logical expiry only; not a promise of SSD/back-up secure erasure."""
        with self.transaction() as db:
            empty = self.cipher.encrypt({}, "expired")
            db.execute(
                """UPDATE jobs SET state='expired', details=?, quote=NULL, quote_hash=NULL
                WHERE expires < ? AND state IN ('awaiting_selection','awaiting_approval')""",
                (empty, int(time.time())),
            )
            db.execute("DELETE FROM sessions WHERE expires < ?", (int(time.time()),))
