import random, json
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
LOG_PATH = DATA_DIR / "reflection_log.json"

PROMPTS = {
    "emotion": [
        "How did you feel most of today — calm, tired, annoyed, or good? What caused it?",
        "Did anything make you smile today? Or tense up?",
        "Was there a moment you felt proud or frustrated? Why?"
    ],
    "lisa": [
        "How do you think Lisa felt today? What signs did you notice?",
        "Did you make her day easier or harder? One small thing that helped or hurt?",
        "What’s one thing she did today you can thank her for?"
    ],
    "action": [
        "If today wasn’t great, what could you do differently tomorrow?",
        "One thing you can do tonight or tomorrow to make her feel supported?",
        "Did you give any compliment or warmth today? If not, start with one before bed."
    ],
    "reset": [
        "No need to fix everything — what’s one good thing about today you want to keep?",
        "Even on hard days, what went right between you two?",
        "What’s one thing you can look forward to together this week?"
    ]
}

def random_reflection():
    return [
        random.choice(PROMPTS["emotion"]),
        random.choice(PROMPTS["lisa"]),
        random.choice(PROMPTS["action"]),
        random.choice(PROMPTS["reset"])
    ]

def random_connection_idea():
    with open(DATA_DIR / "connection_ideas.json", "r", encoding="utf-8") as f:
        ideas = json.load(f)
    # pick a random category then a random idea
    cat = random.choice(list(ideas.keys()))
    return random.choice(ideas[cat])

def random_kindness_exercise():
    with open(DATA_DIR / "kindness_exercises.json", "r", encoding="utf-8") as f:
        items = json.load(f)["starters"]
    return random.choice(items)

def save_reflection_response(user_id, answers):
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "user": user_id,
        "answers": answers
    }
    try:
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            log = json.load(f)
    except FileNotFoundError:
        log = []
    log.append(entry)
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
