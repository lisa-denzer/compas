from flask import Flask, render_template, request, session
from openai import OpenAI
import os

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "temporary-key")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
PASSCODE = os.getenv("PASSCODE", "ayuda")

def ask_compas(message):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": "You are Compás, a calm relationship coach for Miguel and Lisa."},
                  {"role": "user", "content": message}]
    )
    return response.choices[0].message.content.strip()

@app.route("/", methods=["GET", "POST"])
def index():
    if "history" not in session:
        session["history"] = []

    if request.method == "POST":
        passcode = request.form.get("passcode", "")
        message = request.form.get("message", "").strip()

        if passcode != PASSCODE:
            return render_template("index.html", history=session["history"] + [{"role": "bot", "content": "❌ Wrong passcode."}])

        if message:
            session["history"].append({"role": "user", "content": message})
            reply = ask_compas(message)
            session["history"].append({"role": "bot", "content": reply})

        return render_template("index.html", history=session["history"])

    return render_template("index.html", history=session.get("history", []))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)
