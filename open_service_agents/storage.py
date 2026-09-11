"""SQLite durable jobs and commercial state; every row belongs to one local operator."""
import json
import sqlite3
import time
import uuid
from pathlib import Path
from contextlib import contextmanager


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "state.sqlite3"
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, brief TEXT NOT NULL,
                    provider TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0,
                    available REAL NOT NULL, lease_until REAL, lease_token TEXT, error TEXT, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS artifacts (
                    job_id TEXT NOT NULL, stage TEXT NOT NULL, content TEXT NOT NULL,
                    PRIMARY KEY(job_id, stage));
                CREATE TABLE IF NOT EXISTS products (
                    id TEXT PRIMARY KEY, job_id TEXT NOT NULL, amount INTEGER NOT NULL, currency TEXT NOT NULL,
                    partner_bps INTEGER NOT NULL, approved INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY, product_id TEXT NOT NULL, link_id TEXT UNIQUE, email TEXT NOT NULL,
                    amount INTEGER NOT NULL, currency TEXT NOT NULL, state TEXT NOT NULL, mode TEXT NOT NULL,
                    payment_id TEXT UNIQUE, url TEXT, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS ledger (
                    payment_id TEXT PRIMARY KEY, order_id TEXT NOT NULL, gross INTEGER NOT NULL,
                    partner_share INTEGER NOT NULL, currency TEXT NOT NULL, mode TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS suppressions (email TEXT PRIMARY KEY, reason TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS mail (
                    id TEXT PRIMARY KEY, recipient TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL,
                    state TEXT NOT NULL, evidence TEXT NOT NULL, due REAL NOT NULL, sent REAL, error TEXT);
                CREATE TABLE IF NOT EXISTS leads(id TEXT PRIMARY KEY,profile_url TEXT UNIQUE,content TEXT NOT NULL,updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS research(id TEXT PRIMARY KEY,content TEXT NOT NULL,created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS campaigns(id TEXT PRIMARY KEY,name TEXT NOT NULL,created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS campaign_mail(mail_id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL,variant TEXT NOT NULL,lead_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS mail_headers(mail_id TEXT PRIMARY KEY,message_id TEXT UNIQUE NOT NULL);
                CREATE TABLE IF NOT EXISTS replies(id TEXT PRIMARY KEY,mail_id TEXT NOT NULL,sender TEXT NOT NULL,subject TEXT NOT NULL,body TEXT NOT NULL,status TEXT NOT NULL,created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS imap_seen(account TEXT NOT NULL,validity TEXT NOT NULL,uid TEXT NOT NULL,PRIMARY KEY(account,validity,uid));
                CREATE TABLE IF NOT EXISTS imap_cursor(account TEXT PRIMARY KEY,validity TEXT NOT NULL,uid INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS storefronts(product_id TEXT PRIMARY KEY,content TEXT NOT NULL,published INTEGER NOT NULL,updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS visits(product_id TEXT NOT NULL,day TEXT NOT NULL,page TEXT NOT NULL,count INTEGER NOT NULL,PRIMARY KEY(product_id,day,page));
                CREATE TABLE IF NOT EXISTS checkout_requests(nonce TEXT PRIMARY KEY,product_id TEXT NOT NULL,email TEXT NOT NULL,order_id TEXT,state TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS advisor(id TEXT PRIMARY KEY,job_id TEXT NOT NULL,question TEXT NOT NULL,answer TEXT NOT NULL,created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS edits(id TEXT PRIMARY KEY,job_id TEXT NOT NULL,stage TEXT NOT NULL,previous TEXT NOT NULL,created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS transfers(id TEXT PRIMARY KEY,payment_id TEXT UNIQUE NOT NULL,account TEXT NOT NULL,amount INTEGER NOT NULL,currency TEXT NOT NULL,mode TEXT NOT NULL,state TEXT NOT NULL,provider_id TEXT,created REAL NOT NULL,error TEXT);
                CREATE INDEX IF NOT EXISTS idx_mail_state_due ON mail(state,due);
                CREATE INDEX IF NOT EXISTS idx_orders_product_state ON orders(product_id,state);
                CREATE INDEX IF NOT EXISTS idx_replies_mail_id ON replies(mail_id);
            ''')

    def edit_artifact(self, job_id, stage, content):
        from .models import artifact
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            job = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            old = db.execute('SELECT content FROM artifacts WHERE job_id=? AND stage=?', (job_id, stage)).fetchone()
            if not job or job['state'] != 'ready' or not old:
                raise ValueError('Only a completed draft stage can be edited.')
            if db.execute('SELECT 1 FROM products WHERE job_id=?', (job_id,)).fetchone():
                raise ValueError('An approved product is immutable. Create a revised product before editing.')
            clean = artifact(content, {s['id'] for s in json.loads(job['brief'])['sources']})
            clean['edited_by'] = 'operator'
            db.execute('INSERT INTO edits VALUES(?,?,?,?,?)', (uuid.uuid4().hex, job_id, stage, old['content'], time.time()))
            db.execute('UPDATE artifacts SET content=? WHERE job_id=? AND stage=?', (json.dumps(clean), job_id, stage))
        return clean

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def enqueue(self, brief, provider, request_key=None):
        job_id = uuid.uuid4().hex
        key = request_key or job_id
        serialized = json.dumps(brief, sort_keys=True)
        with self.connect() as db:
            existing = db.execute("SELECT * FROM jobs WHERE request_key=?", (key,)).fetchone()
            if existing:
                if existing["brief"] != serialized or existing["provider"] != provider:
                    raise ValueError("Idempotency key already belongs to a different request.")
                return existing["id"]
            db.execute("INSERT INTO jobs(id,request_key,brief,provider,available,created) VALUES(?,?,?,?,?,?)",
                       (job_id, key, serialized, provider, time.time(), time.time()))
        return job_id

    def claim(self):
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE jobs SET state='queued', lease_token=NULL WHERE state='running' AND lease_until<?", (now,))
            db.execute("UPDATE jobs SET state='failed',error='Retry budget exhausted' WHERE state='queued' AND attempts>=3")
            row = db.execute("SELECT * FROM jobs WHERE state='queued' AND available<=? AND attempts<3 ORDER BY created LIMIT 1", (now,)).fetchone()
            if not row:
                return None
            token = uuid.uuid4().hex
            db.execute("UPDATE jobs SET state='running', attempts=attempts+1,lease_until=?,lease_token=? WHERE id=?",
                       (now + 1800, token, row["id"]))
            return {**dict(row), "lease_token": token, "attempts": row["attempts"] + 1}

    def save_artifact(self, job, stage, content):
        with self.connect() as db:
            owned = db.execute("SELECT 1 FROM jobs WHERE id=? AND lease_token=? AND state='running'", (job["id"], job["lease_token"])).fetchone()
            if not owned:
                raise RuntimeError("Job lease lost.")
            db.execute("INSERT OR REPLACE INTO artifacts VALUES(?,?,?)", (job["id"], stage, json.dumps(content)))
            db.execute("UPDATE jobs SET lease_until=? WHERE id=?", (time.time() + 1800, job["id"]))

    def finish(self, job, error=None):
        with self.connect() as db:
            state = ("failed" if job["attempts"] >= 3 else "queued") if error else "ready"
            db.execute("UPDATE jobs SET state=?,error=?,available=?,lease_token=NULL WHERE id=? AND lease_token=?",
                       (state, error, time.time() + 30 * job["attempts"], job["id"], job["lease_token"]))

    def job(self, job_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise ValueError("Unknown job.")
            result = dict(row)
            result["brief"] = json.loads(result["brief"])
            result["artifacts"] = {r["stage"]: json.loads(r["content"]) for r in
                db.execute("SELECT stage,content FROM artifacts WHERE job_id=?", (job_id,))}
            return result

    def jobs(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT id,provider,state,attempts,error,created FROM jobs ORDER BY created DESC LIMIT 100")]

    def retry(self, job_id):
        """Explicit operator recovery after fixing inputs/configuration; retain checkpoints."""
        with self.connect() as db:
            changed = db.execute("UPDATE jobs SET state='queued',attempts=0,error=NULL,available=?,lease_until=NULL,lease_token=NULL WHERE id=? AND state='failed'",
                                 (time.time(), job_id)).rowcount
            if changed != 1:
                raise ValueError("Only a failed job can be explicitly retried.")
        return job_id
