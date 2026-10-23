"""Apply one visitor issue (a guess or a star) to the stage state.

Writes the reply comment to $REPLY_FILE so the workflow can post it.
"""
import os
import re

from common import (
    MAX_STARS,
    NUM_MAX,
    NUM_MIN,
    clean_message,
    fresh_game,
    load_state,
    now_kst,
    repo,
    save_state,
    target_for,
)

STAR_PLACEHOLDER = "이 줄을 지우고 별에 적을 한마디를 써주세요"


def handle_guess(state, user, n):
    game = state["game"]
    if not (NUM_MIN <= n <= NUM_MAX):
        return f"{NUM_MIN}~{NUM_MAX} 사이 숫자만 받아요."
    if not (game["lo"] <= n <= game["hi"]):
        return f"{n}은(는) 이미 범위 밖이에요. 지금 범위는 **{game['lo']} ~ {game['hi']}** 입니다."

    target = target_for(game["round"])
    if n == target:
        tries = len(game["guesses"]) + 1
        state["wins"][user] = state["wins"].get(user, 0) + 1
        state["last_winner"] = {"user": user, "n": n, "round": game["round"], "tries": tries}
        state["game"] = fresh_game(game["round"] + 1)
        return f"🎉 정답! **{n}** 맞아요. 라운드 {game['round']}은(는) {tries}번 만에 끝났어요. 새 라운드가 시작됐습니다."

    hint = "UP" if target > n else "DOWN"
    if hint == "UP":
        game["lo"] = n + 1
    else:
        game["hi"] = n - 1
    game["guesses"].append({"user": user, "n": n, "hint": hint})
    arrow = "⬆️ UP" if hint == "UP" else "⬇️ DOWN"
    return f"**{n}** → {arrow}! 범위가 **{game['lo']} ~ {game['hi']}** 로 좁혀졌어요."


def handle_star(state, user, body):
    msg = clean_message(body.replace(STAR_PLACEHOLDER, ""))
    if not msg:
        msg = "✨"
    stamp = now_kst().strftime("%Y-%m-%d %H:%M")
    state["stars"].append({"user": user, "msg": msg, "at": stamp})
    state["stars"] = state["stars"][-MAX_STARS:]
    return "⭐ 별을 무대에 걸었어요. 밤(KST 19시~)이 되면 하늘에서 흔들리고 있을 거예요."


def main():
    title = os.environ["ISSUE_TITLE"].strip()
    user = os.environ["ISSUE_USER"]
    body = os.environ.get("ISSUE_BODY", "")
    state = load_state()

    m = re.fullmatch(r"guess:\s*(\d{1,3})", title)
    if m:
        reply = handle_guess(state, user, int(m.group(1)))
    elif title == "star":
        reply = handle_star(state, user, body)
    else:
        return

    save_state(state)
    with open(os.environ.get("REPLY_FILE", "reply.md"), "w", encoding="utf-8") as f:
        f.write(f"@{user} {reply}\n\n[무대로 돌아가기](https://github.com/{repo().split('/')[0]})\n")


if __name__ == "__main__":
    main()
