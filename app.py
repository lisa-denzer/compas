from flask import Flask, render_template, request, session, redirect, url_for
from openai import OpenAI
import os, json, random
from datetime import datetime, timezone

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "compas-ai-stable-secret")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
PASSCODE = os.getenv("PASSCODE", "ayuda")

# ---------- Utilities ----------
def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

# ---------- Load data ----------
PEOPLE  = load_json("data/people.json")                 # Lisa & Miguel profiles
CONTEXT = load_json("data/context.json")                # shared, slow-changing facts
IDEAS   = load_json("data/connection_ideas.json")       # suggestions pools
KIND    = load_json("data/kindness_exercises.json")     # kindness starters
MEM     = load_json("data/memory.json")                 # episodic facts

# ---------- Mode detection ----------
def detect_mode(text: str) -> str:
    t = (text or "").lower()
    if any(w in t for w in ["fight", "argu", "tension", "upset", "angry", "conflict", "snapped", "withdraw", "stonewall"]):
        return "REPAIR"
    if any(w in t for w in ["plan", "book", "tickets", "weekend", "schedule", "organise", "organize", "reservation"]):
        return "PLANNING"
    if any(w in t for w in ["miss", "hug", "cuddle", "affection", "reassure", "warm", "soothe", "snuggle"]):
        return "AFFECTION"
    if any(w in t for w in ["proud", "went well", "good day", "win", "progress", "we did it"]):
        return "CELEBRATE"
    return "GENERAL"

# ---------- Suggestion pickers (respect avoids, low-effort bias) ----------
def pick_connection_idea(target="lisa", effort_bias="low"):
    avoid_terms = set((w.lower() for w in PEOPLE[target].get("avoid", [])))
    pools = []
    for bucket in ("everyday", "shared", "surprise", "plans"):
        for item in IDEAS.get(bucket, []):
            # normalise: allow plain strings or richer objects
            obj = item if isinstance(item, dict) else {"text": item, "tags": [], "effort": "low"}
            txt = obj.get("text", "")
            # simple avoid filter: drop if any avoid term appears in text
            if any(term in txt.lower() for term in avoid_terms):
                continue
            pools.append(obj)
    if not pools:
        return None

    def score(o):
        s = 0
        if o.get("effort", "low") == effort_bias: s += 2
        if "acts_of_service" in o.get("tags", []): s += 1
        if o.get("novelty", "small") == "small": s += 1
        return s

    pools.sort(key=score, reverse=True)
    return pools[0]

def pick_kindness_starter():
    items = KIND.get("starters", [])
    return random.choice(items) if items else None

# ---------- System prompt builder (profile + context aware, Miguel-safe) ----------
def build_system_prompt(mode: str):
    mig = PEOPLE["miguel"]; lis = PEOPLE["lisa"]
    rel = CONTEXT.get("relationship", {})
    context_line = (
        f"Status={rel.get('status')}; live_together={rel.get('cohabitation')}; "
        f"home_base={rel.get('home_base')}; co_owners={', '.join(rel.get('co_owners', []))}; "
        f"assets={', '.join(rel.get('assets', []))}; pets={', '.join(rel.get('pets', []))}; "
        f"locales={', '.join(rel.get('preferred_locales', []))}; rituals={', '.join(rel.get('standing_rituals', []))}; "
        f"budget_style={rel.get('budget_style','sensible')}."
    )

    facts = [f["text"] for f in MEM.get("facts", [])]
    factline = " | ".join(facts[:6]) if facts else ""

    word_caps = {"GENERAL":110, "REPAIR":120, "PLANNING":110, "AFFECTION":90, "CELEBRATE":80}
    cap = word_caps.get(mode, 110)

    return f"""
You are Compás — a quiet, practical coach for Miguel (shy, low-initiative, goes quiet under stress).
Speak to Miguel only. No therapy, no emotional digging.

SHARED CONTEXT: {context_line}

Profiles (condensed):
- MIGUEL: {mig["summary"]}; style={mig["style"]}; comms={mig["communication"]};
  stress={mig["stress_response"]}; prefers_repairs={mig["preferred_repairs"]}; avoid={mig["avoid"]};
  activation={mig.get("activation","one small task, zero decisions")}
- LISA: {lis["summary"]}; soothing={lis["soothing"]}; avoid={lis["avoid"]}

Mode: {mode}

Hard rules:
1) Keep total ≤ {cap} words. Friendly, calm, low emotion; a hint of wit if safe.
2) DEFAULT: Give exactly ONE concrete action now. Optionally add ONE backup prefixed “Or:”.
3) Provide copy-ready wording in "words_to_say".
4) Never ask open questions. If unavoidable, use a yes/no micro-prompt.
5) In REPAIR use PAUSE: validate briefly → propose 30–60 min pause → set a resume time → one tiny act of service.
6) Respect both ‘avoid’ lists; prefer Lisa’s soothing items when upset.
7) Low effort first; familiar-before-novel unless explicitly asked for novelty.
8) Output STRICT JSON only:
   {{"mode": "...", "text": "...", "words_to_say": "...", "next_steps": ["..."], "duration_minutes": N}}

Style examples:
- “Put her mug out and make tea. Send one short line.”
- “Tidy the hallway for 3 minutes, then light a candle.”
- “Pause 30 min → talk at 19:30. Make tea. Keep it calm.”

Facts to keep in mind: {factline}
"""

# ---------- Model call ----------
def ask_compas(user_message: str):
    mode = detect_mode(user_message)
    sys_prompt = build_system_prompt(mode)

    idea = pick_connection_idea(target="lisa", effort_bias="low")
    kindness = pick_kindness_starter()
    gentle = PEOPLE["miguel"].get("gentle_starters", [])

    hints = {
        "idea_hint": (idea.get("text") if isinstance(idea, dict) else idea) if idea else None,
        "kindness_hint": kindness,
        "gentle_star": gentle[0] if gentle else None
    }
    hint_str = json.dumps(hints, ensure_ascii=False)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.4,
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"{user_message}\n\nHINTS (optional): {hint_str}"}
        ],
    )
    raw = response.choices[0].message.content.strip()

    # Be resilient to non-JSON (wrap if needed)
    try:
        data = json.loads(raw)
    except Exception:
        data = {
            "mode": mode,
            "text": raw[:200],
            "words_to_say": "",
            "next_steps": [],
            "duration_minutes": 5
        }
    return data

# ---------- Session helpers ----------
def seed_prompt_for_miguel():
    h = datetime.now().hour
    if h < 11:  return "Morning: one tiny thing I can do without talking, plus a 1-line message to copy."
    if h < 17:  return "Afternoon: one 2-minute act of service at home, no decisions needed."
    return "Evening: one small affectionate gesture (low effort), and a simple line I can send."

def start_new_session():
    session["sessions"].append({"started_at": now_iso(), "messages": []})
    session["current_idx"] += 1

# ---------- Flask routes ----------
@app.before_request
def make_session_permanent():
    session.permanent = True

@app.route("/", methods=["GET", "POST"])
def index():
    # Passcode gate
    if "authenticated" not in session:
        if request.method == "POST":
            code = request.form.get("passcode", "")
            if code == PASSCODE:
                session["authenticated"] = True
                return redirect(url_for("index"))
            return render_template("index.html", require_passcode=True, error="❌ Wrong passcode.")
        return render_template("index.html", require_passcode=True)

    # Initialise sessions structure
    if "sessions" not in session:
        session["sessions"] = []  # list of { "started_at": iso, "messages": [...] }
        session["current_idx"] = -1

    # Start first session and auto-nudge if none exists
    if session["current_idx"] == -1:
        start_new_session()
        try:
            payload = ask_compas(seed_prompt_for_miguel())
            pretty = (
                f"{payload.get('text','')}\n\n"
                f"🗣️ Say: {payload.get('words_to_say','')}\n"
                f"➡️ Next: " + " • ".join(payload.get('next_steps', [])) +
                f"\n⏱️ {payload.get('duration_minutes', 5)} min"
            ).strip()
        except Exception as e:
            pretty = f"Here’s one easy idea: bring her tea and a warm line. (init error: {e})"
        session["sessions"][session["current_idx"]]["messages"].append(
            {"role": "bot", "content": pretty, "ts": now_iso()}
        )

    # Reset/archive: start fresh session
    if request.method == "POST" and request.form.get("reset") == "1":
        start_new_session()
        try:
            payload = ask_compas(seed_prompt_for_miguel())
            pretty = (
                f"{payload.get('text','')}\n\n"
                f"🗣️ Say: {payload.get('words_to_say','')}\n"
                f"➡️ Next: " + " • ".join(payload.get('next_steps', [])) +
                f"\n⏱️ {payload.get('duration_minutes', 5)} min"
            ).strip()
        except Exception as e:
            pretty = f"Let’s start clean. (init error: {e})"
        session["sessions"][session["current_idx"]]["messages"].append(
            {"role": "bot", "content": pretty, "ts": now_iso()}
        )
        return render_template("index.html", sessions=session["sessions"], current_idx=session["current_idx"])

    # Normal chat
    if request.method == "POST":
        message = request.form.get("message", "").strip()
        if message:
            thread = session["sessions"][session["current_idx"]]["messages"]
            thread.append({"role": "user", "content": message, "ts": now_iso()})
            try:
                payload = ask_compas(message)
                pretty = (
                    f"{payload.get('text','')}\n\n"
                    f"🗣️ Say: {payload.get('words_to_say','')}\n"
                    f"➡️ Next: " + " • ".join(payload.get('next_steps', [])) +
                    f"\n⏱️ {payload.get('duration_minutes', 5)} min"
                ).strip()
            except Exception as e:
                pretty = f"⚠️ Error: {e}"
            thread.append({"role": "bot", "content": pretty, "ts": now_iso()})
        return render_template("index.html", sessions=session["sessions"], current_idx=session["current_idx"])

    # GET
    return render_template("index.html", sessions=session.get("sessions", []), current_idx=session.get("current_idx", -1))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)
