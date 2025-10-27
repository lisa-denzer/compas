
# Compás — calm, on‑your‑side coach

A tiny ChatGPT‑style web app to help Miguel handle conflicts, gestures, and planning with Lisa. Private, concise, behaviour‑focused. Learns from feedback.

## Local run
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # paste your OPENAI_API_KEY
python app.py
```
Open http://localhost:5000

## Render deploy
1) Create a Web Service from this folder/repo.
2) Environment:
   - `OPENAI_API_KEY=...`
   - `OPENAI_MODEL=gpt-4o-mini`
   - (optional) `PASSCODE=some-secret`
3) Start command: `python app.py`
4) Open the URL → Add to Home Screen.

## Endpoints
- `POST /chat` → `{ message, session_id }` → reply + suggestion IDs.
- `POST /feedback` → `{ suggestion_id, outcome: success|neutral|fail, notes? }`.
- `POST /suggest/gift` → personalised ideas.
- `POST /memory` → add/list/delete saved facts.

## Customise
- `data/lisa_profile.json` — preferences, values, soothing gestures.
- `data/memory.json` — saved notes.
- System prompt in `app.py` (`SYSTEM_PROMPT_TEMPLATE`).

## Privacy
- Stores only suggestions/feedback (SQLite at `db/compas.db`). Not full transcripts.
- Use `PASSCODE` header or `?passcode=` to restrict.
