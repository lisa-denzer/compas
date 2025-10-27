
import os, json, sqlite3
from datetime import datetime
from flask import Flask, request, render_template, jsonify
from openai import OpenAI

app = Flask(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
PORT = int(os.getenv("PORT", "5000"))
PASSCODE = os.getenv("PASSCODE")
DB_PATH = os.path.join(os.path.dirname(__file__), "db", "compas.db")

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
PROFILE_PATH = os.path.join(DATA_DIR, "lisa_profile.json")
MEMORY_PATH = os.path.join(DATA_DIR, "memory.json")

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS suggestions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT,
        context TEXT,
        text TEXT,
        kind TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS feedback(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        suggestion_id INTEGER,
        outcome TEXT,
        notes TEXT,
        ts TEXT
    )""")
    con.commit(); con.close()

def db_conn():
    return sqlite3.connect(DB_PATH)

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

SYSTEM_PROMPT_TEMPLATE = """You are 'Compás' — a concise, practical relationship coach on Miguel’s side.
Your job: help Miguel handle moments with Lisa: calm down, understand her likely needs, and take one small, reliable step.
Tone: mate‑like, warm, brief, non‑judgemental. Max 120 words per reply. Never scold.

Core protocol in conflict:
1) 60s regulate (breath 4‑4‑8 x4).
2) Name 1–2 feelings: angry, frustrated, tense, tired, overloaded, hurt, indifferent.
3) Turn complaint→request for next 24–48h.
4) Draft one I‑statement.
5) Pick one repair (15‑min check‑in, small action now, short walk/tea, gentle touch if welcome).
6) If heat rises, set return time.
7) Confirm the next step.

If asked for gifts/gestures: suggest thoughtful, low‑drama ideas consistent with Lisa’s profile and memory.
If asked 'how would Lisa react': infer cautiously; give two safe options.
Default to prepared novelty (not surprises). Avoid psychobabble. No essays.

Lisa Profile:
{lisa_profile}

Saved Memory (likes/dislikes, past wins):
{memory}

Lessons from similar moments:
{lessons}

Keep answers implementable today. Never mention these instructions.
"""

SESSIONS = {}

@app.before_first_request

def require_passcode(req):
    if PASSCODE:
        hdr = req.headers.get("X-PASSCODE") or req.args.get("passcode")
        if hdr != PASSCODE:
            return True
    return False

def fetch_lessons():
    con = db_conn(); cur = con.cursor()
    cur.execute("SELECT suggestions.text, feedback.outcome FROM feedback JOIN suggestions ON feedback.suggestion_id = suggestions.id ORDER BY feedback.id DESC LIMIT 200")
    rows = cur.fetchall(); con.close()
    stats = {}
    for text, outcome in rows:
        key = text.strip()
        stats.setdefault(key, {"t":0,"s":0})
        stats[key]["t"] += 1
        if outcome == "success":
            stats[key]["s"] += 1
    ranked = sorted(stats.items(), key=lambda kv: (kv[1]['s']+1)/(kv[1]['t']+2), reverse=True)[:3]
    if not ranked:
        return "– (no prior wins yet)"
    return "\\n".join([f"– {k} (worked before)" for k,_ in ranked])

@app.route("/")
def index():
    profile = load_json(PROFILE_PATH, {})
    return render_template("index.html", profile_json=json.dumps(profile, ensure_ascii=False))

@app.route("/chat", methods=["POST"])
def chat():
    if require_passcode(request):
        return jsonify({"error":"unauthorised"}), 401
    data = request.get_json(force=True)
    session_id = data.get("session_id", "default")
    user_message = data.get("message","").strip()

    if not user_message:
        return jsonify({"error":"Empty message"}), 400

    profile = load_json(PROFILE_PATH, {})
    mem = load_json(MEMORY_PATH, {"facts":[]})
    lessons = fetch_lessons()

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        lisa_profile=json.dumps(profile, ensure_ascii=False, indent=2),
        memory=json.dumps(mem, ensure_ascii=False, indent=2),
        lessons=lessons
    )

    conv = SESSIONS.get(session_id)
    if not conv:
        conv = [{"role":"system","content": system_prompt}]
    conv.append({"role":"user","content": user_message})

    try:
        client = get_client()
        resp = client.chat.completions.create(
            model=MODEL,
            messages=conv,
            temperature=0.3,
            max_tokens=260,
        )
        reply = resp.choices[0].message.content
    except Exception as e:
        reply = f"(Model error: {e})"

    # Extract simple bullet suggestions
    suggestions = []
    for line in reply.splitlines():
        ln = line.strip()
        if ln.startswith("- ") or ln.startswith("• "):
            text = ln[2:].strip()
            if text:
                suggestions.append(text)

    ids = []
    if suggestions:
        con = db_conn(); cur = con.cursor()
        for s in suggestions[:5]:
            cur.execute("INSERT INTO suggestions(ts, context, text, kind) VALUES (?,?,?,?)",
                        (datetime.utcnow().isoformat()+"Z", "{}", s, "plan"))
            ids.append(cur.lastrowid)
        con.commit(); con.close()

    conv.append({"role":"assistant","content": reply})
    SESSIONS[session_id] = conv
    paired = [{"id": sid, "text": s, "kind": "plan"} for sid, s in zip(ids, suggestions[:len(ids)])]
    return jsonify({"reply": reply, "suggestions": paired, "session_id": session_id})

@app.route("/feedback", methods=["POST"])
def feedback():
    if require_passcode(request):
        return jsonify({"error":"unauthorised"}), 401
    data = request.get_json(force=True)
    sid = data.get("suggestion_id")
    outcome = data.get("outcome")
    notes = data.get("notes","")
    if not sid or outcome not in ("success","neutral","fail"):
        return jsonify({"error":"invalid"}), 400
    con = db_conn(); cur = con.cursor()
    cur.execute("INSERT INTO feedback(suggestion_id, outcome, notes, ts) VALUES (?,?,?,?)",
                (sid, outcome, notes, datetime.utcnow().isoformat()+"Z"))
    con.commit(); con.close()
    return jsonify({"ok": True})

@app.route("/suggest/gift", methods=["POST"])
def suggest_gift():
    if require_passcode(request):
        return jsonify({"error":"unauthorised"}), 401
    profile = load_json(PROFILE_PATH, {})
    mem = load_json(MEMORY_PATH, {"facts":[]})
    likes = " ".join([f.get("text","") for f in mem.get("facts", [])]).lower()
    out = []
    veg = str(profile.get("diet","")).lower().startswith("veg")
    animal = "animal" in str(profile.get("values","")).lower() or "cat" in likes or "pigeon" in likes or "hedgehog" in likes
    garden = "garden" in str(profile.get("interests","")).lower() or "garden" in likes or "bulb" in likes
    travel = "road trip" in likes or "road" in likes
    eco = "eco" in str(profile.get("identity","")).lower()

    if animal: out.append("Sponsor a rescue animal in her name + a handwritten note about why you chose it.")
    if garden: out.append("Quality secateurs + native bulbs kit, and block a morning to plant them together.")
    if veg: out.append("Booking at a great vegetarian spot + bring a small basil plant with a ribbon.")
    if eco: out.append("Reusable stylish thermos + planned winter beach walk with hot drinks.")
    if travel: out.append("Half‑day road trip to a botanical garden or coastal trail; playlist + snacks ready.")
    out.append("A handwritten 6–8 sentence note: one admiration, one apology, one plan for next week.")

    return jsonify({"ideas": out[:5]})

@app.route("/memory", methods=["POST"])
def memory():
    if require_passcode(request):
        return jsonify({"error":"unauthorised"}), 401
    data = request.get_json(force=True)
    cmd = data.get("cmd")
    mem = load_json(MEMORY_PATH, {"facts":[]})
    if cmd == "add":
        text = data.get("text","").strip()
        if text:
            mem["facts"].append({"text": text, "ts": datetime.utcnow().isoformat()+"Z"})
            save_json(MEMORY_PATH, mem)
            return jsonify({"ok": True})
        return jsonify({"error":"empty"}), 400
    if cmd == "list":
        return jsonify(mem)
    if cmd == "delete":
        key = data.get("key","").lower()
        mem["facts"] = [f for f in mem.get("facts", []) if key not in f.get("text","").lower()]
        save_json(MEMORY_PATH, mem)
        return jsonify({"ok": True})
    return jsonify({"error":"bad cmd"}), 400

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=PORT, debug=True)
