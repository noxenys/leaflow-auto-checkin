import os
import sys
import sqlite3
import threading
import time
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# Add parent directory to sys.path to import leaflow_checkin
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from leaflow_checkin import LeaflowAutoCheckin, MultiAccountManager

DB_PATH = os.getenv("DB_PATH", "./data/leaflow.db")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

# Scheduler configuration
# Default: 01:15 UTC (09:15 Beijing Time)
CRON_HOUR = int(os.getenv("CRON_HOUR", 1))
CRON_MINUTE = int(os.getenv("CRON_MINUTE", 15))

scheduler = BackgroundScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    print("Executing startup tasks...")
    print(f"DEBUG: Environment variables: PORT={os.getenv('PORT')}, GITHUB_ACTIONS={os.getenv('GITHUB_ACTIONS')}, RUNNING_IN_DOCKER={os.getenv('RUNNING_IN_DOCKER')}")
    _init_db()
    _sync_env_accounts()
    
    # Start scheduler
    if not scheduler.running:
        trigger = CronTrigger(hour=CRON_HOUR, minute=CRON_MINUTE, timezone='UTC')
        scheduler.add_job(_perform_checkin_task, trigger, id='daily_checkin', replace_existing=True)
        scheduler.start()
        print(f"Scheduler started: Running daily at {CRON_HOUR:02d}:{CRON_MINUTE:02d} UTC")
        
    yield
    # Shutdown logic
    print("Executing shutdown tasks...")
    if scheduler.running:
        scheduler.shutdown()

app = FastAPI(lifespan=lifespan)
_run_lock = threading.Lock()
_is_running = False


@app.middleware("http")
async def log_requests(request: Request, call_next):
    print(f"DEBUG: Received request: {request.method} {request.url}")
    try:
        response = await call_next(request)
        print(f"DEBUG: Request processed, status: {response.status_code}")
        return response
    except Exception as e:
        print(f"DEBUG: Request failed: {e}")
        raise


def _ensure_db_dir():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)


def _get_conn():
    # Set a timeout to wait for the lock to be released (default is 5.0 seconds)
    # Increased to 30 seconds to avoid "database is locked" errors under load
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    _ensure_db_dir()
    conn = _get_conn()
    try:
        # Enable Write-Ahead Logging (WAL) mode for better concurrency
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                password TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER,
                email TEXT NOT NULL,
                success INTEGER NOT NULL,
                result TEXT,
                balance TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


@app.get("/health")
def health_check():
    """Health check endpoint for monitoring tools"""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat(), "scheduler": scheduler.running}


def _require_auth(request: Request):
    if not ADMIN_TOKEN:
        return
    token = request.headers.get("x-admin-token") or request.query_params.get("token")
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _sync_env_accounts():
    """Sync accounts from environment variable to database"""
    env_accounts = os.getenv("LEAFLOW_ACCOUNTS", "")
    if not env_accounts:
        return

    conn = _get_conn()
    try:
        # Get existing emails to avoid duplicates
        existing_emails = set(
            row["email"] for row in conn.execute("SELECT email FROM accounts").fetchall()
        )
        
        pairs = [x.strip() for x in env_accounts.split(",") if x.strip()]
        new_count = 0
        for pair in pairs:
            if ":" not in pair:
                continue
            email, password = pair.split(":", 1)
            email = email.strip()
            password = password.strip()
            
            if email and password and email not in existing_emails:
                conn.execute(
                    "INSERT INTO accounts(email, password, created_at) VALUES (?, ?, ?)",
                    (email, password, datetime.utcnow().isoformat()),
                )
                existing_emails.add(email)
                new_count += 1
        
        if new_count > 0:
            conn.commit()
            print(f"Synced {new_count} accounts from environment variables.")
    except Exception as e:
        print(f"Error syncing env accounts: {e}")
    finally:
        conn.close()


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(
        """
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Leaflow Checkin Panel</title>
  <style>
    body { font-family: Arial, sans-serif; padding: 20px; background: #0f0f10; color: #eaeaea; }
    h1 { margin-bottom: 8px; }
    .card { background: #17181a; padding: 16px; border-radius: 8px; margin-bottom: 16px; }
    input, button { padding: 8px 10px; border-radius: 6px; border: 1px solid #333; background: #0f0f10; color: #eaeaea; }
    button { cursor: pointer; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 8px; border-bottom: 1px solid #2a2a2a; text-align: left; }
    .row { display: flex; gap: 8px; flex-wrap: wrap; }
    .muted { color: #9aa0a6; }
  </style>
</head>
<body>
  <h1>Leaflow Checkin Panel</h1>
  <p class="muted">Optional web UI for managing accounts and running check-ins.</p>

  <div class="card">
    <div class="row">
      <button onclick="runCheckin()">Run Checkin</button>
      <span id="status" class="muted"></span>
    </div>
  </div>

  <div class="card">
    <h3>Add Account</h3>
    <div class="row">
      <input id="email" placeholder="email"/>
      <input id="password" placeholder="password" type="password"/>
      <button onclick="addAccount()">Add</button>
    </div>
  </div>

  <div class="card">
    <h3>Accounts</h3>
    <table id="accounts"></table>
  </div>

  <div class="card">
    <h3>Recent Runs</h3>
    <table id="runs"></table>
  </div>

<script>
const tokenKey = "admin_token";
function getToken() { return localStorage.getItem(tokenKey) || ""; }
function withAuth(headers = {}) {
  const token = getToken();
  if (token) headers["x-admin-token"] = token;
  return headers;
}
async function fetchJSON(url, options={}) {
  options.headers = withAuth(options.headers || {});
  const res = await fetch(url, options);
  if (res.status === 401) {
    const t = prompt("Enter ADMIN_TOKEN");
    if (t !== null) { localStorage.setItem(tokenKey, t); location.reload(); }
    throw new Error("Unauthorized");
  }
  return res.json();
}
async function loadAccounts() {
  const data = await fetchJSON("/api/accounts");
  const table = document.getElementById("accounts");
  table.innerHTML = "<tr><th>ID</th><th>Email</th><th>Actions</th></tr>";
  data.items.forEach(a => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${a.id}</td><td>${a.email}</td><td><button onclick="delAccount(${a.id})">Delete</button></td>`;
    table.appendChild(tr);
  });
}
async function loadRuns() {
  const data = await fetchJSON("/api/runs");
  const table = document.getElementById("runs");
  table.innerHTML = "<tr><th>Time</th><th>Email</th><th>Success</th><th>Result</th><th>Balance</th></tr>";
  data.items.forEach(r => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${r.created_at}</td><td>${r.email}</td><td>${r.success ? "yes" : "no"}</td><td>${r.result || ""}</td><td>${r.balance || ""}</td>`;
    table.appendChild(tr);
  });
}
async function addAccount() {
  const email = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value.trim();
  if (!email || !password) return alert("Missing email/password");
  await fetchJSON("/api/accounts", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({email, password})});
  document.getElementById("email").value = "";
  document.getElementById("password").value = "";
  loadAccounts();
}
async function delAccount(id) {
  await fetchJSON(`/api/accounts/${id}`, { method: "DELETE" });
  loadAccounts();
}
async function runCheckin() {
  document.getElementById("status").textContent = "Running...";
  try {
    await fetchJSON("/api/run", { method: "POST" });
    await loadRuns();
  } finally {
    document.getElementById("status").textContent = "";
  }
}
loadAccounts();
loadRuns();
</script>
</body>
</html>
        """
    )


@app.get("/api/accounts")
def list_accounts(request: Request):
    _require_auth(request)
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT id, email, created_at FROM accounts ORDER BY id DESC").fetchall()
        return {"items": [dict(row) for row in rows]}
    finally:
        conn.close()


@app.post("/api/accounts")
def add_account(request: Request, payload: dict):
    _require_auth(request)
    email = (payload.get("email") or "").strip()
    password = (payload.get("password") or "").strip()
    if not email or not password:
        raise HTTPException(status_code=400, detail="email/password required")
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO accounts(email, password, created_at) VALUES (?, ?, ?)",
            (email, password, datetime.utcnow().isoformat()),
        )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.delete("/api/accounts/{account_id}")
def delete_account(request: Request, account_id: int):
    _require_auth(request)
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.get("/api/runs")
def list_runs(request: Request, limit: int = 50):
    _require_auth(request)
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT email, success, result, balance, created_at FROM runs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return {"items": [dict(row) for row in rows]}
    finally:
        conn.close()


def _perform_checkin_task():
    """Internal function to run the checkin logic"""
    global _is_running
    if not _run_lock.acquire(blocking=False):
        print("Checkin task already running, skipping...")
        return {"ok": False, "message": "already running"}
    
    _is_running = True
    print(f"Starting checkin task at {datetime.utcnow().isoformat()}")
    try:
        conn = _get_conn()
        accounts = conn.execute("SELECT id, email, password FROM accounts ORDER BY id ASC").fetchall()
        conn.close()
        
        if not accounts:
            print("No accounts found for checkin task")
            return {"ok": False, "message": "no accounts"}

        results = []
        for acc in accounts:
            email = acc["email"]
            password = acc["password"]
            print(f"Running checkin for {email}...")
            
            # Run checkin logic
            try:
                auto_checkin = LeaflowAutoCheckin(email, password)
                success, result, balance = auto_checkin.run()
            except Exception as e:
                print(f"Checkin failed for {email}: {e}")
                success = False
                result = f"Error: {str(e)}"
                balance = "N/A"

            results.append(
                {
                    "email": email,
                    "success": success,
                    "result": result,
                    "balance": balance,
                }
            )

            conn = _get_conn()
            try:
                conn.execute(
                    "INSERT INTO runs(account_id, email, success, result, balance, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        acc["id"],
                        email,
                        1 if success else 0,
                        str(result),
                        str(balance),
                        datetime.utcnow().isoformat(),
                    ),
                )
                conn.commit()
            except Exception as e:
                print(f"Failed to save run result for {email}: {e}")
            finally:
                conn.close()

        print(f"Checkin task completed. Results: {len(results)}")
        
        # Send Telegram notification
        try:
            print("Sending Telegram notification...")
            # Convert results to the format expected by MultiAccountManager
            # app.py results: [{"email":..., "success":..., "result":..., "balance":...}]
            # MultiAccountManager expects: [(email, success, result, balance)]
            notify_results = []
            for item in results:
                notify_results.append((item["email"], item["success"], item["result"], item["balance"]))
            
            manager = MultiAccountManager(auto_load=False)
            manager.send_notification(notify_results)
        except Exception as e:
            print(f"Failed to send notification: {e}")

        return {"ok": True, "items": results}
    except Exception as e:
        print(f"Checkin task failed with error: {e}")
        raise
    finally:
        _is_running = False
        _run_lock.release()


@app.post("/api/run")
def run_checkin(request: Request):
    _require_auth(request)
    # Check if lock is available without acquiring it, because _perform_checkin_task will acquire it
    if _is_running:
         raise HTTPException(status_code=409, detail="already running")
         
    return _perform_checkin_task()


@app.get("/api/status")
def status(request: Request):
    _require_auth(request)
    return {"running": _is_running}


if __name__ == "__main__":
    import uvicorn
    # Debug: print environment variables related to port
    print(f"DEBUG: Environment PORT variable is: {os.getenv('PORT')}")
    
    port = int(os.getenv("PORT", 8080))
    print(f"Starting Web UI on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)
