import os, json, sqlite3
from flask import Flask, request, jsonify, render_template
from openai import OpenAI

# -----------------------------------------------------------------------------
#  CONFIGURATION
# -----------------------------------------------------------------------------
app = Flask(__name__)

DATA_DIR       = os.path.join(os.path.dirname(__file__), "data")
PROFILE_PATH   = os.path.join(DATA_DIR, "lisa_profile.json")
MEMORY_PATH    = os.path.join(DATA_DIR, "memory.json")
PEOPLE_PATH    = os.path.join(DATA_DIR, "people.json")
DB_PATH        = os.path.join(DATA_DIR, "compas.db")
PORT           = int(os.environ.get("PORT", 5000))
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
MODEL          = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

# -----------------------------------------------------------------------------
#  UTILITIES
# -----------------------------------------------------------------------------
def db_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = db_conn()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT,
            text TEXT
        )"""
    )
    conn.commit()
    conn.close()

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
    return OpenAI(api_key=OPENAI_API_KEY)

# -----------------------------------------------------------------------------
#  SYSTEM PROMPT
# -----------------------------------------------------------------------------
SYSTEM_PROMPT_TEMPLATE = """You are Compás — a concise, pragmatic coach on Miguel’s side.

Profiles
--------
MIGUEL:
{miguel_profile}

LISA:
{lisa_persona}

Lisa’s broader profile:
{lisa_profile}

Current memory:
{memory}

Lessons from similar moments:
{lessons}

Rules
-----
- Speak Miguel’s language: clear, practical, action-first.
- Anticipate Lisa’s emotional needs so advice doesn’t backfire.
- When conflict arises: 1) control restored for Miguel, 2) visible reassurance for Lisa.
- Avoid therapy jargon or filler (no “I-statements”, “processing feelings”, “breathe”).
- Prefer verbs: fix, plan, decide, build.
- If Lisa wants novelty & Miguel needs order → offer **prepared novelty**.
- If Miguel withdraws & Lisa seeks closeness → propose **structured re-entry**.
- Output ≤ 90 words:

  1. One-line neutral read.
  2. Three lines:
     - MINIMUM — solo micro-action.
     - TODAY — practical fix for both.
     - THIS WEEK — small system/habit.
  3. End with “Pick one and do it.”

Tone: firm, kind, realistic. No emojis or therapy talk.
"""

# -----------------------------------------------------------------------------
#  ROUTES
# -----------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True)
    msg = data.get("message", "").strip()
    if not msg:
        return jsonify({"reply": "Empty message."})

    # Load context files
    profile = load_json(PROFILE_PATH, {})
    mem = load_json(MEMORY_PATH, {"facts": []})
    people = load_json(PEOPLE_PATH, {"miguel": {}, "lisa": {}})

    miguel_profile = people.get("miguel", {})
    lisa_persona   = people.get("lisa", {})
    lessons        = fetch_lessons()

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        miguel_profile=json.dumps(miguel_profile, ensure_ascii=False, indent=2),
        lisa_persona=json.dumps(lisa_persona, ensure_ascii=False, indent=2),
        lisa_profile=json.dumps(profile, ensure_ascii=False, indent=2),
        memory=json.dumps(mem, ensure_ascii=False, indent=2),
        lessons=lessons
    )

    client = get_client()
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": msg},
            ],
            temperature=0.15,
            max_tokens=220,
        )
        reply = resp.choices[0].message.content.strip()
    except Exception as e:
        if "insufficient_quota" in str(e):
            reply = "⚠️ OpenAI quota exceeded. Please top up or update your API key."
        else:
            reply = f"(Model error: {e})"

    return jsonify({"reply": reply})

@app.route("/suggest/gift", methods=["POST"])
def suggest_gift():
    return jsonify({"suggestions": [
        "Tidy one visible area she cares about.",
        "Bring tea without words.",
        "Plan a small repair or garden fix."
    ]})

@app.route("/memory", methods=["POST"])
def memory_ops():
    data = request.get_json(force=True)
    cmd = data.get("cmd")
    mem = load_json(MEMORY_PATH, {"facts": []})

    if cmd == "list":
        return jsonify(mem)
    elif cmd == "add":
        item = data.get("item")
        if item:
            mem["facts"].append(item)
            save_json(MEMORY_PATH, mem)
        return jsonify({"status": "ok"})
    else:
        return jsonify({"error": "Unknown command"}), 400

# -----------------------------------------------------------------------------
#  HELPER FOR LESSONS
# -----------------------------------------------------------------------------
def fetch_lessons():
    try:
        conn = db_conn()
        rows = conn.execute("SELECT topic, text FROM lessons ORDER BY id DESC LIMIT 10").fetchall()
        conn.close()
        return "\n".join(f"- {r['topic']}: {r['text']}" for r in rows)
    except Exception:
        return ""

# -----------------------------------------------------------------------------
#  MAIN
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=PORT, debug=True)
