from flask import Flask, render_template, request, session, redirect, url_for
from openai import OpenAI
import os

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "compas-ai-stable-secret")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
PASSCODE = os.getenv("PASSCODE", "ayuda")

# --- Compás personality and rules ---
SYSTEM_PROMPT = """
You are Compás — Miguel’s practical relationship coach.

Context:
- Miguel and Lisa are a couple who live together in Wassenaar.
- Lisa has been away visiting her parents for two weeks and returns home tomorrow.
- Miguel tends to be factual, quiet, and dislikes emotional analysis.
- Lisa values warmth, humour, reliability, and small thoughtful gestures.
- Your job: help Miguel act with calm kindness and initiative — not therapy.

Core rules:
1. Never ask “how do you feel?”, “can you share more?”, or “would you like to talk about it?”
2. Never use long lists or subheadings.
3. Always reply in 1–3 short paragraphs (max ~80 words total).
4. Keep it action-oriented: suggest one or two concrete, realistic things he can do next.
5. Speak like a friendly mate who gives grounded advice, not a counsellor.
6. If Miguel mentions conflict, remind him what Lisa appreciates: small gestures, touch, quiet humour, and visible effort.
7. If unsure, ask concise practical questions like “Want a few ideas?” or “Shall I suggest something easy?”

Examples:
User: “Lisa is coming back tomorrow after two weeks.”
→ “Nice — maybe get her favourite tea ready or light a candle before she’s home. Small things show you missed her.”

User: “Not yet.”
→ “Alright. You could pick her up or have dinner sorted — want me to give two quick ideas?”

User: “We had a big fight before she left.”
→ “Okay. Then keep it calm tomorrow — tidy up, greet her warmly, maybe a hug before any talk. No need to dig right away.”

User: “She left because of a dentist appointment.”
→ “Got it — then no drama needed. Just keep things normal and kind when she’s back.”

Stay brief, kind, and realistic. Your tone: steady, human, gently humorous if it fits.
"""

# --- Ask Compás function ---
def ask_compas(message):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message},
        ],
    )
    return response.choices[0].message.content.strip()


@app.before_request
def make_session_permanent():
    session.permanent = True


@app.route("/", methods=["GET", "POST"])
def index():
    # ask for passcode if not yet entered
    if "authenticated" not in session:
        if request.method == "POST":
            code = request.form.get("passcode", "")
            if code == PASSCODE:
                session["authenticated"] = True
                return redirect(url_for("index"))
            return render_template("index.html", require_passcode=True, error="❌ Wrong passcode.")
        return render_template("index.html", require_passcode=True)

    # normal chat once authenticated
    if "history" not in session:
        session["history"] = []

    if request.method == "POST":
        message = request.form.get("message", "").strip()
        if message:
            session["history"].append({"role": "user", "content": message})
            try:
                reply = ask_compas(message)
            except Exception as e:
                reply = f"⚠️ Error: {e}"
            session["history"].append({"role": "bot", "content": reply})
        return render_template("index.html", history=session["history"])

    return render_template("index.html", history=session.get("history", []))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)
