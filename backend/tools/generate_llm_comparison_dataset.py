"""Generate the deterministic 1,000-comment V4-versus-V5 comparison fixture."""

import csv
import random
from pathlib import Path

TOPICS = [
    ("microphone audio", "what microphone are you using today"),
    ("mechanical keyboard", "what keyboard and switches are you using"),
    ("stream lighting", "what lights are you using for the stream"),
    ("webcam camera", "what camera are you using right now"),
    ("gaming chair", "what chair do you use for long streams"),
    ("monitor display", "what monitor do you use for gaming"),
    ("internet upload", "what upload speed do you stream with"),
    ("stream bitrate", "what bitrate are you streaming at today"),
    ("obs scenes", "how do you organize all your OBS scenes"),
    ("audio interface", "what audio interface is your microphone plugged into"),
    ("headphone headset", "what headphones are you wearing on stream"),
    ("desk setup", "how did you set up your streaming desk"),
    ("background decoration", "where did you get the decorations behind you"),
    ("stream schedule", "what days do you normally go live"),
    ("game choice", "why did you pick this game today"),
    ("difficulty setting", "what difficulty are you playing this on"),
    ("character build", "what character build are you going for"),
    ("weapon loadout", "what weapons are you running for this build"),
    ("boss strategy", "how are you planning to beat this boss"),
    ("map route", "which route are you taking through this map"),
    ("controller settings", "what controller settings are you using here"),
    ("mouse sensitivity", "what mouse sensitivity do you play on"),
    ("graphics settings", "what graphics settings are you playing with"),
    ("computer hardware", "what computer upgrade helped your stream most"),
    ("graphics card", "what graphics card is in your computer"),
    ("computer processor", "what processor are you gaming and streaming on"),
    ("memory capacity", "how much memory does your streaming computer have"),
    ("storage drive", "what drive do you save your recordings on"),
    ("cooling system", "how do you keep your computer cool while streaming"),
    ("stream overlay", "did you make this stream overlay yourself"),
    ("alert sounds", "where did you get your stream alert sounds"),
    ("channel emotes", "who made the emotes for your channel"),
    ("moderation rules", "what chat rules do your moderators usually enforce"),
    ("community discord", "how do we join your discord server"),
    ("viewer games", "when are you doing viewer games again"),
    ("stream highlights", "where do you post your stream highlights"),
    ("video editing", "what do you use to edit your videos"),
    ("music playlist", "what playlist is playing in the background"),
    ("copyright music", "where do you find music that is safe to stream"),
    ("snack choice", "what snacks do you eat during long streams"),
    ("drink choice", "what are you drinking on stream today"),
    ("break timing", "how often do you take breaks while streaming"),
    ("voice warmup", "do you warm up your voice before streaming"),
    ("stream goals", "what goals are you working toward this month"),
    ("channel growth", "what helped your channel grow the most"),
    ("new streamer", "what advice would you give a new streamer"),
    ("collaboration plans", "are you planning any streams with other creators"),
    ("tournament plans", "are you entering any tournaments for this game"),
    ("charity stream", "when are you doing another charity stream"),
    ("next game", "what game are you playing after this one"),
]


VALID_TEMPLATES = [
    "{comment}?",
    "hey {comment}?",
    "wait {comment}?",
    "yo {comment}?",
    "{comment} btw?",
    "did you already say {comment}?",
    "random question but {comment}?",
    "chat keeps asking {comment}?",
    "quick question for you: {comment}?",
    "i missed it earlier, {comment}?",
    "been wondering all stream, {comment}?",
    "before you move on, {comment}?",
    "if you have time later, quick question: {comment}?",
    "not sure if someone asked already but {comment}?",
    "i have been trying to figure this out for myself, so i wanted to ask: {comment}?",
    "i have been watching for a while and i am genuinely curious: {comment}?",
]


EMOJI_ONLY = [
    "😂🔥", "❤️❤️❤️", "👏👏👏", "🎉🎉", "💀💀💀", "🤣🤣", "😍✨", "🙌🙌",
    "🔥🔥🔥🔥", "😮😮", "🥳🎊", "💯💯", "👀👀", "😭😭", "🚀🚀", "🤯🤯",
    "✅✅✅", "⭐🌟", "🎮🎮", "🏆🏆",
]


SHORT_OR_NOISE = [
    "pog", "lol", "lmao", "lel", "rofl", "nice", "wow", "so good", "great play",
    "hello chat", "gg everyone", "that was wild", "very cool stream", "love this game",
    "asdfgh qwrty zxcvb", "qweoiu asdjk zmxn", "blargh snorf glibble", "zzxxcc vvbbnn",
    "12345 67890", "!!! ??? ...",
]


def build_rows() -> list[tuple[str, bool]]:
    valid = [
        (template.format(comment=comment), True)
        for _, comment in TOPICS
        for template in VALID_TEMPLATES
    ]
    invalid = []
    for index in range(100):
        invalid.append((EMOJI_ONLY[index % len(EMOJI_ONLY)], False))
    for index in range(100):
        invalid.append((SHORT_OR_NOISE[index % len(SHORT_OR_NOISE)], False))

    assert len(valid) == 800
    assert len(invalid) == 200
    rows = [*valid, *invalid]
    random.Random(20260808).shuffle(rows)
    return rows


def main() -> None:
    output = Path(__file__).resolve().parents[2] / "docs" / "LLM_COMPARISON_DATASET_1000.csv"
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "comment", "validity"])
        for index, (comment, validity) in enumerate(build_rows(), start=1):
            writer.writerow([f"comment-{index:04d}", comment, validity])
    print(output)


if __name__ == "__main__":
    main()
