import os, json, sqlite3
from datetime import datetime
from flask import Flask, request, render_template, jsonify
from openai import OpenAI

app = Flask(__name__)

# === Environment & config ===
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
PORT = int(os.getenv("PORT", "5000"))
PASSCODE = os.getenv("PASSCODE")
DB_PATH = os.path.join(os.path.dirname(__file__), "db", "compas.db")

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
PROFILE_PATH = os.path.join(DATA_DIR, "lisa_profile.json")
PEOPLE_PATH = os.path.join(DATA_DIR, "people.json")
people = load_json(PEOPLE_PATH, {"miguel": {}, "lisa": {}})
MEMORY_PATH = os.path.join(DATA_DIR, "memory.json")


# === Database helpers ===
def init_db():
    """Create SQLite tables if missing."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS suggestions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            context TEXT,
            text TEXT,
            kind TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS feedback(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            suggestion_id INTEGER,
            outcome TEXT,
            notes TEXT,
            ts TEXT
        )
    """)
    con.commit()
    con.close()


def db_conn():
    return sqlite3.connect(DB_PATH)


# === Utilities ===
def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def get_client():
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set")
    return OpenAI(api_key=OPENAI_API_KEY)


# === System prompt ===
SYSTEM_PROMPT_TEMPLATE = """You are Compás — a concise, pragmatic coach on Miguel’s side.

Profiles:
MIGUEL:
{miguel_profile}

LISA:
{lisa_persona}

Rules:
- Speak Miguel’s language: clear, practical, action-first.
- Still anticipate Lisa’s emotional needs so advice doesn’t backfire.
- When conflict arises, prioritise: 1) control restored for Miguel, 2) small visible reassurance for Lisa.
- Avoid therapy jargon. Prefer verbs: fix, plan, decide, build.
- If Lisa wants novelty and Miguel needs order, offer **prepared novelty** (clear time, plan, and purpose).
- If Miguel withdraws and Lisa seeks closeness, propose a **structured re-entry** (short act, short message, clear timeframe).

Output ≤ 90 words:
1. One-sentence read of the situation.
2. Three lines:
   - MINIMUM — quick solo action.
   - TODAY — practical fix for both.
   - THIS WEEK — small system or habit.
3. End with “Pick one and do it.”

Keep tone firm but kind. No emojis, no therapy words, no fluff.

"""


SESSIONS = {}


# === Security ===
def require_passcode(req):
    if PASSCODE:
        hdr = req.headers.get("X-PASSCODE") or req.args.get("passcode")
        if hdr != PASSCODE:
            return True
    return False


# === Lessons (feedback memory) ===
def fetch_lessons():
    con = db_conn()
    cur = con.cursor()
    cur.execute("""
        SELECT suggestions.text, feedback.outcome
        FROM feedback JOIN suggestions
        ON feedback.suggestion_id = suggestions.id
        ORDER BY feedback.id DESC LIMIT 200
    """)
    rows = cur.fetchall()
    con.close()
    stats = {}
    for text, outcome in rows:
        key = text.strip()
        stats.setdefault(key, {"t": 0, "s": 0})
        stats[key]["t"] += 1
        if outcome == "success":
            stats[key]["s"] += 1
    ranked = sorted(
        stats.items(),
        key=lambda kv: (kv[1]["s"] + 1) / (kv[1]["t"] + 2),
        reverse=True
    )[:3]
    if not ranked:
        return "– (no prior wins yet)"
    return "\n".join([f"– {k} (worked before)" for k, _ in ranked])


# === Routes ===
@app.route("/")
def index():
    profile = load_json(PROFILE_PATH, {})
    return render_template("index.html", profile_json=json.dumps(profile, ensure_ascii=False))


@app.route("/chat", methods=["POST"])
def chat():
    if require_passcode(request):
        return jsonify({"error": "unauthorised"}), 401

    data = request.get_json(force=True)
    session_id = data.get("session_id", "default")
    user_message = data.get("message", "").strip()
    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    profile = load_json(PROFILE_PATH, {})
    mem = load_json(MEMORY_PATH, {"facts": []})
    lessons = fetch_lessons()

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
    miguel_profile=json.dumps(people.get("miguel", {}), ensure_ascii=False, indent=2),
    lisa_persona=json.dumps(people.get("lisa", {}), ensure_ascii=False, indent=2),
    lisa_profile=json.dumps(profile, ensure_ascii=False, indent=2),
    memory=json.dumps(mem, ensure_ascii=False, indent=2),
    lessons=lessons
    )

    conv = SESSIONS.get(session_id)
    if not conv:
        conv = [{"role": "system", "content": system_prompt}]
    conv.append({"role": "user", "content": user_message})

    try:
        client = get_client()
        resp = client.chat.completions.create(
            model=MODEL,
            messages=conv,
            temperature=0.15,
            max_tokens=220,
        )
        reply = resp.choices[0].message.content
    except Exception as e:
        reply = f"(Model error: {e})"

    # Extract suggestions (lines starting with - or •)
    suggestions = []
    for line in reply.splitlines():
        ln = line.strip()
        if ln.startswith("- ") or ln.startswith("• "):
            text = ln[2:].strip()
            if text:
                suggestions.append(text)

    ids = []
    if suggestions:
        con = db_conn()
        cur = con.cursor()
        for s in suggestions[:5]:
            cur.execute(
                "INSERT INTO suggestions(ts, context, text, kind) VALUES (?,?,?,?)",
                (datetime.utcnow().isoformat() + "Z", "{}", s, "plan"),
            )
            ids.append(cur.lastrowid)
        con.commit()
        con.close()

    conv.append({"role": "assistant", "content": reply})
    SESSIONS[session_id] = conv

    paired = [{"id": sid, "text": s, "kind": "plan"} for sid, s in zip(ids, suggestions[:len(ids)])]
    return jsonify({"reply": reply, "suggestions": paired, "session_id": session_id})


@app.route("/feedback", methods=["POST"])
def feedback():
    if require_passcode(request):
        return jsonify({"error": "unauthorised"}), 401
    data = request.get_json(force=True)
    sid = data.get("suggestion_id")
    outcome = data.get("outcome")
    notes = data.get("notes", "")
    if not sid or outcome not in ("success", "neutral", "fail"):
        return jsonify({"error": "invalid"}), 400
    con = db_conn()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO feedback(suggestion_id, outcome, notes, ts) VALUES (?,?,?,?)",
        (sid, outcome, notes, datetime.utcnow().isoformat() + "Z"),
    )
    con.commit()
    con.close()
    return jsonify({"ok": True})


@app.route("/suggest/gift", methods=["POST"])
def suggest_gift():
    if require_passcode(request):
        return jsonify({"error": "unauthorised"}), 401
    profile = load_json(PROFILE_PATH, {})
    mem = load_json(MEMORY_PATH, {"facts": []})
    likes = " ".join([f.get("text", "") for f in mem.get("facts", [])]).lower()

    out = []
    veg = str(profile.get("diet", "")).lower().startswith("veg")
    animal = "animal" in str(profile.get("values", "")).lower() or "cat" in likes or "pigeon" in likes or "hedgehog" in likes
    garden = "garden" in str(profile.get("interests", "")).lower() or "garden" in likes or "bulb" in likes
    travel = "road trip" in likes or "road" in likes
    eco = "eco" in str(profile.get("identity", "")).lower()

    if animal:
        out.append("Sponsor a rescue animal in her name + a handwritten note about why you chose it.")
    if garden:
        out.append("Quality secateurs + native bulbs kit, and block a morning to plant them together.")
    if veg:
        out.append("Booking at a great vegetarian spot + bring a small basil plant with a ribbon.")
    if eco:
        out.append("Reusable stylish thermos + planned winter beach walk with hot drinks.")
    if travel:
        out.append("Half-day road trip to a botanical garden or coastal trail; playlist + snacks ready.")
    out.append("A handwritten 6–8 sentence note: one admiration, one apology, one plan for next week.")

    return jsonify({"ideas": out[:5]})


@app.route("/memory", methods=["POST"])
def memory():
    if require_passcode(request):
        return jsonify({"error": "unauthorised"}), 401
    data = request.get_json(force=True)
    cmd = data.get("cmd")
    mem = load_json(MEMORY_PATH, {"facts": []})
    if cmd == "add":
        text = data.get("text", "").strip()
        if text:
            mem["facts"].append({"text": text, "ts": datetime.utcnow().isoformat() + "Z"})
            save_json(MEMORY_PATH, mem)
            return jsonify({"ok": True})
        return jsonify({"error": "empty"}), 400
    if cmd == "list":
        return jsonify(mem)
    if cmd == "delete":
        key = data.get("key", "").lower()
        mem["facts"] = [f for f in mem.get("facts", []) if key not in f.get("text", "").lower()]
        save_json(MEMORY_PATH, mem)
        return jsonify({"ok": True})
    return jsonify({"error": "bad cmd"}), 400


# === Startup ===
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=PORT, debug=True)
