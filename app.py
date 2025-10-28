from flask import Flask, render_template, request, session, redirect, url_for
from openai import OpenAI
import os

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "temporary-key")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
PASSCODE = os.getenv("PASSCODE", "ayuda")


def ask_compas(message):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are Compás, a calm relationship coach for Miguel and Lisa."},
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
