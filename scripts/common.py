"""Shared state + helpers for the profile stage."""
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "state.json"
KST = timezone(timedelta(hours=9))

DAY_START, NIGHT_START = 7, 19  # KST hours
NUM_MIN, NUM_MAX = 1, 100
MAX_STARS = 30


def now_kst():
    return datetime.now(KST)


def mode():
    forced = os.environ.get("STAGE_MODE")
    if forced in ("day", "night"):
        return forced
    return "day" if DAY_START <= now_kst().hour < NIGHT_START else "night"


def repo():
    # Set automatically inside GitHub Actions ("owner/repo").
    return os.environ.get("GITHUB_REPOSITORY", "YOUR_ID/YOUR_ID")


def fresh_game(round_no=1):
    return {"round": round_no, "lo": NUM_MIN, "hi": NUM_MAX, "guesses": []}


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"game": fresh_game(), "last_winner": None, "wins": {}, "stars": []}


def save_state(state):
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def target_for(round_no):
    # The answer is derived from a repo secret so it never appears in the public repo.
    salt = os.environ.get("STAGE_SALT", "")
    if not salt:
        raise SystemExit("STAGE_SALT secret is missing")
    digest = hashlib.sha256(f"{salt}:{round_no}".encode()).hexdigest()
    return int(digest, 16) % (NUM_MAX - NUM_MIN + 1) + NUM_MIN


def seeded(*parts):
    """Deterministic float in [0, 1) from arbitrary parts."""
    h = hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest()
    return int(h[:12], 16) / 16**12


def clean_message(text, limit=60):
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]
