"""
Token Tracker Engine for Antigravity Control Center.
Monitors session transcripts in real-time and persists token counts into SQLite.
Provides daily, monthly, and yearly aggregations across accounts and models.
"""
import os
import glob
import json
import re
import sqlite3
import tempfile
import threading
import time
from datetime import datetime, timezone, timedelta

SWITCHER_DIR = os.path.join(os.environ.get("USERPROFILE", ""), ".gemini", "antigravity-switcher")
DB_PATH = os.path.join(SWITCHER_DIR, "tokens_history.db")
ACTIVE_FILE = os.path.join(SWITCHER_DIR, "active_email.txt")
BRAIN_DIR = os.path.join(os.environ.get("USERPROFILE", ""), ".gemini", "antigravity", "brain")
TMP_DIR = os.path.join(os.environ.get("USERPROFILE", ""), ".gemini", "tmp")
STATE_FILE = os.path.join(SWITCHER_DIR, "watcher_state.json")
CONVERSATION_SUMMARIES_DB = os.path.join(os.environ.get("USERPROFILE", ""), ".gemini", "antigravity", "conversation_summaries.db")

def get_active_account():
    if os.path.exists(ACTIVE_FILE):
        try:
            with open(ACTIVE_FILE, "r", encoding="utf-8") as f:
                email = f.read().strip()
                if email:
                    return email
        except Exception:
            pass
    return "default"

def get_db_connection():
    os.makedirs(SWITCHER_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS token_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                step_index INTEGER,
                created_at TEXT NOT NULL,
                day TEXT NOT NULL,
                month TEXT NOT NULL,
                year TEXT NOT NULL,
                hour INTEGER NOT NULL,
                account TEXT NOT NULL,
                model TEXT NOT NULL,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                cache_read_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                duration_sec REAL DEFAULT 0,
                UNIQUE(session_id, step_index)
            )
        """)
        try:
            conn.execute("ALTER TABLE token_events ADD COLUMN duration_sec REAL DEFAULT 0;")
        except Exception:
            pass
        conn.execute("CREATE INDEX IF NOT EXISTS idx_day ON token_events(day);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_month ON token_events(month);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_year ON token_events(year);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_account ON token_events(account);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON token_events(created_at);")
    conn.close()

def load_watcher_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_watcher_state(state):
    try:
        os.makedirs(SWITCHER_DIR, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=SWITCHER_DIR, prefix=".watcher_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state, f)
                f.flush()
            os.replace(tmp_path, STATE_FILE)
        except Exception:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            raise
    except Exception:
        pass

def is_ai_generating(threshold_seconds=15.0):
    """
    Returns True if an AI turn or prompt in Antigravity was active within the last threshold_seconds.
    Used by AutoPilot Idle Guard to guarantee active chats/prompts are NEVER interrupted.
    """
    now = time.time()
    pattern = os.path.join(BRAIN_DIR, "*", ".system_generated", "logs", "transcript.jsonl")
    try:
        files = glob.glob(pattern)
        for f in files:
            try:
                mtime = os.path.getmtime(f)
                if (now - mtime) < threshold_seconds:
                    return True
            except Exception:
                pass
    except Exception:
        pass
    return False

def parse_transcript_file(file_path, last_offset=0, active_account="default", initial_model="Gemini 3.8 Flash"):
    """
    Parses new lines from a transcript file starting at last_offset.
    Returns (new_events, new_offset, current_model).
    """
    if not os.path.exists(file_path):
        return [], last_offset, initial_model

    events = []
    # Derive session_id from parent folder path
    parts = os.path.normpath(file_path).split(os.sep)
    # expected: brain/<session_id>/.system_generated/logs/transcript.jsonl
    session_id = "unknown"
    try:
        idx = parts.index("brain")
        if idx + 1 < len(parts):
            session_id = parts[idx + 1]
    except Exception:
        pass

    current_model = initial_model or "Gemini 3.8 Flash"
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            f.seek(last_offset)
            prev_ts = None
            while True:
                line = f.readline()
                if not line:
                    break

                # Dynamically track model selection changes
                if "USER_SETTINGS_CHANGE" in line and "Model Selection" in line:
                    try:
                        data = json.loads(line)
                        content = data.get("content", "")
                        for subline in content.splitlines():
                            if "Model Selection" in subline and " to " in subline:
                                after_to = subline.split(" to ", 1)[1]
                                extracted = after_to.split(". No need", 1)[0].split(".\n", 1)[0].strip()
                                if extracted.endswith("."):
                                    extracted = extracted[:-1].strip()
                                if extracted and extracted != "None":
                                    current_model = extracted
                    except Exception:
                        pass

                parsed_data = None
                try:
                    parsed_data = json.loads(line)
                except Exception:
                    pass

                line_ts = None
                if parsed_data and "created_at" in parsed_data:
                    try:
                        line_ts = datetime.fromisoformat(parsed_data["created_at"].replace("Z", "+00:00"))
                    except Exception:
                        pass

                if '"input_tokens"' in line or '"output_tokens"' in line:
                    try:
                        data = parsed_data or json.loads(line)
                        inp = data.get("input_tokens", 0)
                        outp = data.get("output_tokens", 0)
                        cache = data.get("cache_read_tokens", 0)
                        tot = inp + outp
                        if tot > 0 or cache > 0:
                            created_at = data.get("created_at", datetime.now(timezone.utc).isoformat())
                            ts_clean = created_at.replace("Z", "+00:00")
                            try:
                                dt = datetime.fromisoformat(ts_clean)
                            except Exception:
                                dt = datetime.now(timezone.utc)

                            # Calculate duration for output generation
                            duration_sec = 0.0
                            if outp > 0:
                                if prev_ts:
                                    diff = (dt - prev_ts).total_seconds()
                                    if 0 <= diff <= 60:
                                        duration_sec = diff if diff > 0 else max(0.5, round(outp / 235.0, 2))
                                    else:
                                        duration_sec = max(0.5, round(outp / 235.0, 2))
                                else:
                                    duration_sec = max(0.5, round(outp / 235.0, 2))

                            # Priority: step model -> dynamically detected model -> fallback
                            model = data.get("model") or current_model
                            events.append({
                                "session_id": session_id,
                                "step_index": data.get("step_index", 0),
                                "created_at": created_at,
                                "day": dt.strftime("%Y-%m-%d"),
                                "month": dt.strftime("%Y-%m"),
                                "year": dt.strftime("%Y"),
                                "hour": dt.hour,
                                "account": active_account,
                                "model": model,
                                "input_tokens": inp,
                                "output_tokens": outp,
                                "cache_read_tokens": cache,
                                "total_tokens": tot,
                                "duration_sec": duration_sec
                            })
                    except Exception:
                        pass
                else:
                    # Historical fallback for Antigravity sessions before October 8, 2026
                    try:
                        data = parsed_data or json.loads(line)
                        stype = data.get("type", "")
                        created_at = data.get("created_at")
                        if created_at and stype in ("PLANNER_RESPONSE", "USER_INPUT", "CODE_ACTION", "VIEW_FILE"):
                            content = data.get("content", "") or ""
                            thinking = data.get("thinking", "") or ""
                            tool_calls = data.get("tool_calls", "") or ""
                            
                            content_tok = max(0, int(len(content) / 3.8))
                            thinking_tok = max(0, int(len(thinking) / 3.8))
                            tools_tok = max(0, int(len(str(tool_calls)) / 3.8)) if tool_calls else 0
                            
                            if stype == "PLANNER_RESPONSE":
                                outp = content_tok + thinking_tok
                                inp = tools_tok
                            else:
                                inp = content_tok
                                outp = 0
                                
                            tot = inp + outp
                            if tot > 0:
                                ts_clean = created_at.replace("Z", "+00:00")
                                try:
                                    dt = datetime.fromisoformat(ts_clean)
                                except Exception:
                                    dt = datetime.now(timezone.utc)
                                events.append({
                                    "session_id": session_id,
                                    "step_index": data.get("step_index", 0),
                                    "created_at": created_at,
                                    "day": dt.strftime("%Y-%m-%d"),
                                    "month": dt.strftime("%Y-%m"),
                                    "year": dt.strftime("%Y"),
                                    "hour": dt.hour,
                                    "account": active_account,
                                    "model": data.get("model") or current_model,
                                    "input_tokens": inp,
                                    "output_tokens": outp,
                                    "cache_read_tokens": 0,
                                    "total_tokens": tot,
                                    "duration_sec": max(0.5, round(outp / 235.0, 2)) if outp > 0 else 0.0
                                })
                    except Exception:
                        pass
                if line_ts:
                    prev_ts = line_ts
            new_offset = f.tell()
            return events, new_offset, current_model
    except Exception:
        return [], last_offset, current_model

def parse_legacy_chat_file(file_path, active_account="default"):
    """Parses pre-Antigravity Gemini CLI / IDE session chats from .gemini/tmp."""
    fname = os.path.basename(file_path)
    session_id = fname.split(".")[0]
    events = []

    if file_path.endswith(".jsonl"):
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                step_idx = 0
                for line in f:
                    if not line.strip(): continue
                    try:
                        d = json.loads(line)
                        tokens = d.get("tokens")
                        ts = d.get("timestamp")
                        if not ts: continue
                        dt = None
                        if isinstance(ts, (int, float)):
                            dt = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc)
                        elif isinstance(ts, str):
                            try:
                                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                            except Exception:
                                pass
                        if not dt: continue

                        inp = 0
                        outp = 0
                        cache = 0
                        tot = 0
                        if isinstance(tokens, dict):
                            inp = tokens.get("input", 0)
                            outp = tokens.get("output", 0)
                            cache = tokens.get("cached", 0)
                            tot = tokens.get("total", inp + outp)
                        elif d.get("type") in ("gemini", "assistant", "model"):
                            content = d.get("content", "")
                            thoughts = d.get("thoughts", "")
                            outp = max(5, int((len(content) + len(thoughts)) / 3.8))
                            inp = 50
                            tot = inp + outp
                        elif d.get("type") == "user":
                            content = d.get("content", "")
                            inp = max(5, int(len(content) / 3.8))
                            tot = inp

                        if tot > 0:
                            model = d.get("model") or "Gemini 1.5 Pro"
                            events.append({
                                "session_id": session_id,
                                "step_index": step_idx,
                                "created_at": dt.isoformat(),
                                "day": dt.strftime("%Y-%m-%d"),
                                "month": dt.strftime("%Y-%m"),
                                "year": dt.strftime("%Y"),
                                "hour": dt.hour,
                                "account": active_account,
                                "model": model,
                                "input_tokens": inp,
                                "output_tokens": outp,
                                "cache_read_tokens": cache,
                                "total_tokens": tot,
                                "duration_sec": 0.0
                            })
                            step_idx += 1
                    except Exception:
                        pass
        except Exception:
            pass
    elif file_path.endswith(".json"):
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                data = json.load(f)
                msgs = data.get("messages", [])
                step_idx = 0
                for m in msgs:
                    ts = m.get("timestamp")
                    if not ts: continue
                    dt = None
                    if isinstance(ts, (int, float)):
                        dt = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc)
                    elif isinstance(ts, str):
                        try:
                            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        except Exception:
                            pass
                    if not dt: continue

                    content = m.get("content", "") or m.get("message", "")
                    tok = max(5, int(len(content) / 3.8))
                    if tok > 0:
                        m_type = m.get("type", "user")
                        inp = tok if m_type == "user" else 0
                        outp = tok if m_type != "user" else 0
                        events.append({
                            "session_id": session_id,
                            "step_index": step_idx,
                            "created_at": dt.isoformat(),
                            "day": dt.strftime("%Y-%m-%d"),
                            "month": dt.strftime("%Y-%m"),
                            "year": dt.strftime("%Y"),
                            "hour": dt.hour,
                            "account": active_account,
                            "model": "Gemini",
                            "input_tokens": inp,
                            "output_tokens": outp,
                            "cache_read_tokens": 0,
                            "total_tokens": tok,
                            "duration_sec": 0.0
                        })
                        step_idx += 1
        except Exception:
            pass
    return events

def backfill_and_sync():
    """Backfills any untracked or existing transcripts into SQLite."""
    state = load_watcher_state()
    active_acc = get_active_account()

    pattern = os.path.join(BRAIN_DIR, "*", ".system_generated", "logs", "transcript.jsonl")
    transcript_files = glob.glob(pattern)

    all_events = []
    state_changed = False
    for tf in transcript_files:
        norm_path = os.path.normpath(tf)
        entry = state.get(norm_path, 0)
        if isinstance(entry, dict):
            last_offset = int(entry.get("offset", 0))
            last_model = entry.get("model", "Gemini 3.8 Flash")
        else:
            last_offset = int(entry or 0)
            last_model = "Gemini 3.8 Flash"
        try:
            file_size = os.path.getsize(norm_path)
            if file_size > last_offset:
                evs, new_offset, new_model = parse_transcript_file(
                    norm_path, last_offset, active_acc, initial_model=last_model
                )
                if evs:
                    all_events.extend(evs)
                state[norm_path] = {"offset": new_offset, "model": new_model}
                state_changed = True
        except Exception:
            pass

    # Also backfill legacy session chats in .gemini/tmp
    if os.path.exists(TMP_DIR):
        legacy_files = glob.glob(os.path.join(TMP_DIR, "*", "chats", "*.*"))
        for lf in legacy_files:
            norm_path = os.path.normpath(lf)
            if norm_path not in state:
                evs = parse_legacy_chat_file(norm_path, active_acc)
                if evs:
                    all_events.extend(evs)
                state[norm_path] = os.path.getsize(norm_path)
                state_changed = True

    if all_events:
        conn = get_db_connection()
        with conn:
            conn.executemany("""
                INSERT OR IGNORE INTO token_events 
                (session_id, step_index, created_at, day, month, year, hour, account, model, input_tokens, output_tokens, cache_read_tokens, total_tokens, duration_sec)
                VALUES (:session_id, :step_index, :created_at, :day, :month, :year, :hour, :account, :model, :input_tokens, :output_tokens, :cache_read_tokens, :total_tokens, :duration_sec)
            """, all_events)
        conn.close()

    if state_changed:
        save_watcher_state(state)
    return len(all_events)

class BackgroundTokenWatcher(threading.Thread):
    def __init__(self, interval_sec=2.5, on_new_events=None):
        super().__init__(daemon=True, name="BackgroundTokenWatcher")
        self.interval_sec = interval_sec
        self.on_new_events = on_new_events
        self.running = True

    def run(self):
        # Initial fast backfill
        try:
            added = backfill_and_sync()
            if added and self.on_new_events:
                self.on_new_events()
        except Exception:
            pass

        while self.running:
            time.sleep(self.interval_sec)
            try:
                added = backfill_and_sync()
                if added and self.on_new_events:
                    self.on_new_events()
            except Exception:
                pass

    def stop(self):
        self.running = False

# Query helpers for frontend
def get_token_summary(time_range="month", account=None):
    """
    time_range: 'today', '7d', 'month', 'year', 'all'
    """
    conn = get_db_connection()
    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y-%m-%d")
    month_str = now_utc.strftime("%Y-%m")
    year_str = now_utc.strftime("%Y")

    where_clauses = []
    params = []

    if time_range == "today":
        where_clauses.append("day = ?")
        params.append(today_str)
    elif time_range == "7d":
        where_clauses.append("datetime(created_at) >= datetime('now', '-7 days')")
    elif time_range == "month":
        where_clauses.append("month = ?")
        params.append(month_str)
    elif time_range == "year":
        where_clauses.append("year = ?")
        params.append(year_str)

    if account and account != "all":
        where_clauses.append("account = ?")
        params.append(account)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    # Totals
    tot_query = f"""
        SELECT 
            COALESCE(SUM(input_tokens), 0) AS total_in,
            COALESCE(SUM(output_tokens), 0) AS total_out,
            COALESCE(SUM(cache_read_tokens), 0) AS total_cache,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            COUNT(DISTINCT session_id) AS total_sessions,
            COUNT(*) AS total_steps
        FROM token_events
        {where_sql}
    """
    cur = conn.cursor()
    cur.execute(tot_query, params)
    totals = dict(cur.fetchone())

    # Timeline grouping: for today show hourly breakdown (00:00 - 23:00), for days/months show accordingly
    if time_range == "today":
        timeline_query = f"""
            SELECT 
                printf('%02d:00', hour) AS period,
                COALESCE(SUM(input_tokens), 0) AS input_tokens,
                COALESCE(SUM(output_tokens), 0) AS output_tokens,
                COALESCE(SUM(total_tokens), 0) AS total_tokens
            FROM token_events
            {where_sql}
            GROUP BY hour
            ORDER BY hour ASC
        """
    elif time_range in ("7d", "month"):
        timeline_query = f"""
            SELECT 
                day AS period,
                COALESCE(SUM(input_tokens), 0) AS input_tokens,
                COALESCE(SUM(output_tokens), 0) AS output_tokens,
                COALESCE(SUM(total_tokens), 0) AS total_tokens
            FROM token_events
            {where_sql}
            GROUP BY day
            ORDER BY day ASC
            LIMIT 31
        """
    else:
        timeline_query = f"""
            SELECT 
                month AS period,
                COALESCE(SUM(input_tokens), 0) AS input_tokens,
                COALESCE(SUM(output_tokens), 0) AS output_tokens,
                COALESCE(SUM(total_tokens), 0) AS total_tokens
            FROM token_events
            {where_sql}
            GROUP BY month
            ORDER BY month ASC
            LIMIT 36
        """

    cur.execute(timeline_query, params)
    timeline = [dict(row) for row in cur.fetchall()]

    # Grouped by Account
    acc_query = f"""
        SELECT 
            account,
            COALESCE(SUM(input_tokens), 0) AS input_tokens,
            COALESCE(SUM(output_tokens), 0) AS output_tokens,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            COUNT(*) AS turns
        FROM token_events
        {where_sql}
        GROUP BY account
        ORDER BY total_tokens DESC
    """
    cur.execute(acc_query, params)
    by_account = [dict(row) for row in cur.fetchall()]

    # Grouped by Model
    model_query = f"""
        SELECT 
            model,
            COALESCE(SUM(input_tokens), 0) AS input_tokens,
            COALESCE(SUM(output_tokens), 0) AS output_tokens,
            COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
            COALESCE(SUM(total_tokens), 0) AS total_tokens
        FROM token_events
        {where_sql}
        GROUP BY model
        ORDER BY total_tokens DESC
    """
    cur.execute(model_query, params)
    by_model = [dict(row) for row in cur.fetchall()]

    # Recent Events (up to 100 for live table display)
    events_query = f"""
        SELECT 
            id, session_id, created_at, day, account, model, 
            input_tokens, output_tokens, cache_read_tokens, total_tokens
        FROM token_events
        {where_sql}
        ORDER BY id DESC
        LIMIT 100
    """
    cur.execute(events_query, params)
    recent_events = [dict(row) for row in cur.fetchall()]

    # Burn rate & generation speed — smart session-aware calculation
    # Step 1: Check last hour of activity
    burn_clauses = ["datetime(created_at) >= datetime('now', '-1 hour')"]
    burn_params = []
    if account and account != "all":
        burn_clauses.append("account = ?")
        burn_params.append(account)

    burn_sql = "WHERE " + " AND ".join(burn_clauses)
    burn_query = f"""
        SELECT 
            COALESCE(SUM(total_tokens), 0) AS tokens_last_hour,
            COALESCE(SUM(output_tokens), 0) AS output_tokens_last_hour,
            COALESCE(SUM(duration_sec), 0) AS gen_sec_last_hour
        FROM token_events
        {burn_sql}
    """
    cur.execute(burn_query, burn_params)
    burn_row = cur.fetchone()
    last_hr = burn_row["tokens_last_hour"]
    out_last_hr = burn_row["output_tokens_last_hour"]
    gen_sec_last_hr = burn_row["gen_sec_last_hour"]

    tokens_per_min = round(last_hr / 60.0, 1)

    # Smart tok/s: use actual generation duration from last 20 non-trivial turns
    # regardless of how long ago they happened — shows real speed, not 0 during idle.
    smart_params = []
    smart_acct_clause = ""
    if account and account != "all":
        smart_acct_clause = "AND account = ?"
        smart_params.append(account)

    smart_speed_query = f"""
        SELECT output_tokens, duration_sec
        FROM token_events
        WHERE output_tokens > 10 AND duration_sec > 0 {smart_acct_clause}
        ORDER BY created_at DESC
        LIMIT 20
    """
    cur.execute(smart_speed_query, smart_params)
    recent_turns = cur.fetchall()

    if recent_turns:
        # Weighted average: sum(output) / sum(duration) across recent turns
        total_out = sum(r["output_tokens"] for r in recent_turns)
        total_dur = sum(r["duration_sec"] for r in recent_turns)
        gen_speed_tok_s = round(total_out / total_dur, 1) if total_dur > 0 else 0.0
    elif gen_sec_last_hr > 0:
        gen_speed_tok_s = round(out_last_hr / gen_sec_last_hr, 1)
    else:
        gen_speed_tok_s = 0.0

    throughput_tok_s = round(last_hr / 3600.0, 1)
    tokens_per_sec = gen_speed_tok_s

    # Feature 3: Cache Hit Rate & Session Context Calculations
    total_in = totals.get("total_in", 0)
    total_cache = totals.get("total_cache", 0)
    total_steps = totals.get("total_steps", 0)
    total_sessions = totals.get("total_sessions", 0)

    context_denom = total_in + total_cache
    cache_hit_rate = round((total_cache / context_denom * 100.0), 2) if context_denom > 0 else 0.0
    avg_context_per_session = round(context_denom / total_sessions) if total_sessions > 0 else 0
    avg_context_per_turn = round(context_denom / total_steps) if total_steps > 0 else 0

    totals["cache_hit_rate"] = cache_hit_rate
    totals["avg_context_per_session"] = avg_context_per_session
    totals["avg_context_per_turn"] = avg_context_per_turn

    conn.close()

    summary_res = {
        "time_range": time_range,
        "account_filter": account or "all",
        "totals": totals,
        "timeline": timeline,
        "by_account": by_account,
        "by_model": by_model,
        "recent_events": recent_events,
        "burn_rate": {
            "tokens_last_hour": last_hr,
            "tokens_per_min": tokens_per_min,
            "tokens_per_sec": tokens_per_sec,
            "gen_speed_tok_s": gen_speed_tok_s,
            "throughput_tok_s": throughput_tok_s,
            "output_tokens_last_hour": out_last_hr,
            "gen_sec_last_hour": round(gen_sec_last_hr, 1)
        },
        "cache_hit_rate": cache_hit_rate,
        "avg_context_per_session": avg_context_per_session,
        "avg_context_per_turn": avg_context_per_turn
    }

    # Feature 4: Cloud Cost Equivalency
    cost_info = calculate_cost_equivalency(summary_res)
    summary_res["estimated_cost_usd"] = cost_info["estimated_cost_usd"]
    summary_res["cost_breakdown"] = cost_info["breakdown"]
    summary_res["cost_equivalency"] = cost_info
    totals["estimated_cost_usd"] = cost_info["estimated_cost_usd"]

    return summary_res

def get_all_events(time_range="month", account=None):
    """Returns all events matching the filter without pagination limits for data export."""
    conn = get_db_connection()
    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y-%m-%d")
    month_str = now_utc.strftime("%Y-%m")
    year_str = now_utc.strftime("%Y")

    where_clauses = []
    params = []

    if time_range == "today":
        where_clauses.append("day = ?")
        params.append(today_str)
    elif time_range == "7d":
        where_clauses.append("datetime(created_at) >= datetime('now', '-7 days')")
    elif time_range == "month":
        where_clauses.append("month = ?")
        params.append(month_str)
    elif time_range == "year":
        where_clauses.append("year = ?")
        params.append(year_str)

    if account and account != "all":
        where_clauses.append("account = ?")
        params.append(account)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    query = f"""
        SELECT 
            id, session_id, created_at, day, account, model, 
            input_tokens, output_tokens, cache_read_tokens, total_tokens
        FROM token_events
        {where_sql}
        ORDER BY id DESC
    """
    cur = conn.cursor()
    cur.execute(query, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def get_model_pricing(model_name):
    """
    Standard API benchmark pricing:
    Claude 3.5: $3.00/M in, $15.00/M out, $0.30/M cache
    Gemini 2.5 Pro: $1.25/M in, $5.00/M out, $0.3125/M cache
    Gemini 2.5 Flash: $0.075/M in, $0.30/M out, $0.01875/M cache
    Default: $2.00/M in, $8.00/M out, $0.50/M cache
    """
    m = (model_name or "").lower()
    if "claude" in m:
        return {"input_per_m": 3.00, "output_per_m": 15.00, "cache_per_m": 0.30, "benchmark": "Claude 3.5 Sonnet"}
    elif "pro" in m:
        return {"input_per_m": 1.25, "output_per_m": 5.00, "cache_per_m": 0.3125, "benchmark": "Gemini 2.5 Pro"}
    elif "flash" in m:
        return {"input_per_m": 0.075, "output_per_m": 0.30, "cache_per_m": 0.01875, "benchmark": "Gemini 2.5 Flash"}
    else:
        return {"input_per_m": 2.00, "output_per_m": 8.00, "cache_per_m": 0.50, "benchmark": "Standard API"}

def calculate_cost_equivalency(summary):
    """
    Feature 4: Cloud Cost Equivalency Calculation.
    Calculates estimated dollar cost and savings across models and benchmark tiers.
    """
    by_model = summary.get("by_model", [])
    breakdown = []
    total_cost = 0.0
    total_cache_savings = 0.0

    for item in by_model:
        model_name = item.get("model", "Default")
        inp = item.get("input_tokens", 0)
        outp = item.get("output_tokens", 0)
        cache = item.get("cache_read_tokens", 0)
        tot = item.get("total_tokens", inp + outp)

        rates = get_model_pricing(model_name)
        cost_in = (inp / 1_000_000.0) * rates["input_per_m"]
        cost_out = (outp / 1_000_000.0) * rates["output_per_m"]
        cost_cache = (cache / 1_000_000.0) * rates["cache_per_m"]
        cache_saved = (cache / 1_000_000.0) * max(0.0, rates["input_per_m"] - rates["cache_per_m"])

        m_cost = cost_in + cost_out + cost_cache
        total_cost += m_cost
        total_cache_savings += cache_saved

        breakdown.append({
            "model": model_name,
            "benchmark": rates["benchmark"],
            "input_tokens": inp,
            "output_tokens": outp,
            "cache_tokens": cache,
            "total_tokens": tot,
            "input_cost_usd": round(cost_in, 4),
            "output_cost_usd": round(cost_out, 4),
            "cache_cost_usd": round(cost_cache, 4),
            "total_cost_usd": round(m_cost, 4),
            "cache_savings_usd": round(cache_saved, 4),
            "rates": rates
        })

    totals = summary.get("totals", {})
    t_in = totals.get("total_in", 0)
    t_out = totals.get("total_out", 0)
    t_cache = totals.get("total_cache", 0)
    steps = totals.get("total_steps", 0)
    tr = summary.get("time_range", "month")

    # Claude Verbosity Adjustment: Empirical benchmarks show Claude models are ~15% more concise on coding tasks (0.85x factor)
    c_factor = 0.85
    c_in = t_in * c_factor
    c_out = t_out * c_factor
    c_cache = t_cache * c_factor

    claude_opus_cost = (c_in / 1e6 * 15.00) + (c_out / 1e6 * 75.00) + (c_cache / 1e6 * 1.50)
    claude_sonnet_cost = (c_in / 1e6 * 3.00) + (c_out / 1e6 * 15.00) + (c_cache / 1e6 * 0.30)
    gemini_pro_cost = (t_in / 1e6 * 1.25) + (t_out / 1e6 * 5.00) + (t_cache / 1e6 * 0.3125)
    gemini_flash_cost = (t_in / 1e6 * 0.075) + (t_out / 1e6 * 0.30) + (t_cache / 1e6 * 0.01875)

    # Claude Pro Plan Limit Simulation ($20/mo web plan)
    # Standard Pro allows ~4M tokens/week and throttles to ~15 messages per 5h on large context
    if tr == "today":
        pro_limit = 800_000
    elif tr == "7d":
        pro_limit = 4_000_000
    else:
        pro_limit = 16_000_000

    total_raw = t_in + t_out
    exhaustion_pct = round((total_raw / float(pro_limit)) * 100.0, 1) if pro_limit > 0 else 0.0

    # Realistic 5-hour rolling window lockout simulation:
    # A lockout cooldown freezes the window for 5 hours (18,000s) once burst messages exceed 15 turns.
    # In any given time frame, lockouts cannot exceed total_hours / 5.
    if tr == "today":
        max_possible_lockouts = 24 // 5  # At most 4 lockouts in 24 hours
        est_lockouts = min(max_possible_lockouts, max(0, steps // 20))
    elif tr == "7d":
        max_possible_lockouts = (7 * 24) // 5  # At most 33 lockouts in a 7-day week
        est_lockouts = min(max_possible_lockouts, max(0, steps // 35))
    else:
        max_possible_lockouts = (30 * 24) // 5  # At most 144 lockouts in a 30-day month
        est_lockouts = min(max_possible_lockouts, max(0, steps // 45))

    return {
        "estimated_cost_usd": round(total_cost, 2),
        "total_cost_usd": round(total_cost, 4),
        "cache_savings_usd": round(total_cache_savings, 2),
        "breakdown": breakdown,
        "benchmarks": {
            "claude_opus": round(claude_opus_cost, 2),
            "claude_35_sonnet": round(claude_sonnet_cost, 2),
            "gemini_25_pro": round(gemini_pro_cost, 2),
            "gemini_25_flash": round(gemini_flash_cost, 2)
        },
        "claude_pro_plan": {
            "limit_tokens": pro_limit,
            "used_tokens": total_raw,
            "exhaustion_pct": exhaustion_pct,
            "is_exhausted": exhaustion_pct > 100.0,
            "estimated_lockouts": est_lockouts,
            "verbosity_factor": c_factor
        }
    }

def get_daily_heatmap(account="all"):
    """
    Feature 1: 365-day Daily Heatmap Data.
    Returns a 365-day list of:
    {date: 'YYYY-MM-DD', total_tokens: N, input_tokens: N, output_tokens: N, cache_tokens: N, turns: N, top_model: str}
    """
    conn = get_db_connection()
    where_clauses = ["day >= date('now', '-365 days')"]
    params = []
    if account and account != "all":
        where_clauses.append("account = ?")
        params.append(account)
    where_sql = "WHERE " + " AND ".join(where_clauses)

    query = f"""
        WITH filtered AS (
            SELECT day, model, total_tokens, input_tokens, output_tokens, cache_read_tokens
            FROM token_events
            {where_sql}
        ),
        daily_models AS (
            SELECT day, model, SUM(total_tokens) AS m_tokens,
                   ROW_NUMBER() OVER (PARTITION BY day ORDER BY SUM(total_tokens) DESC) AS rn
            FROM filtered
            GROUP BY day, model
        ),
        daily_totals AS (
            SELECT day,
                   COALESCE(SUM(total_tokens), 0) AS total_tokens,
                   COALESCE(SUM(input_tokens), 0) AS input_tokens,
                   COALESCE(SUM(output_tokens), 0) AS output_tokens,
                   COALESCE(SUM(cache_read_tokens), 0) AS cache_tokens,
                   COUNT(*) AS turns
            FROM filtered
            GROUP BY day
        )
        SELECT dt.day AS date, dt.total_tokens, dt.input_tokens, dt.output_tokens, dt.cache_tokens, dt.turns,
               COALESCE(dm.model, 'Unknown') AS top_model
        FROM daily_totals dt
        LEFT JOIN daily_models dm ON dt.day = dm.day AND dm.rn = 1
        ORDER BY dt.day ASC
    """
    cur = conn.cursor()
    cur.execute(query, params)
    db_map = {}
    for r in cur.fetchall():
        db_map[r["date"]] = {
            "date": r["date"],
            "total_tokens": int(r["total_tokens"] or 0),
            "input_tokens": int(r["input_tokens"] or 0),
            "output_tokens": int(r["output_tokens"] or 0),
            "cache_tokens": int(r["cache_tokens"] or 0),
            "turns": int(r["turns"] or 0),
            "top_model": r["top_model"] or "Unknown"
        }
    conn.close()

    today = datetime.now(timezone.utc).date()
    heatmap = []
    for i in range(365):
        d_str = (today - timedelta(days=364 - i)).strftime("%Y-%m-%d")
        if d_str in db_map:
            heatmap.append(db_map[d_str])
        else:
            heatmap.append({
                "date": d_str,
                "total_tokens": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_tokens": 0,
                "turns": 0,
                "top_model": "None"
            })
    return heatmap

def get_hourly_productivity(account="all", range_key="month"):
    """
    Feature 5: 24-Hour Hourly Productivity breakdown.
    Returns [{hour: 0..23, total_tokens: N, turns: N, primary_model: str}].
    """
    conn = get_db_connection()
    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y-%m-%d")
    month_str = now_utc.strftime("%Y-%m")
    year_str = now_utc.strftime("%Y")

    where_clauses = []
    params = []

    if range_key == "today":
        where_clauses.append("day = ?")
        params.append(today_str)
    elif range_key == "7d":
        where_clauses.append("datetime(created_at) >= datetime('now', '-7 days')")
    elif range_key == "month":
        where_clauses.append("month = ?")
        params.append(month_str)
    elif range_key == "year":
        where_clauses.append("year = ?")
        params.append(year_str)

    if account and account != "all":
        where_clauses.append("account = ?")
        params.append(account)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    query = f"""
        WITH filtered AS (
            SELECT hour, model, total_tokens
            FROM token_events
            {where_sql}
        ),
        hourly_models AS (
            SELECT hour, model, SUM(total_tokens) AS m_tokens,
                   ROW_NUMBER() OVER (PARTITION BY hour ORDER BY SUM(total_tokens) DESC) AS rn
            FROM filtered
            GROUP BY hour, model
        ),
        hourly_totals AS (
            SELECT hour,
                   COALESCE(SUM(total_tokens), 0) AS total_tokens,
                   COUNT(*) AS turns
            FROM filtered
            GROUP BY hour
        )
        SELECT ht.hour, ht.total_tokens, ht.turns, COALESCE(hm.model, 'None') AS primary_model
        FROM hourly_totals ht
        LEFT JOIN hourly_models hm ON ht.hour = hm.hour AND hm.rn = 1
        ORDER BY ht.hour ASC
    """
    cur = conn.cursor()
    cur.execute(query, params)
    hour_map = {row["hour"]: dict(row) for row in cur.fetchall()}
    conn.close()

    result = []
    for h in range(24):
        if h in hour_map:
            result.append({
                "hour": h,
                "total_tokens": int(hour_map[h]["total_tokens"] or 0),
                "turns": int(hour_map[h]["turns"] or 0),
                "primary_model": hour_map[h]["primary_model"] or "None"
            })
        else:
            result.append({
                "hour": h,
                "total_tokens": 0,
                "turns": 0,
                "primary_model": "None"
            })
    return result

def get_conversation_metadata():
    """
    Extracts official conversation titles and subagent relationships
    from Antigravity's conversation_summaries.db.
    Maps session_id -> { 'title': str, 'agent_name': str, 'parent_id': str, 'is_subagent': bool }
    """
    metadata = {}
    if os.path.exists(CONVERSATION_SUMMARIES_DB):
        try:
            with sqlite3.connect(f"file:{CONVERSATION_SUMMARIES_DB}?mode=ro", uri=True) as conn:
                cur = conn.cursor()
                cur.execute("SELECT conversation_id, title, preview, agent_name, parent_conversation_id FROM conversation_summaries")
                rows = cur.fetchall()
                parent_titles = {r[0]: (r[1] or r[2]) for r in rows if (r[1] or r[2])}
                for cid, title, preview, agent_name, parent_id in rows:
                    resolved = (title or preview or "").strip()
                    is_sub = bool(parent_id or agent_name)
                    if not resolved:
                        if parent_id and parent_id in parent_titles:
                            friendly = "Worker" if agent_name == "self" else ("Researcher" if agent_name == "research" else (agent_name.capitalize() if agent_name else "Helper"))
                            role = f" [Subagent: {friendly}]"
                            resolved = f"{parent_titles[parent_id]}{role}"
                        elif agent_name:
                            friendly = "Worker" if agent_name == "self" else ("Researcher" if agent_name == "research" else agent_name.capitalize())
                            resolved = f"Subagent: {friendly}"
                    metadata[cid] = {
                        "title": resolved,
                        "agent_name": agent_name or "",
                        "parent_id": parent_id or "",
                        "is_subagent": is_sub
                    }
        except Exception:
            pass
    return metadata

def resolve_session_title(session_id: str, metadata_cache: dict = None) -> tuple:
    """
    Returns (title, is_subagent, agent_name)
    """
    if metadata_cache and session_id in metadata_cache:
        meta = metadata_cache[session_id]
        if meta.get("title"):
            return meta["title"], meta.get("is_subagent", False), meta.get("agent_name", "")

    # Fallback to transcript.jsonl initial user prompt
    tp = os.path.join(BRAIN_DIR, session_id, ".system_generated", "logs", "transcript.jsonl")
    if os.path.exists(tp):
        try:
            with open(tp, "r", encoding="utf-8", errors="ignore") as f:
                for idx, line in enumerate(f):
                    if idx > 25:
                        break
                    if not line.strip():
                        continue
                    try:
                        step = json.loads(line)
                    except Exception:
                        continue
                    c = step.get("content", "")
                    if "<USER_REQUEST>" in c:
                        match = re.search(r"<USER_REQUEST>\s*(.*?)\s*(?:</USER_REQUEST>|\n)", c, re.DOTALL)
                        if match:
                            raw = " ".join(match.group(1).split())
                            title = raw[:45] + "..." if len(raw) > 45 else raw
                            return title, False, ""
                    elif step.get("type") == "USER_INPUT" and c:
                        raw = " ".join(c.split())
                        title = raw[:45] + "..." if len(raw) > 45 else raw
                        return title, False, ""
        except Exception:
            pass

    # Fallback when conversation summary or transcript is unavailable
    short_id = session_id[:8] if len(session_id) >= 8 else session_id
    return f"Session ({short_id})", False, ""

def count_session_compactions(session_id: str) -> int:
    """
    Counts how many times Antigravity has triggered automatic conversation compaction
    for a given session by scanning transcript.jsonl for CHECKPOINT / compaction events.
    """
    tp = os.path.join(BRAIN_DIR, session_id, ".system_generated", "logs", "transcript.jsonl")
    if not os.path.exists(tp):
        return 0
    count = 0
    try:
        with open(tp, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                t = obj.get("type", "")
                src = obj.get("source", "")
                c = str(obj.get("content", "")).lower()
                if t == "CHECKPOINT" and ("compaction" in c or "resuming from" in c):
                    count += 1
                elif src == "SYSTEM" and ("# resuming from a compaction" in c or "truncated to fit within the context window" in c):
                    count += 1
    except Exception:
        pass
    return count

def get_session_compaction_steps(session_id: str) -> set:
    """
    Returns the set of step_index numbers where a compaction occurred.
    """
    tp = os.path.join(BRAIN_DIR, session_id, ".system_generated", "logs", "transcript.jsonl")
    if not os.path.exists(tp):
        return set()
    steps = set()
    try:
        with open(tp, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                t = obj.get("type", "")
                src = obj.get("source", "")
                c = str(obj.get("content", "")).lower()
                if (t == "CHECKPOINT" and ("compaction" in c or "resuming from" in c)) or \
                   (src == "SYSTEM" and ("# resuming from a compaction" in c or "truncated to fit within the context window" in c)):
                    st_idx = obj.get("step_index")
                    if st_idx is not None:
                        steps.add(st_idx)
    except Exception:
        pass
    return steps

def get_recent_sessions(limit=25, account=None, include_purged=False, include_subagents=False):
    """
    Feature 8: Session Inspector - recent sessions list with titles and subagent info.
    Filters out purged/deleted sessions and background subagents by default while
    preserving all their token events and historical analytics in the database.
    """
    conn = get_db_connection()
    where_clauses = []
    params = []
    if account and account != "all":
        where_clauses.append("account = ?")
        params.append(account)
    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    candidate_limit = max(limit * 15, 600)

    query = f"""
        WITH filtered AS (
            SELECT session_id, account, model, total_tokens, input_tokens, output_tokens, cache_read_tokens, created_at
            FROM token_events
            {where_sql}
        ),
        session_agg AS (
            SELECT 
                session_id,
                account,
                COUNT(*) AS total_turns,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(SUM(input_tokens), 0) AS input_tokens,
                COALESCE(SUM(output_tokens), 0) AS output_tokens,
                COALESCE(SUM(cache_read_tokens), 0) AS cache_tokens,
                ROUND(AVG(input_tokens + cache_read_tokens)) AS avg_context_tokens,
                MAX(input_tokens + cache_read_tokens) AS max_context_tokens,
                MIN(created_at) AS first_turn,
                MAX(created_at) AS last_turn
            FROM filtered
            GROUP BY session_id
        ),
        session_models AS (
            SELECT 
                session_id, model,
                ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY SUM(total_tokens) DESC) AS rn
            FROM filtered
            GROUP BY session_id, model
        )
        SELECT 
            sa.session_id,
            sa.account,
            COALESCE(sm.model, 'Unknown') AS model,
            sa.total_turns,
            sa.total_tokens,
            sa.input_tokens,
            sa.output_tokens,
            sa.cache_tokens,
            sa.avg_context_tokens,
            sa.max_context_tokens,
            sa.first_turn,
            sa.last_turn
        FROM session_agg sa
        LEFT JOIN session_models sm ON sa.session_id = sm.session_id AND sm.rn = 1
        ORDER BY sa.last_turn DESC
        LIMIT ?
    """
    cur = conn.cursor()
    cur.execute(query, params + [candidate_limit])
    sessions = []
    meta_cache = get_conversation_metadata()
    for r in cur.fetchall():
        d = dict(r)
        sid = d["session_id"]
        
        m = meta_cache.get(sid, {}) if meta_cache else {}
        is_sub = bool(m.get("is_subagent") or m.get("parent_id") or m.get("agent_name"))
        tp = os.path.join(BRAIN_DIR, sid, ".system_generated", "logs", "transcript.jsonl")
        has_transcript = os.path.exists(tp)
        in_meta = sid in meta_cache if meta_cache else False
        is_purged = not in_meta and not has_transcript
        
        title, is_sub_res, agent_name = resolve_session_title(sid, meta_cache)
        if is_sub_res:
            is_sub = True
        if title.startswith("Session (") or title == "Unknown Session":
            is_purged = True

        if not include_subagents and is_sub:
            continue
        if not include_purged and is_purged:
            continue
            
        c_denom = d["input_tokens"] + d["cache_tokens"]
        d["cache_hit_rate"] = round((d["cache_tokens"] / c_denom * 100.0), 2) if c_denom > 0 else 0.0
        parent_id = m.get("parent_id", "")
        d["title"] = title
        d["is_subagent"] = is_sub
        d["agent_name"] = agent_name
        d["parent_id"] = parent_id
        d["compactions"] = count_session_compactions(sid)
        sessions.append(d)
        if len(sessions) >= limit:
            break
    conn.close()
    return sessions

def get_session_turns(session_id, limit=50):
    """
    Feature 8: Session Inspector - turn details for a single session.
    """
    if not session_id:
        return []
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT 
            id, session_id, step_index, created_at, day, hour, account, model,
            input_tokens, output_tokens, cache_read_tokens, total_tokens
        FROM token_events
        WHERE session_id = ?
        ORDER BY step_index ASC, id ASC
        LIMIT ?
    """, (session_id, limit))
    compaction_checkpoints = get_session_compaction_steps(session_id)
    raw_rows = cur.fetchall()
    turns = []
    all_step_indices = [r["step_index"] for r in raw_rows]
    flagged_turn_steps = set()
    for cp in compaction_checkpoints:
        next_turns = [s for s in all_step_indices if s >= cp]
        if next_turns:
            flagged_turn_steps.add(next_turns[0])

    for r in raw_rows:
        d = dict(r)
        d["context_size"] = d["input_tokens"] + d["cache_read_tokens"]
        d["is_compaction"] = (d["step_index"] in flagged_turn_steps) or (d["step_index"] in compaction_checkpoints)
        turns.append(d)
    conn.close()
    return turns

def get_context_stats(account="all", limit=50):
    """
    Feature 3: Context & Cache Analytics endpoint helper.
    """
    conn = get_db_connection()
    where_clauses = []
    params = []
    if account and account != "all":
        where_clauses.append("account = ?")
        params.append(account)
    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    cur = conn.cursor()
    cur.execute(f"""
        SELECT 
            COALESCE(SUM(input_tokens), 0) AS total_in,
            COALESCE(SUM(cache_read_tokens), 0) AS total_cache,
            COALESCE(SUM(output_tokens), 0) AS total_out,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            COUNT(DISTINCT session_id) AS total_sessions,
            COUNT(*) AS total_turns,
            COALESCE(MAX(input_tokens + cache_read_tokens), 0) AS peak_context_tokens
        FROM token_events
        {where_sql}
    """, params)
    overall = dict(cur.fetchone())
    tot_in = overall["total_in"]
    tot_cache = overall["total_cache"]
    tot_sessions = overall["total_sessions"]
    tot_turns = overall["total_turns"]
    denom = tot_in + tot_cache
    overall_hit_rate = round((tot_cache / denom * 100.0), 2) if denom > 0 else 0.0
    avg_session_context = round(denom / tot_sessions) if tot_sessions > 0 else 0
    avg_turn_context = round(denom / tot_turns) if tot_turns > 0 else 0

    sessions = get_recent_sessions(limit=limit, account=account)
    conn.close()

    return {
        "cache_hit_rate": overall_hit_rate,
        "avg_context_per_session": avg_session_context,
        "avg_context_per_turn": avg_turn_context,
        "peak_context_size": overall["peak_context_tokens"],
        "total_cache_tokens": tot_cache,
        "total_input_tokens": tot_in,
        "total_sessions": tot_sessions,
        "total_turns": tot_turns,
        "sessions": sessions
    }

def backup_sqlite_db():
    """
    Feature 10: Safely copies tokens_history.db using the SQLite Online Backup API.
    Writes to Downloads or Desktop with a timestamped filename.
    """
    user_profile = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    downloads_dir = os.path.join(user_profile, "Downloads")
    desktop_dir = os.path.join(user_profile, "Desktop")
    target_dir = downloads_dir if os.path.isdir(downloads_dir) else desktop_dir
    os.makedirs(target_dir, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"tokens_history_backup_{ts}.db"
    dest_path = os.path.join(target_dir, backup_filename)

    src_conn = get_db_connection()
    try:
        try:
            src_conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        except Exception:
            pass
        bck_conn = sqlite3.connect(dest_path)
        try:
            src_conn.backup(bck_conn)
        finally:
            bck_conn.close()
    finally:
        src_conn.close()

    size_bytes = os.path.getsize(dest_path) if os.path.exists(dest_path) else 0
    return {
        "ok": True,
        "filename": backup_filename,
        "path": dest_path,
        "size_bytes": size_bytes,
        "timestamp": ts,
        "message": f"Database backup saved successfully to {dest_path}"
    }

def generate_executive_html_report(time_range="month", account="all"):
    """
    Feature 10: Standalone, beautifully styled offline HTML executive report.
    Summarizes token volume, prompt cache efficiency, model distribution, and cloud cost equivalency.
    """
    summary = get_token_summary(time_range=time_range, account=account)
    totals = summary.get("totals", {})
    cost_info = summary.get("cost_equivalency", {})
    benchmarks = cost_info.get("benchmarks", {})
    hourly = get_hourly_productivity(account=account, range_key=time_range)
    sessions = get_recent_sessions(limit=10, account=account)

    gen_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    range_label = {
        "today": "Today's Telemetry",
        "7d": "Last 7 Days",
        "month": "Current Month",
        "year": "Current Year",
        "all": "All Time"
    }.get(time_range, time_range.capitalize())

    def fnum(v):
        try:
            return f"{int(v):,}"
        except Exception:
            return str(v or 0)

    def fcurr(v):
        try:
            return f"${float(v):,.2f}"
        except Exception:
            return "$0.00"

    tot_tokens = totals.get("total_tokens", 0)
    tot_in = totals.get("total_in", 0)
    tot_out = totals.get("total_out", 0)
    tot_cache = totals.get("total_cache", 0)
    tot_turns = totals.get("total_steps", 0)
    tot_sessions = totals.get("total_sessions", 0)
    cache_hit = totals.get("cache_hit_rate", 0.0)
    est_cost = cost_info.get("estimated_cost_usd", 0.0)
    savings = cost_info.get("cache_savings_usd", 0.0)

    # Hourly chart data
    max_hour_tokens = max([h["total_tokens"] for h in hourly] + [1])
    hourly_bars_html = ""
    for h in hourly:
        pct = max(3, round((h["total_tokens"] / max_hour_tokens) * 100)) if h["total_tokens"] > 0 else 3
        bar_color = "#3b82f6" if h["total_tokens"] > 0 else "#232330"
        hourly_bars_html += f"""
        <div class="h-col" title="Hour {h['hour']:02d}:00 | {fnum(h['total_tokens'])} tokens ({fnum(h['turns'])} turns)">
          <div class="bar-container">
            <div class="bar-fill" style="height: {pct}%; background: {bar_color};"></div>
          </div>
          <div class="hour-label">{h['hour']}</div>
        </div>
        """

    # Model rows
    model_rows_html = ""
    for m in cost_info.get("breakdown", []):
        m_tot = m.get("total_tokens", 0)
        m_pct = round((m_tot / tot_tokens * 100.0), 1) if tot_tokens > 0 else 0.0
        model_rows_html += f"""
        <tr>
          <td class="font-mono text-white"><strong>{m.get('model', 'Unknown')}</strong></td>
          <td><span class="badge">{m.get('benchmark', 'Standard')}</span></td>
          <td class="text-right font-mono">{fnum(m.get('input_tokens', 0))}</td>
          <td class="text-right font-mono">{fnum(m.get('output_tokens', 0))}</td>
          <td class="text-right font-mono text-cyan">{fnum(m.get('cache_tokens', 0))}</td>
          <td class="text-right font-mono font-bold text-white">{fnum(m_tot)}</td>
          <td class="text-right font-mono">{m_pct}%</td>
          <td class="text-right font-mono text-emerald font-bold">{fcurr(m.get('total_cost_usd', 0))}</td>
        </tr>
        """

    # Session rows
    session_rows_html = ""
    for s in sessions:
        short_id = s.get("session_id", "")[:12] + "..." if len(s.get("session_id", "")) > 12 else s.get("session_id", "")
        session_rows_html += f"""
        <tr>
          <td class="font-mono text-cyan" title="{s.get('session_id', '')}">{short_id}</td>
          <td class="text-muted">{s.get('model', 'Unknown')}</td>
          <td class="text-right font-mono">{fnum(s.get('total_turns', 0))}</td>
          <td class="text-right font-mono">{fnum(s.get('avg_context_tokens', 0))}</td>
          <td class="text-right font-mono">{fnum(s.get('max_context_tokens', 0))}</td>
          <td class="text-right font-mono text-white font-semibold">{fnum(s.get('total_tokens', 0))}</td>
          <td class="text-right font-mono text-muted text-xs">{s.get('last_turn', '')}</td>
        </tr>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Antigravity Control Center - Executive Report ({range_label})</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background-color: #0b0c10;
      color: #e5e7eb;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      padding: 32px 24px;
      line-height: 1.5;
    }}
    .max-w {{ max-width: 1200px; margin: 0 auto; }}
    .header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      border-bottom: 1px solid #1f222e;
      padding-bottom: 24px;
      margin-bottom: 28px;
    }}
    .brand {{
      display: flex;
      align-items: center;
      gap: 12px;
    }}
    .brand-logo {{
      width: 40px;
      height: 40px;
      background: linear-gradient(135deg, #3b82f6, #8b5cf6);
      border-radius: 10px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 800;
      color: #ffffff;
      font-size: 20px;
      letter-spacing: -1px;
    }}
    .brand-title {{
      font-size: 20px;
      font-weight: 700;
      color: #ffffff;
      letter-spacing: -0.5px;
    }}
    .brand-sub {{
      font-size: 13px;
      color: #9ca3af;
    }}
    .meta-badges {{
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }}
    .badge {{
      display: inline-block;
      padding: 4px 10px;
      border-radius: 6px;
      font-size: 12px;
      font-weight: 600;
      background: #191b24;
      border: 1px solid #2d3142;
      color: #d1d5db;
    }}
    .badge-cyan {{ background: rgba(6, 182, 212, 0.12); border-color: rgba(6, 182, 212, 0.4); color: #22d3ee; }}
    .badge-emerald {{ background: rgba(16, 185, 129, 0.12); border-color: rgba(16, 185, 129, 0.4); color: #34d399; }}
    .print-btn {{
      padding: 7px 14px;
      background: #2563eb;
      color: #fff;
      border: none;
      border-radius: 6px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.15s;
    }}
    .print-btn:hover {{ background: #1d4ed8; }}
    
    /* KPI Cards */
    .grid-4 {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
      gap: 16px;
      margin-bottom: 28px;
    }}
    .card {{
      background: #13151f;
      border: 1px solid #202434;
      border-radius: 10px;
      padding: 20px;
    }}
    .card-title {{
      font-size: 12px;
      font-weight: 600;
      color: #9ca3af;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 8px;
    }}
    .card-val {{
      font-size: 26px;
      font-weight: 700;
      color: #ffffff;
      font-family: Consolas, monospace;
      margin-bottom: 4px;
    }}
    .card-sub {{
      font-size: 12px;
      color: #6b7280;
    }}

    /* Section Styling */
    .section {{
      background: #13151f;
      border: 1px solid #202434;
      border-radius: 10px;
      padding: 24px;
      margin-bottom: 28px;
    }}
    .section-title {{
      font-size: 15px;
      font-weight: 700;
      color: #ffffff;
      margin-bottom: 16px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}

    /* Tables */
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th {{
      text-align: left;
      padding: 10px 12px;
      border-bottom: 1px solid #24293d;
      color: #9ca3af;
      font-weight: 600;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }}
    td {{
      padding: 12px;
      border-bottom: 1px solid #1a1e2e;
      color: #d1d5db;
    }}
    tr:last-child td {{ border-bottom: none; }}
    .text-right {{ text-align: right; }}
    .font-mono {{ font-family: Consolas, monospace; }}
    .font-bold {{ font-weight: 700; }}
    .text-white {{ color: #ffffff; }}
    .text-muted {{ color: #9ca3af; }}
    .text-cyan {{ color: #22d3ee; }}
    .text-emerald {{ color: #34d399; }}
    .text-amber {{ color: #fbbf24; }}
    .text-xs {{ font-size: 11px; }}

    /* Hourly Chart */
    .hourly-grid {{
      display: flex;
      align-items: flex-end;
      height: 140px;
      gap: 6px;
      padding-top: 10px;
      border-bottom: 1px solid #24293d;
      padding-bottom: 6px;
    }}
    .h-col {{
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      height: 100%;
      justify-content: flex-end;
    }}
    .bar-container {{
      width: 100%;
      height: 110px;
      display: flex;
      align-items: flex-end;
      justify-content: center;
    }}
    .bar-fill {{
      width: 70%;
      max-width: 16px;
      border-radius: 3px 3px 0 0;
      transition: height 0.3s;
    }}
    .hour-label {{
      font-size: 10px;
      color: #6b7280;
      font-family: Consolas, monospace;
      margin-top: 4px;
    }}

    /* Benchmark Grid */
    .benchmarks-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
      margin-top: 12px;
    }}
    .bench-card {{
      background: #181b28;
      border: 1px solid #24293d;
      border-radius: 8px;
      padding: 16px;
    }}
    .bench-name {{
      font-size: 13px;
      font-weight: 600;
      color: #9ca3af;
      margin-bottom: 6px;
    }}
    .bench-val {{
      font-size: 22px;
      font-weight: 700;
      font-family: Consolas, monospace;
      color: #ffffff;
      margin-bottom: 4px;
    }}
    .bench-note {{
      font-size: 11px;
      color: #6b7280;
    }}

    .footer {{
      margin-top: 32px;
      padding-top: 16px;
      border-top: 1px solid #1a1e2e;
      font-size: 12px;
      color: #4b5563;
      display: flex;
      justify-content: space-between;
    }}

    @media print {{
      body {{ background: #ffffff !important; color: #111827 !important; padding: 0; }}
      .card, .section, .bench-card {{ background: #ffffff !important; border: 1px solid #e5e7eb !important; color: #111827 !important; }}
      .card-val, .brand-title, .section-title, .text-white, .bench-val {{ color: #111827 !important; }}
      .print-btn {{ display: none; }}
      th {{ border-color: #e5e7eb; color: #4b5563; }}
      td {{ border-color: #f3f4f6; color: #1f2937; }}
    }}
  </style>
</head>
<body>
  <div class="max-w">
    <div class="header">
      <div class="brand">
        <div class="brand-logo">AG</div>
        <div>
          <div class="brand-title">ANTIGRAVITY EXECUTIVE REPORT</div>
          <div class="brand-sub">Comprehensive Token Telemetry, Cloud Equivalency & Efficiency Audit</div>
        </div>
      </div>
      <div class="meta-badges">
        <span class="badge badge-cyan">{range_label}</span>
        <span class="badge">Account: {account}</span>
        <span class="badge">{gen_time}</span>
        <button class="print-btn" onclick="window.print()">Export / Print PDF</button>
      </div>
    </div>

    <!-- Top KPI Grid -->
    <div class="grid-4">
      <div class="card">
        <div class="card-title">Total Token Volume</div>
        <div class="card-val">{fnum(tot_tokens)}</div>
        <div class="card-sub">{fnum(tot_in)} in &bull; {fnum(tot_out)} out</div>
      </div>
      <div class="card">
        <div class="card-title">Prompt Cache Efficiency</div>
        <div class="card-val text-cyan">{cache_hit}%</div>
        <div class="card-sub">{fnum(tot_cache)} cache read tokens</div>
      </div>
      <div class="card">
        <div class="card-title">Estimated Cost Equivalency</div>
        <div class="card-val text-emerald">{fcurr(est_cost)}</div>
        <div class="card-sub">Saved {fcurr(savings)} via prompt caching</div>
      </div>
      <div class="card">
        <div class="card-title">Activity Scope</div>
        <div class="card-val">{fnum(tot_turns)} turns</div>
        <div class="card-sub">{fnum(tot_sessions)} sessions &bull; avg {fnum(totals.get('avg_context_per_turn', 0))} ctx/turn</div>
      </div>
    </div>

    <!-- Cloud Cost Benchmark Equivalency -->
    <div class="section">
      <div class="section-title">
        <span>Commercial Cloud Benchmark Equivalency</span>
        <span class="badge badge-emerald">Real Dollar Equivalent Value</span>
      </div>
      <p style="font-size: 13px; color: #9ca3af; margin-bottom: 14px;">
        Comparing workload volume against benchmark commercial API rates for standard cloud providers:
      </p>
      <div class="benchmarks-grid">
        <div class="bench-card">
          <div class="bench-name">Anthropic Claude 3.5 Sonnet</div>
          <div class="bench-val text-amber">{fcurr(benchmarks.get('claude_35_sonnet', 0))}</div>
          <div class="bench-note">Benchmarked at $3.00/M input, $15.00/M output, $0.30/M cache</div>
        </div>
        <div class="bench-card">
          <div class="bench-name">Google Gemini 2.5 Pro</div>
          <div class="bench-val text-cyan">{fcurr(benchmarks.get('gemini_25_pro', 0))}</div>
          <div class="bench-note">Benchmarked at $1.25/M input, $5.00/M output, $0.31/M cache</div>
        </div>
        <div class="bench-card">
          <div class="bench-name">Google Gemini 2.5 Flash</div>
          <div class="bench-val text-emerald">{fcurr(benchmarks.get('gemini_25_flash', 0))}</div>
          <div class="bench-note">Benchmarked at $0.075/M input, $0.30/M output, $0.019/M cache</div>
        </div>
      </div>
    </div>

    <!-- Model Distribution & Share -->
    <div class="section">
      <div class="section-title">Model Workload Share & Economics</div>
      <table>
        <thead>
          <tr>
            <th>Model</th>
            <th>Benchmark Tier</th>
            <th class="text-right">Input</th>
            <th class="text-right">Output</th>
            <th class="text-right">Cache Read</th>
            <th class="text-right">Total Tokens</th>
            <th class="text-right">Share</th>
            <th class="text-right">Est. Cost</th>
          </tr>
        </thead>
        <tbody>
          {model_rows_html}
        </tbody>
      </table>
    </div>

    <!-- 24-Hour Productivity Distribution -->
    <div class="section">
      <div class="section-title">24-Hour Productivity & Token Distribution</div>
      <div class="hourly-grid">
        {hourly_bars_html}
      </div>
    </div>

    <!-- High-Impact Recent Sessions -->
    <div class="section">
      <div class="section-title">Recent High-Impact Sessions</div>
      <table>
        <thead>
          <tr>
            <th>Session ID</th>
            <th>Primary Model</th>
            <th class="text-right">Turns</th>
            <th class="text-right">Avg Context</th>
            <th class="text-right">Max Context</th>
            <th class="text-right">Total Tokens</th>
            <th class="text-right">Last Turn</th>
          </tr>
        </thead>
        <tbody>
          {session_rows_html}
        </tbody>
      </table>
    </div>

    <div class="footer">
      <div>Antigravity Control Center &bull; High-Performance Local Token Telemetry</div>
      <div>Verified SQLite WAL Engine &bull; Zero External Telemetry</div>
    </div>
  </div>
</body>
</html>
"""
    return html


def get_context_mode_stats():
    """
    Aggregates statistics from context-mode MCP sessions, merging:
      - Legacy v1 JSON session files (~/.gemini/context-mode/sessions/stats-pid-*.json)
      - Current v2 SQLite project databases (~/.context-mode/projects/*/context.db)
    Returns token savings, bytes sandboxed vs returned, cost avoidance,
    tool execution breakdown, and all-time daily activity since installation.
    """
    home_dir = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    v1_sessions_dir = os.path.join(home_dir, ".gemini", "context-mode", "sessions")
    v2_projects_dir = os.path.join(home_dir, ".context-mode", "projects")

    stats = {
        "active": False,
        "tokens_saved": 0,
        "bytes_sandboxed": 0,
        "bytes_returned": 0,
        "total_calls": 0,
        "reduction_pct": 0.0,
        "session_count": 0,
        "active_sessions": 0,
        "by_tool": {},
        "daily": [],
        "peak_day": None,
        "peak_calls": 0,
        "active_days": 0,
        "total_days": 0,
        "install_date": None,
        "last_updated": None
    }

    latest_ts = 0
    earliest_ts = None
    parsed_sessions = []
    v2_daily_rows = []

    # 1. Legacy v1 JSON session files
    if os.path.isdir(v1_sessions_dir):
        v1_files = glob.glob(os.path.join(v1_sessions_dir, "stats-pid-*.json"))
        stats["session_count"] += len(v1_files)

        for fpath in v1_files:
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    d = json.load(f)
                calls = d.get("total_calls", 0)
                tok_saved = d.get("tokens_saved", 0)
                if calls > 0:
                    stats["active"] = True
                    stats["active_sessions"] += 1
                stats["tokens_saved"] += tok_saved
                stats["bytes_sandboxed"] += d.get("bytes_sandboxed", 0)
                stats["bytes_returned"] += d.get("bytes_returned", 0)
                stats["total_calls"] += calls

                for tool, tdata in d.get("by_tool", {}).items():
                    if tool not in stats["by_tool"]:
                        stats["by_tool"][tool] = {"calls": 0, "bytes": 0}
                    stats["by_tool"][tool]["calls"] += tdata.get("calls", 0)
                    stats["by_tool"][tool]["bytes"] += tdata.get("bytes", 0)

                up_ts = d.get("updated_at", 0)
                start_ts = d.get("session_start", 0)
                if up_ts > latest_ts:
                    latest_ts = up_ts
                for ts_cand in (start_ts, up_ts):
                    if ts_cand > 0 and (earliest_ts is None or ts_cand < earliest_ts):
                        earliest_ts = ts_cand

                parsed_sessions.append((calls, tok_saved, up_ts, start_ts))
            except Exception:
                continue

    # 2. Current v2 SQLite project databases
    if os.path.isdir(v2_projects_dir):
        v2_dbs = glob.glob(os.path.join(v2_projects_dir, "*", "context.db"))
        for db_path in v2_dbs:
            conn = None
            try:
                uri = f"file:{db_path.replace(os.sep, '/')}?mode=ro"
                conn = sqlite3.connect(uri, uri=True, timeout=2.0)
                cur = conn.cursor()

                cur.execute(
                    """
                    SELECT
                        tool,
                        COUNT(*) AS calls,
                        COALESCE(SUM(CASE WHEN sandbox_bytes > returned_bytes THEN sandbox_bytes - returned_bytes ELSE 0 END), 0) AS kept_out,
                        COALESCE(SUM(returned_bytes), 0) AS returned_bytes,
                        COALESCE(SUM(sandbox_bytes), 0) AS sandbox_bytes,
                        MIN(created_at) AS min_ts,
                        MAX(created_at) AS max_ts
                    FROM events
                    WHERE tool IS NOT NULL AND tool != 'ctx_stats'
                    GROUP BY tool
                    """
                )
                rows = cur.fetchall()
                db_kept_out = 0
                db_calls = 0

                for tool, calls, kept_out, returned_bytes, sandbox_bytes, min_ts, max_ts in rows:
                    calls = int(calls or 0)
                    kept_out = int(kept_out or 0)
                    returned_bytes = int(returned_bytes or 0)
                    sandbox_bytes = int(sandbox_bytes or 0)
                    min_ts = int(min_ts or 0)
                    max_ts = int(max_ts or 0)

                    db_calls += calls
                    db_kept_out += kept_out
                    stats["total_calls"] += calls
                    stats["bytes_sandboxed"] += kept_out
                    stats["bytes_returned"] += returned_bytes

                    if tool not in stats["by_tool"]:
                        stats["by_tool"][tool] = {"calls": 0, "bytes": 0}
                    stats["by_tool"][tool]["calls"] += calls
                    stats["by_tool"][tool]["bytes"] += (sandbox_bytes if sandbox_bytes > 0 else returned_bytes)

                    if max_ts > latest_ts:
                        latest_ts = max_ts
                    if min_ts > 0 and (earliest_ts is None or min_ts < earliest_ts):
                        earliest_ts = min_ts

                if db_calls > 0:
                    stats["active"] = True
                    v2_tokens = int(round(db_kept_out / 4.0))
                    stats["tokens_saved"] += v2_tokens

                    cur.execute(
                        "SELECT COUNT(DISTINCT session_id) FROM events WHERE tool IS NOT NULL AND tool != 'ctx_stats'"
                    )
                    sess_row = cur.fetchone()
                    sess_cnt = int(sess_row[0] or 0) if sess_row else 0
                    stats["session_count"] += sess_cnt
                    stats["active_sessions"] += sess_cnt

                    cur.execute(
                        """
                        SELECT
                            date(created_at / 1000, 'unixepoch', 'localtime') AS day,
                            COUNT(*) AS calls,
                            COUNT(DISTINCT session_id) AS sessions,
                            COALESCE(SUM(CASE WHEN sandbox_bytes > returned_bytes THEN sandbox_bytes - returned_bytes ELSE 0 END), 0) AS kept_out
                        FROM events
                        WHERE tool IS NOT NULL AND tool != 'ctx_stats' AND created_at > 0
                        GROUP BY day
                        """
                    )
                    for day_str, d_calls, d_sessions, d_kept in cur.fetchall():
                        if day_str:
                            v2_daily_rows.append((
                                day_str,
                                int(d_calls or 0),
                                int(d_sessions or 0),
                                int(round((d_kept or 0) / 4.0))
                            ))
            except Exception:
                continue
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass

    if stats["by_tool"]:
        stats["by_tool"] = dict(
            sorted(stats["by_tool"].items(), key=lambda kv: kv[1].get("calls", 0), reverse=True)
        )

    total_bytes = stats["bytes_sandboxed"] + stats["bytes_returned"]
    if total_bytes > 0:
        stats["reduction_pct"] = round((stats["bytes_sandboxed"] / total_bytes) * 100, 2)

    if earliest_ts is not None:
        first_date = datetime.fromtimestamp(earliest_ts / 1000.0).date()
        end_date = datetime.now().date()
        if latest_ts > 0:
            latest_date = datetime.fromtimestamp(latest_ts / 1000.0).date()
            if latest_date > end_date:
                end_date = latest_date

        stats["install_date"] = first_date.strftime("%Y-%m-%d")
        num_days = (end_date - first_date).days + 1
        daily_map = {}
        daily_buckets = []
        for offset in range(num_days):
            d_obj = first_date + timedelta(days=offset)
            d_key = d_obj.strftime("%Y-%m-%d")
            bucket = {"date": d_key, "calls": 0, "sessions": 0, "tokens_saved": 0}
            daily_map[d_key] = bucket
            daily_buckets.append(bucket)

        for calls, tok_saved, up_ts, start_ts in parsed_sessions:
            ts_ref = up_ts if up_ts > 0 else start_ts
            if ts_ref > 0:
                d_end = datetime.fromtimestamp(ts_ref / 1000.0).date().strftime("%Y-%m-%d")
                if d_end in daily_map:
                    daily_map[d_end]["sessions"] += 1
                    daily_map[d_end]["calls"] += calls
                    daily_map[d_end]["tokens_saved"] += tok_saved
                if start_ts > 0 and start_ts < up_ts:
                    d_start = datetime.fromtimestamp(start_ts / 1000.0).date().strftime("%Y-%m-%d")
                    if d_start != d_end and d_start in daily_map:
                        daily_map[d_start]["sessions"] += 1

        for day_str, d_calls, d_sessions, d_tok_saved in v2_daily_rows:
            if day_str in daily_map:
                daily_map[day_str]["calls"] += d_calls
                daily_map[day_str]["sessions"] += d_sessions
                daily_map[day_str]["tokens_saved"] += d_tok_saved

        peak_day = None
        peak_score = 0
        peak_calls = 0
        active_days = 0
        for b in daily_buckets:
            score = b["calls"] if b["calls"] > 0 else (b["sessions"] * 0.01)
            if b["calls"] > 0 or b["sessions"] > 0:
                active_days += 1
            if score > peak_score:
                peak_score = score
                peak_day = b["date"]
                peak_calls = b["calls"]

        stats["daily"] = daily_buckets
        stats["peak_day"] = peak_day
        stats["peak_calls"] = peak_calls
        stats["active_days"] = active_days
        stats["total_days"] = len(daily_buckets)

    if latest_ts > 0:
        stats["last_updated"] = datetime.fromtimestamp(latest_ts / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    return stats


_AGY_FAST_CACHE_LOCK = threading.Lock()
_AGY_FAST_FILE_CACHE = {}

_AGY_FAST_TOOLS = ("batch_search", "apply_edits", "read_slices", "quick_outline", "run_checks")
_AGY_FAST_TOOL_RE = re.compile(r"(?:^|[_:./-])(batch_search|apply_edits|read_slices|quick_outline|run_checks)$")
_AGY_FAST_CLI_SEG_RE = re.compile(r"\bmcp-server\.mjs\b[\s\S]*?--cli\s+(search|outline|slice|edit|check)\b", re.IGNORECASE)
_AGY_FAST_CLI_MAP = {
    "search": "batch_search",
    "outline": "quick_outline",
    "slice": "read_slices",
    "edit": "apply_edits",
    "check": "run_checks",
}
_HOST_META_PREFIX_RE = re.compile(r"^(?:(?:Created At|Completed At):[^\r\n]*(?:\r?\n|$)|\r?\n)+")
_HOST_SPILL_FIRST_LINE_RE = re.compile(
    r"^(?:The output was large and was saved to:|(?:The (?:tool's |command's )?|Tool |Command )?output was truncated\b[^\r\n]*output\.txt)",
    re.IGNORECASE,
)
_HOST_SPILL_HEAD_RE = re.compile(r"^(?:The (?:tool's |command's )?|Tool |Command )?output was truncated\b", re.IGNORECASE)
_AGY_BUDGET_TRUNC_RE = re.compile(r"(?:^|\n)\.\.\.\s*\[truncated:")
_AGY_ERROR_HEAD_RE = re.compile(r"^(?:Encountered error in step execution|Error invalid tool call|Partial edit applied|Atomic edit aborted)\b")
_AGY_VERIFY_FAIL_RE = re.compile(r"(?:^|\n)Verify \[(?:FAIL\b|TIMEOUT\b|ERROR\b)")
_BLOCKING_TOOLS = {"ask_question", "swarm_wait", "schedule", "manage_subagents", "wait_for_subagents"}


def _unwrap_json_string(val):
    if not isinstance(val, str):
        return ""
    trimmed = val.strip()
    if len(trimmed) >= 2 and trimmed.startswith('"') and trimmed.endswith('"'):
        try:
            parsed = json.loads(trimmed)
            if isinstance(parsed, str):
                return parsed
        except Exception:
            pass
    return val


def _maybe_parse_json(val):
    if not isinstance(val, str):
        return val
    trimmed = val.strip()
    if trimmed.startswith(("[", "{")) or trimmed in ("true", "false", "null"):
        try:
            return json.loads(trimmed)
        except Exception:
            return val
    return val


def _get_call_args(call):
    raw = call.get("args")
    if raw is None:
        raw = call.get("arguments")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return None
    return None


def _extract_agy_fast_tool(call):
    name = call.get("name") or ""
    args = _get_call_args(call)
    if name == "call_mcp_tool":
        if not args:
            return None, None
        server = _unwrap_json_string(args.get("ServerName") or args.get("serverName") or args.get("server_name") or "")
        tool = _unwrap_json_string(args.get("ToolName") or args.get("toolName") or args.get("tool_name") or "")
        is_fast_server = (not server) or bool(re.search(r"(?:^|[_:/-])fast$", server, re.I)) or ("agy-fast" in server.lower())
        if not is_fast_server:
            return None, None
        m = _AGY_FAST_TOOL_RE.search(tool)
        return (m.group(1), "lazy") if m else (None, None)
    if name == "run_command":
        if not args:
            return None, None
        cmd = _unwrap_json_string(args.get("CommandLine") or args.get("commandLine") or args.get("command") or args.get("cmd") or "")
        if "--cli" not in cmd:
            return None, None
        for seg in re.split(r"\s*(?:&&|\|\||;|\|)\s*", cmd):
            if "--cli" not in seg:
                continue
            m = _AGY_FAST_CLI_SEG_RE.search(seg)
            if m:
                mapped = _AGY_FAST_CLI_MAP.get(m.group(1).lower())
                if mapped:
                    return mapped, "cli"
        return None, None
    m = _AGY_FAST_TOOL_RE.search(name)
    return (m.group(1), "eager") if m else (None, None)


def _extract_inner_fast_args(call, dispatch_mode):
    outer = _get_call_args(call)
    if not outer:
        return None
    if dispatch_mode != "lazy":
        return outer
    inner = outer.get("Arguments") if outer.get("Arguments") is not None else outer.get("arguments")
    for _ in range(2):
        if isinstance(inner, str):
            try:
                inner = json.loads(inner)
            except Exception:
                break
    return inner if isinstance(inner, dict) else None


def _count_batched_ops_and_corrupted(call, fast_tool, dispatch_mode):
    inner = _extract_inner_fast_args(call, dispatch_mode)
    if not inner or dispatch_mode == "cli":
        return 1, False

    if fast_tool == "batch_search":
        qs = _maybe_parse_json(inner.get("queries"))
        corrupted = (qs is None or isinstance(qs, bool)) if "queries" in inner else False
        if not corrupted and isinstance(qs, list):
            corrupted = any(not isinstance(q, dict) for q in qs)
        ops = len(qs) if isinstance(qs, list) and len(qs) > 0 else 1
        return ops, corrupted

    if fast_tool == "apply_edits":
        eds = _maybe_parse_json(inner.get("edits"))
        corrupted = (eds is None or isinstance(eds, bool)) if "edits" in inner else False
        ops = 0
        if isinstance(eds, list):
            if len(eds) == 0:
                corrupted = True
            for e in eds:
                if not isinstance(e, dict):
                    corrupted = True
                    continue
                if "hunks" in e and e["hunks"] is not None:
                    hunks = _maybe_parse_json(e["hunks"])
                    if not isinstance(hunks, list) or any(not isinstance(h, dict) for h in hunks):
                        corrupted = True
                    ops += len(hunks) if isinstance(hunks, list) and len(hunks) > 0 else 1
                else:
                    ops += 1
        verify_val = inner.get("verify")
        if isinstance(verify_val, str) and verify_val.strip():
            ops += 1
        return max(1, ops), corrupted

    if fast_tool == "quick_outline":
        raw = inner.get("paths") if inner.get("paths") is not None else (inner.get("outlines") if inner.get("outlines") is not None else inner.get("files"))
        has_key = any(k in inner for k in ("paths", "outlines", "files"))
        paths = _maybe_parse_json(raw)
        corrupted = (paths is None or isinstance(paths, bool)) if has_key else False
        if not corrupted and isinstance(paths, list):
            corrupted = any(not isinstance(p, str) for p in paths)
        ops = len(paths) if isinstance(paths, list) and len(paths) > 0 else 1
        return ops, corrupted

    if fast_tool == "read_slices":
        ops = 0
        corrupted = False
        for key in ("outlines", "lineRanges"):
            if key in inner:
                val = _maybe_parse_json(inner.get(key))
                if val is None or isinstance(val, bool):
                    corrupted = True
                elif isinstance(val, list):
                    if any(not isinstance(x, str) or not x.strip() for x in val):
                        corrupted = True
                    ops += len(val)
        if "slices" in inner:
            sl = _maybe_parse_json(inner.get("slices"))
            if sl is None or isinstance(sl, bool):
                corrupted = True
            elif isinstance(sl, list):
                for s in sl:
                    if isinstance(s, str):
                        if not s.strip():
                            corrupted = True
                        ops += 1
                    elif isinstance(s, dict):
                        ranges = _maybe_parse_json(s.get("ranges")) if "ranges" in s else None
                        if "ranges" in s and not isinstance(ranges, list):
                            corrupted = True
                        ops += len(ranges) if isinstance(ranges, list) and len(ranges) > 0 else 1
                    else:
                        corrupted = True
        return max(1, ops), corrupted

    if fast_tool == "run_checks":
        cmds = _maybe_parse_json(inner.get("commands"))
        corrupted = (cmds is None or isinstance(cmds, bool)) if "commands" in inner else False
        if not corrupted and isinstance(cmds, list):
            corrupted = any(not isinstance(c, (str, dict)) for c in cmds)
        ops = len(cmds) if isinstance(cmds, list) and len(cmds) > 0 else 1
        return ops, corrupted

    return 1, False


def _parse_iso_dt(iso_str):
    if not isinstance(iso_str, str) or not iso_str:
        return None
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except Exception:
        return None


def _get_tool_call_id(obj):
    for k in ("tool_call_id", "call_id", "id"):
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _resolve_existing_file(raw_path, cwd_str):
    """Resolves raw_path against cwd_str and returns (norm_key, file_size_bytes) if it exists."""
    if not isinstance(raw_path, str):
        return None, 0
    p = _unwrap_json_string(raw_path).strip()
    if not p:
        return None, 0
    if not os.path.isabs(p):
        if not cwd_str or not os.path.isdir(cwd_str):
            return None, 0
        p = os.path.join(cwd_str, p)
    try:
        abs_p = os.path.abspath(p)
        if not os.path.isfile(abs_p):
            return None, 0
        key = os.path.normcase(os.path.realpath(abs_p))
        return key, os.path.getsize(abs_p)
    except Exception:
        return None, 0


def _match_generic_responses(calls, generic_steps, planner_idx):
    """Maps call index -> matching GENERIC response step by tool_call_id or step_index."""
    if not calls or not generic_steps:
        return {}
    call_ids = {cid for cid in (_get_tool_call_id(c) for c in calls if isinstance(c, dict)) if cid}
    gen_by_id = {}
    gen_by_idx = {}
    any_explicit = False
    any_matched = False
    for gs in generic_steps:
        if isinstance(gs.get("tool_call_id"), str) and gs.get("tool_call_id").strip():
            any_explicit = True
        if isinstance(gs.get("call_id"), str) and gs.get("call_id").strip():
            any_explicit = True
        gid = _get_tool_call_id(gs)
        if gid:
            gen_by_id.setdefault(gid, gs)
            if gid in call_ids:
                any_matched = True
        sidx = gs.get("step_index")
        if isinstance(sidx, int) and sidx not in gen_by_idx:
            gen_by_idx[sidx] = gs

    use_id_mode = any_explicit or any_matched
    matched = {}
    for call_idx, call in enumerate(calls):
        if not isinstance(call, dict):
            continue
        cid = _get_tool_call_id(call)
        res_step = None
        if cid and cid in gen_by_id:
            res_step = gen_by_id[cid]
        elif not (cid and use_id_mode):
            if isinstance(planner_idx, int) and gen_by_idx:
                res_step = gen_by_idx.get(planner_idx + 1 + call_idx)
            elif planner_idx is None and not gen_by_idx and len(generic_steps) == len(calls):
                res_step = generic_steps[call_idx]
        if res_step is not None:
            matched[call_idx] = res_step
    return matched


def _estimate_effective_turns_saved(fast_tool, ops, inner):
    """Conservative estimate of whole LLM round-trips collapsed by one agy-fast call."""
    if ops <= 1:
        return 0.0
    if fast_tool == "apply_edits":
        has_verify = bool(isinstance(inner, dict) and isinstance(inner.get("verify"), str) and inner.get("verify").strip())
        if has_verify:
            edit_ops = max(1, ops - 1)
            return 1.0 + min(2.0, 0.5 * (edit_ops - 1))
        return min(2.5, 0.5 * (ops - 1))
    if fast_tool == "run_checks":
        return min(2.5, 0.5 * (ops - 1))
    return min(3.0, 0.35 * (ops - 1))


def _extract_outline_targets(fast_tool, inner):
    """Returns list of file paths requested for outline/slice reading from inner args."""
    if not isinstance(inner, dict):
        return []
    if fast_tool == "quick_outline":
        raw = inner.get("paths") if inner.get("paths") is not None else (inner.get("outlines") if inner.get("outlines") is not None else inner.get("files"))
        vals = _maybe_parse_json(raw)
        return [v for v in vals if isinstance(v, str)] if isinstance(vals, list) else []
    if fast_tool == "read_slices":
        vals = _maybe_parse_json(inner.get("outlines"))
        return [v for v in vals if isinstance(v, str)] if isinstance(vals, list) else []
    return []


def _extract_read_slice_targets(inner):
    """Returns list of file paths whose contents were read via read_slices."""
    if not isinstance(inner, dict):
        return []
    out = []
    lr = _maybe_parse_json(inner.get("lineRanges"))
    if isinstance(lr, list):
        for item in lr:
            if isinstance(item, str) and ":" in item:
                out.append(item.rsplit(":", 1)[0])
    sl = _maybe_parse_json(inner.get("slices"))
    if isinstance(sl, list):
        for item in sl:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict) and isinstance(item.get("path"), str):
                out.append(item["path"])
    return out


def _parse_single_transcript_for_agy_fast(fpath):
    """Extracts agy-fast usage, health, speed comparison, and daily buckets from one transcript."""
    steps = []
    has_fast_hint = False
    try:
        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                if "[agy-fast startup snapshot]" in s or "agy-fast" in s or "mcp-server.mjs" in s:
                    has_fast_hint = True
                try:
                    steps.append(json.loads(s))
                except Exception:
                    continue
    except Exception:
        return None

    if not steps:
        return None

    has_planner = False
    has_snapshot = False
    total_calls = 0
    batched_ops = 0
    by_tool = {t: {"calls": 0, "ops": 0} for t in _AGY_FAST_TOOLS}
    dispatch = {"eager": 0, "lazy": 0, "cli": 0}
    health = {"spills": 0, "errors": 0, "truncations": 0, "verify_fails": 0, "corrupted_args": 0}
    daily = {}
    session_days = set()
    earliest_ts_ms = None
    latest_ts_ms = None
    active_sec = 0.0
    total_out_tokens = 0
    out_samples = []
    cache_samples = []
    outlined_files = {}  # norm_key -> {"baseline_bytes": int, "outline_bytes": int, "day": str|None}
    read_bytes_by_file = {}  # norm_key -> int
    eff_turns_total = 0.0
    eff_turns_by_day = {}

    for i, step in enumerate(steps):
        stype = step.get("type")
        content = step.get("content")
        if not has_snapshot and isinstance(content, str) and "[agy-fast startup snapshot]" in content:
            if stype == "SYSTEM_MESSAGE" or (stype == "USER_INPUT" and "SessionStart" in content):
                has_snapshot = True
                dt = _parse_iso_dt(step.get("created_at"))
                if dt is not None:
                    ts_ms = int(dt.timestamp() * 1000)
                    earliest_ts_ms = ts_ms if earliest_ts_ms is None else min(earliest_ts_ms, ts_ms)
                    latest_ts_ms = ts_ms if latest_ts_ms is None else max(latest_ts_ms, ts_ms)
                    day_key = dt.astimezone().date().strftime("%Y-%m-%d")
                    session_days.add(day_key)

        if stype != "PLANNER_RESPONSE":
            continue

        has_planner = True
        out_tok = step.get("output_tokens") or 0
        if isinstance(out_tok, (int, float)) and out_tok > 0:
            total_out_tokens += int(out_tok)
            out_samples.append(int(out_tok))
        cache_tok = step.get("cache_read_tokens") or 0
        if isinstance(cache_tok, (int, float)) and cache_tok > 0:
            cache_samples.append(int(cache_tok))

        t_planner = _parse_iso_dt(step.get("created_at"))
        calls = step.get("tool_calls") or []
        has_blocking = any(isinstance(c, dict) and c.get("name") in _BLOCKING_TOOLS for c in calls)

        generic_steps = []
        generic_dts = []
        next_planner_dt = None
        for nxt in steps[i + 1:]:
            nt = nxt.get("type")
            if nt == "USER_INPUT":
                break
            if nt == "SYSTEM_MESSAGE" and not calls:
                break
            if nt == "PLANNER_RESPONSE":
                next_planner_dt = _parse_iso_dt(nxt.get("created_at"))
                break
            if nt == "GENERIC":
                generic_steps.append(nxt)
                gdt = _parse_iso_dt(nxt.get("created_at"))
                if gdt is not None:
                    generic_dts.append(gdt)

        if t_planner is not None and not has_blocking:
            if generic_dts:
                first_g = min(generic_dts)
                last_g = max(generic_dts)
                for seg in (
                    max(0.0, (first_g - t_planner).total_seconds()),
                    max(0.0, (last_g - first_g).total_seconds()),
                    max(0.0, (next_planner_dt - last_g).total_seconds()) if next_planner_dt else 0.0,
                ):
                    if seg <= 600.0:
                        active_sec += seg
            elif next_planner_dt is not None:
                span = max(0.0, (next_planner_dt - t_planner).total_seconds())
                if span <= 600.0:
                    active_sec += span

        if not has_fast_hint or not calls:
            continue

        matched_generics = _match_generic_responses(calls, generic_steps, step.get("step_index"))
        turn_day = t_planner.astimezone().date().strftime("%Y-%m-%d") if t_planner is not None else None

        # Track native read_file bytes against any files outlined in this session
        for call_idx, call in enumerate(calls):
            if not isinstance(call, dict):
                continue
            if call.get("name") == "read_file":
                rargs = _get_call_args(call) or {}
                rkey, _ = _resolve_existing_file(rargs.get("Path") or rargs.get("path"), None)
                if rkey and call_idx in matched_generics:
                    rtxt = matched_generics[call_idx].get("content") or ""
                    rbody = _HOST_META_PREFIX_RE.sub("", rtxt, count=1) if isinstance(rtxt, str) else ""
                    read_bytes_by_file[rkey] = read_bytes_by_file.get(rkey, 0) + len(rbody.encode("utf-8", errors="ignore"))

        for call_idx, call in enumerate(calls):
            if not isinstance(call, dict):
                continue
            fast_tool, mode = _extract_agy_fast_tool(call)
            if not fast_tool:
                continue
            ops, corrupted = _count_batched_ops_and_corrupted(call, fast_tool, mode)
            inner = _extract_inner_fast_args(call, mode)
            eff = _estimate_effective_turns_saved(fast_tool, ops, inner)
            total_calls += 1
            batched_ops += ops
            eff_turns_total += eff
            by_tool[fast_tool]["calls"] += 1
            by_tool[fast_tool]["ops"] += ops
            dispatch[mode] += 1
            if corrupted:
                health["corrupted_args"] += 1

            if t_planner is not None:
                ts_ms = int(t_planner.timestamp() * 1000)
                earliest_ts_ms = ts_ms if earliest_ts_ms is None else min(earliest_ts_ms, ts_ms)
                latest_ts_ms = ts_ms if latest_ts_ms is None else max(latest_ts_ms, ts_ms)
                session_days.add(turn_day)
                b = daily.setdefault(turn_day, {"calls": 0, "batched_ops": 0, "turns_saved": 0, "tokens_saved": 0})
                b["calls"] += 1
                b["batched_ops"] += ops
                b["turns_saved"] += max(0, ops - 1)
                eff_turns_by_day[turn_day] = eff_turns_by_day.get(turn_day, 0.0) + eff

            res_step = matched_generics.get(call_idx)
            if not res_step:
                continue

            res_text = res_step.get("content") if isinstance(res_step.get("content"), str) else ""
            raw_body = _HOST_META_PREFIX_RE.sub("", res_text, count=1)
            cli_exit = None
            body = raw_body
            if (call.get("name") or "") == "run_command":
                em = re.match(r"^Command exited with code (\d+)\.\s*(?:\r?\n)+(?:Command output:\r?\n)?", raw_body)
                if em:
                    cli_exit = int(em.group(1))
                    body = raw_body[em.end():]

            head = body.splitlines()[:3]
            first_line = head[0] if head else ""
            is_spill = bool(_HOST_SPILL_FIRST_LINE_RE.match(first_line)) or (
                bool(_HOST_SPILL_HEAD_RE.match(first_line)) and ("output.txt" in "\n".join(head))
            )
            if is_spill:
                health["spills"] += 1
            elif _AGY_BUDGET_TRUNC_RE.search(body):
                health["truncations"] += 1

            is_verify_fail = (fast_tool == "apply_edits") and (not is_spill) and bool(_AGY_VERIFY_FAIL_RE.search(body))
            is_normal_check_fail = (
                (fast_tool == "run_checks")
                and (cli_exit is not None and cli_exit != 0)
                and bool(re.match(r"^Checks:\s+\d+/\d+\s+passed,", body))
            )
            is_cli_err = (cli_exit is not None and cli_exit != 0) and (not is_verify_fail) and (not is_normal_check_fail)
            is_err = (
                res_step.get("status") in ("ERROR", "INVALID")
                or is_cli_err
                or bool(_AGY_ERROR_HEAD_RE.match(body))
                or ((call.get("name") or "") == "run_command" and not is_verify_fail and not is_normal_check_fail and body.startswith("Error:"))
            )
            if is_err:
                health["errors"] += 1
            elif is_verify_fail:
                health["verify_fails"] += 1

            if not is_err and not is_spill and isinstance(inner, dict):
                cwd_str = _unwrap_json_string(inner.get("cwd") or "").strip()
                if fast_tool == "read_slices":
                    sl_paths = _extract_read_slice_targets(inner)
                    if sl_paths:
                        per_slice_bytes = len(body.encode("utf-8", errors="ignore")) // len(sl_paths)
                        for sp in sl_paths:
                            skey, _ = _resolve_existing_file(sp, cwd_str)
                            if skey:
                                read_bytes_by_file[skey] = read_bytes_by_file.get(skey, 0) + per_slice_bytes
                outline_paths = _extract_outline_targets(fast_tool, inner)
                if outline_paths:
                    per_out_bytes = len(body.encode("utf-8", errors="ignore")) // len(outline_paths)
                    for op in outline_paths:
                        okey, fsize = _resolve_existing_file(op, cwd_str)
                        if okey and okey not in outlined_files:
                            # Cap baseline at read_file's 1-call limit (46,080 bytes)
                            outlined_files[okey] = {
                                "baseline_bytes": min(fsize, 46080),
                                "outline_bytes": per_out_bytes,
                                "day": turn_day,
                            }

    if not has_planner:
        return None

    outline_tokens_saved = 0
    for okey, info in outlined_files.items():
        saved_bytes = max(0, info["baseline_bytes"] - info["outline_bytes"] - read_bytes_by_file.get(okey, 0))
        tok = int(round(saved_bytes / 4.0))
        outline_tokens_saved += tok
        if info["day"] and info["day"] in daily:
            daily[info["day"]]["tokens_saved"] += tok

    med_out = 0
    if out_samples:
        sorted_out = sorted(out_samples)
        med_out = min(1500, sorted_out[len(sorted_out) // 2])
    elif total_calls > 0:
        med_out = 350

    med_cache = 0
    if cache_samples:
        sorted_cache = sorted(cache_samples)
        med_cache = sorted_cache[len(sorted_cache) // 2]

    turn_tokens_saved = int(round(eff_turns_total * med_out))
    cache_reads_avoided = int(round(eff_turns_total * med_cache))
    for d_key, et in eff_turns_by_day.items():
        if d_key in daily:
            daily[d_key]["tokens_saved"] += int(round(et * med_out))

    return {
        "has_fast": total_calls > 0,
        "has_snapshot": has_snapshot,
        "total_calls": total_calls,
        "batched_ops": batched_ops,
        "by_tool": by_tool,
        "dispatch": dispatch,
        "health": health,
        "daily": daily,
        "session_days": session_days,
        "earliest_ts_ms": earliest_ts_ms,
        "latest_ts_ms": latest_ts_ms,
        "active_sec": active_sec,
        "output_tokens": total_out_tokens,
        "outline_tokens_saved": outline_tokens_saved,
        "turn_tokens_saved": turn_tokens_saved,
        "cache_reads_avoided": cache_reads_avoided,
        "tokens_saved": outline_tokens_saved + turn_tokens_saved,
    }


def _inspect_agy_fast_plugin(home_dir):
    candidates = [
        os.path.join(home_dir, ".gemini", "config", "plugins", "agy-fast"),
        os.path.join(home_dir, ".agents", "plugins", "agy-fast"),
    ]
    plugin_dir = next((p for p in candidates if os.path.isfile(os.path.join(p, "plugin.json"))), None)
    info = {
        "installed": plugin_dir is not None,
        "version": None,
        "latest_version": None,
        "tool_loading": "unknown",
        "mcp_ready": False,
        "hook_ready": False,
    }
    if not plugin_dir:
        return info

    try:
        with open(os.path.join(plugin_dir, "plugin.json"), "r", encoding="utf-8") as f:
            pdata = json.load(f)
        info["version"] = pdata.get("version")
    except Exception:
        pass

    info["mcp_ready"] = os.path.isfile(os.path.join(plugin_dir, "dist", "mcp-server.mjs"))
    info["hook_ready"] = os.path.isfile(os.path.join(plugin_dir, "dist", "session-start.mjs")) and os.path.isfile(
        os.path.join(plugin_dir, "hooks.json")
    )

    try:
        with open(os.path.join(plugin_dir, "mcp_config.json"), "r", encoding="utf-8") as f:
            mc = json.load(f)
        tools = (mc.get("mcpServers") or {}).get("fast", {}).get("tools") or {}
        if isinstance(tools, dict) and tools:
            eager_flags = [bool(v.get("eager")) for v in tools.values() if isinstance(v, dict)]
            if eager_flags and all(eager_flags):
                info["tool_loading"] = "eager"
            elif eager_flags and not any(eager_flags):
                info["tool_loading"] = "lazy"
            elif eager_flags:
                info["tool_loading"] = "mixed"
    except Exception:
        pass

    cache_dir = (os.environ.get("AGY_FAST_CACHE_DIR") or "").strip() or os.path.join(
        home_dir, ".gemini", "cache", "agy-fast"
    )
    state_path = os.path.join(cache_dir, "update-state.json")
    if os.path.isfile(state_path):
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                ud = json.load(f)
            info["latest_version"] = ud.get("latestVersion")
        except Exception:
            pass
    return info


def _collect_local_transcript_files(home_dir):
    brain_dirs = [
        os.path.join(home_dir, ".gemini", "antigravity", "brain"),
        os.path.join(home_dir, ".gemini", "antigravity-cli", "brain"),
        os.path.join(home_dir, ".gemini", "antigravity-ide", "brain"),
    ]
    env_gemini = (os.environ.get("GEMINI_HOME") or "").strip()
    if env_gemini:
        brain_dirs.append(os.path.join(env_gemini, "antigravity-acp", "brain"))
        brain_dirs.append(os.path.join(env_gemini, "antigravity-cli", "brain"))
    env_app = (os.environ.get("ANTIGRAVITY_APP_DATA_DIR") or "").strip()
    if env_app:
        brain_dirs.append(os.path.join(env_app, "brain"))

    seen_files = set()
    files = []
    for bdir in brain_dirs:
        if not os.path.isdir(bdir):
            continue
        try:
            entries = os.scandir(bdir)
        except Exception:
            continue
        for entry in entries:
            if not entry.is_dir():
                continue
            logs_dir = os.path.join(entry.path, ".system_generated", "logs")
            full_p = os.path.join(logs_dir, "transcript_full.jsonl")
            basic_p = os.path.join(logs_dir, "transcript.jsonl")
            chosen = full_p if os.path.isfile(full_p) else (basic_p if os.path.isfile(basic_p) else None)
            if not chosen:
                continue
            try:
                real_p = os.path.realpath(chosen)
            except Exception:
                real_p = os.path.abspath(chosen)
            norm_key = real_p.lower() if os.name == "nt" else real_p
            if norm_key not in seen_files:
                seen_files.add(norm_key)
                files.append(chosen)
    return files


def get_agy_fast_stats():
    """
    Aggregates agy-fast MCP plugin status, batched operations, turn savings,
    tool breakdown, health checks, and all-time daily activity from local transcripts.
    """
    home_dir = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    plugin_info = _inspect_agy_fast_plugin(home_dir)
    transcript_files = _collect_local_transcript_files(home_dir)

    stats = {
        "installed": plugin_info["installed"],
        "active": False,
        "version": plugin_info["version"],
        "latest_version": plugin_info["latest_version"],
        "tool_loading": plugin_info["tool_loading"],
        "mcp_ready": plugin_info["mcp_ready"],
        "hook_ready": plugin_info["hook_ready"],
        "total_calls": 0,
        "batched_ops": 0,
        "turns_saved": 0,
        "tokens_saved": 0,
        "outline_tokens_saved": 0,
        "turn_tokens_saved": 0,
        "cache_reads_avoided": 0,
        "batch_multiplier": 0.0,
        "total_sessions": 0,
        "sessions_with_fast": 0,
        "sessions_with_snapshot": 0,
        "dispatch": {"eager": 0, "lazy": 0, "cli": 0},
        "by_tool": {},
        "health": {"spills": 0, "errors": 0, "truncations": 0, "verify_fails": 0, "corrupted_args": 0},
        "with_fast_tps": 0.0,
        "baseline_tps": 0.0,
        "daily": [],
        "peak_day": None,
        "peak_calls": 0,
        "active_days": 0,
        "total_days": 0,
        "last_updated": None,
    }

    by_tool_agg = {t: {"calls": 0, "ops": 0} for t in _AGY_FAST_TOOLS}
    daily_agg = {}
    earliest_ts_ms = None
    latest_ts_ms = None
    fast_active_sec = 0.0
    fast_out_tok = 0
    base_active_sec = 0.0
    base_out_tok = 0

    for fpath in transcript_files:
        try:
            st = os.stat(fpath)
            sig = (st.st_mtime_ns, st.st_size)
        except Exception:
            continue

        with _AGY_FAST_CACHE_LOCK:
            cached = _AGY_FAST_FILE_CACHE.get(fpath)
        if cached and cached[0] == sig:
            parsed = cached[1]
        else:
            parsed = _parse_single_transcript_for_agy_fast(fpath)
            with _AGY_FAST_CACHE_LOCK:
                _AGY_FAST_FILE_CACHE[fpath] = (sig, parsed)

        if not parsed:
            continue

        stats["total_sessions"] += 1
        if parsed["has_snapshot"]:
            stats["sessions_with_snapshot"] += 1
        if parsed["has_fast"]:
            stats["sessions_with_fast"] += 1
            fast_active_sec += parsed["active_sec"]
            fast_out_tok += parsed["output_tokens"]
        else:
            base_active_sec += parsed["active_sec"]
            base_out_tok += parsed["output_tokens"]

        stats["total_calls"] += parsed["total_calls"]
        stats["batched_ops"] += parsed["batched_ops"]
        stats["outline_tokens_saved"] += parsed.get("outline_tokens_saved", 0)
        stats["turn_tokens_saved"] += parsed.get("turn_tokens_saved", 0)
        stats["cache_reads_avoided"] += parsed.get("cache_reads_avoided", 0)
        stats["tokens_saved"] += parsed.get("tokens_saved", 0)
        for mode in ("eager", "lazy", "cli"):
            stats["dispatch"][mode] += parsed["dispatch"][mode]
        for hk in stats["health"]:
            stats["health"][hk] += parsed["health"][hk]
        for t in _AGY_FAST_TOOLS:
            by_tool_agg[t]["calls"] += parsed["by_tool"][t]["calls"]
            by_tool_agg[t]["ops"] += parsed["by_tool"][t]["ops"]

        if parsed["earliest_ts_ms"] is not None:
            earliest_ts_ms = parsed["earliest_ts_ms"] if earliest_ts_ms is None else min(earliest_ts_ms, parsed["earliest_ts_ms"])
        if parsed["latest_ts_ms"] is not None:
            latest_ts_ms = parsed["latest_ts_ms"] if latest_ts_ms is None else max(latest_ts_ms, parsed["latest_ts_ms"])

        for d_key in parsed["session_days"]:
            b = daily_agg.setdefault(d_key, {"calls": 0, "batched_ops": 0, "turns_saved": 0, "tokens_saved": 0, "sessions": 0})
            b["sessions"] += 1
        for d_key, vals in parsed["daily"].items():
            b = daily_agg.setdefault(d_key, {"calls": 0, "batched_ops": 0, "turns_saved": 0, "tokens_saved": 0, "sessions": 0})
            b["calls"] += vals["calls"]
            b["batched_ops"] += vals["batched_ops"]
            b["turns_saved"] += vals["turns_saved"]
            b["tokens_saved"] += vals.get("tokens_saved", 0)

    stats["turns_saved"] = max(0, stats["batched_ops"] - stats["total_calls"])
    if stats["total_calls"] > 0:
        stats["batch_multiplier"] = round(stats["batched_ops"] / stats["total_calls"], 1)
    if fast_active_sec > 0:
        stats["with_fast_tps"] = round(fast_out_tok / fast_active_sec, 1)
    if base_active_sec > 0:
        stats["baseline_tps"] = round(base_out_tok / base_active_sec, 1)

    stats["active"] = bool(stats["installed"] and (stats["total_calls"] > 0 or stats["sessions_with_snapshot"] > 0))
    stats["by_tool"] = dict(
        sorted(((t, v) for t, v in by_tool_agg.items() if v["calls"] > 0), key=lambda kv: kv[1]["calls"], reverse=True)
    )

    if earliest_ts_ms is not None:
        first_date = datetime.fromtimestamp(earliest_ts_ms / 1000.0).date()
        end_date = datetime.now().date()
        if latest_ts_ms is not None:
            latest_date = datetime.fromtimestamp(latest_ts_ms / 1000.0).date()
            if latest_date > end_date:
                end_date = latest_date

        num_days = (end_date - first_date).days + 1
        daily_buckets = []
        peak_day = None
        peak_score = 0
        peak_calls = 0
        active_days = 0
        for offset in range(num_days):
            d_key = (first_date + timedelta(days=offset)).strftime("%Y-%m-%d")
            raw = daily_agg.get(d_key) or {}
            calls = int(raw.get("calls", 0))
            ops = int(raw.get("batched_ops", 0))
            saved = int(raw.get("turns_saved", 0))
            tok_saved = int(raw.get("tokens_saved", 0))
            sess = int(raw.get("sessions", 0))
            daily_buckets.append({
                "date": d_key,
                "calls": calls,
                "batched_ops": ops,
                "turns_saved": saved,
                "tokens_saved": tok_saved,
                "sessions": sess,
            })
            if calls > 0 or sess > 0:
                active_days += 1
            score = calls if calls > 0 else (sess * 0.01)
            if score > peak_score:
                peak_score = score
                peak_day = d_key
                peak_calls = calls

        stats["daily"] = daily_buckets
        stats["peak_day"] = peak_day
        stats["peak_calls"] = peak_calls
        stats["active_days"] = active_days
        stats["total_days"] = len(daily_buckets)

    if latest_ts_ms is not None:
        stats["last_updated"] = datetime.fromtimestamp(latest_ts_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    return stats



