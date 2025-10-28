import os, json, sqlite3
from flask import Flask, request, jsonify, render_template
from openai import OpenAI
from reflection import (
    random_reflection,
    random_connection_idea,
    random_kindness_exercise,
    save_reflection_response,
)

app = Flask(__name__)

# -------------------- Config --------------------
DATA_DIR       = os.path.join(os.path.dirname(__file__), "data")
PEOPLE_PATH    = os.path.join(DATA_DIR, "people.json")   # single source of truth
MEMORY_PATH    = os.path.join(DATA_DIR, "memory.json")
DB_PATH        = os.path.join(DATA_DIR, "compas.db")     # optional “lessons”
PORT           = int(os.environ.get("PORT", 5000))
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
MODEL          = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
PASSCODE       = os.environ.get("PASSCODE", "")          # optional

# -------------------- Utils --------------------
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
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set")
    return OpenAI(api_key=OPENAI_API_KEY)

def require_passcode(req):
    if not PASSCODE:
        return False
    given = req.headers.get("X-PASSCODE") or req.args.get("passcode")
    return given != PASSCODE

def fetch_lessons():
    try:
        conn = db_conn()
        rows = conn.execute("SELECT topic, text FROM lessons ORDER BY id DESC LIMIT 10").fetchall()
        conn.close()
        return "\n".join(f"- {r['topic']}: {r['text']}" for r in rows) if rows else ""
    except Exception:
        return ""

# -------------------- System Prompt --------------------
SYSTEM_PROMPT_TEMPLATE = """You are Compás — a practical, friendly coach who helps Miguel handle daily life with Lisa.
Tone: calm, clear, respectful. Use simple UK English that is easy for non-native speakers. Prefer actions over long talks.

Profiles (from people.json):
MIGUEL: {miguel_profile}
LISA: {lisa_profile}
Memory: {memory}
Lessons: {lessons}

Rules:
- Write 150–180 words maximum.
- For each option give: ACTION + what to SAY (simple sentence) + WHY it helps.
- Include one calm reaction line if Lisa pushes back.
- Avoid idioms. Avoid “you always” or “why did you…”. Use “I notice / Can we / Next time…”.
- Offer a no-talk repair where possible.
- The style should sound confident but kind.

Format exactly:
Read: <short neutral line>
MINIMUM: <ACTION>. Say: “<SCRIPT>”. Why: <WHY>.
TODAY: <ACTION>. Say: “<SCRIPT>”. Why: <WHY>.
THIS WEEK: <ACTION>. Say: “<SCRIPT>”. Why: <WHY>.
If Lisa says “<her objection>” → you say: “<simple calm answer>”.
Finish: Do something small — it’s better than nothing.
"""

EXAMPLES = """
Example — Topic: lights left on
Read: A small thing that keeps happening and causes frustration.
MINIMUM: Turn the lights off and put a small note near the switch that says “Check lights before leaving.”
Say: “I added a note so we both remember.”
Why: It fixes the problem today without any argument.
TODAY: Suggest a habit: the person who leaves the room last turns the lights off.
Say: “Let’s agree that the one who leaves the room last turns the lights off.”
Why: A clear rule prevents repeating the same talk.
THIS WEEK: Install a motion sensor or set a timer so lights turn off automatically.
Say: “I’ll add a sensor this weekend so we don’t need to think about it anymore.”
Why: One small change removes future stress.
If Lisa says “It’s not a big deal” → you say: “I know, but I like small things to run smoothly for both of us.”
Finish: Do something small — it’s better than nothing.
"""

# -------------------- Routes --------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    if require_passcode(request):
        return jsonify({"error": "unauthorised"}), 401

    data = request.get_json(force=True)
    msg = (data.get("message") or "").strip()
    if not msg:
        return jsonify({"reply": "Empty message."})

    people = load_json(PEOPLE_PATH, {"miguel": {}, "lisa": {}})
    mem    = load_json(MEMORY_PATH, {"facts": []})
    lessons = fetch_lessons()

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        miguel_profile=json.dumps(people.get("miguel", {}), ensure_ascii=False, indent=2),
        lisa_profile=json.dumps(people.get("lisa", {}), ensure_ascii=False, indent=2),
        memory=json.dumps(mem, ensure_ascii=False, indent=2),
        lessons=lessons
    )

    try:
        client = get_client()
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt + "\n\n" + EXAMPLES},
                {"role": "user", "content": msg},
            ],
            temperature=0.15,
            max_tokens=300,
        )
        reply = resp.choices[0].message.content.strip()
    except Exception as e:
        if "insufficient_quota" in str(e):
            reply = "⚠️ OpenAI quota exceeded. Please top up or update your API key."
        else:
            reply = f"(Model error: {e})"

    return jsonify({"reply": reply})

@app.route("/daily_reflection", methods=["GET"])
def get_reflection():
    if require_passcode(request):
        return jsonify({"error": "unauthorised"}), 401
    return jsonify({
        "prompts": random_reflection(),
        "connection": random_connection_idea(),
        "kindness": random_kindness_exercise()
    })

@app.route("/daily_reflection", methods=["POST"])
def post_reflection():
    if require_passcode(request):
        return jsonify({"error": "unauthorised"}), 401
    data = request.get_json(force=True)
    user_id = data.get("user_id", "miguel")
    answers = data.get("answers", [])
    save_reflection_response(user_id, answers)
    return jsonify({"status": "ok"})

@app.route("/memory", methods=["POST"])
def memory_ops():
    if require_passcode(request):
        return jsonify({"error": "unauthorised"}), 401
    data = request.get_json(force=True)
    cmd = (data.get("cmd") or "").lower()
    mem = load_json(MEMORY_PATH, {"facts": []})

    if cmd == "list":
        return jsonify(mem)
    elif cmd == "add":
        item = data.get("item")
        if item:
            mem.setdefault("facts", []).append(item)
            save_json(MEMORY_PATH, mem)
        return jsonify({"status": "ok"})
    elif cmd == "delete":
        key = (data.get("key") or "").lower()
        mem["facts"] = [f for f in mem.get("facts", []) if key not in str(f).lower()]
        save_json(MEMORY_PATH, mem)
        return jsonify({"status": "ok"})
    else:
        return jsonify({"error": "unknown command"}), 400

@app.route("/lessons", methods=["GET","POST","DELETE"])
def lessons_api():
    if require_passcode(request):
        return jsonify({"error": "unauthorised"}), 401
    conn = db_conn()
    if request.method == "GET":
        rows = conn.execute("SELECT id, topic, text FROM lessons ORDER BY id DESC LIMIT 50").fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])
    data = request.get_json(force=True)
    if request.method == "POST":
        conn.execute("INSERT INTO lessons(topic, text) VALUES(?,?)",
                     (data.get("topic","general"), data.get("text","")))
        conn.commit(); conn.close()
        return jsonify({"status":"ok"})
    if request.method == "DELETE":
        conn.execute("DELETE FROM lessons WHERE id=?", (int(data["id"]),))
        conn.commit(); conn.close()
        return jsonify({"status":"ok"})

# -------------------- Main --------------------
if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

