import pytest

from codirector.core.chat_filter import ChatCommentFilter


def test_rejects_emoji_and_symbol_only_comments():
    chat_filter = ChatCommentFilter(min_recognized_words=1)

    assert chat_filter.evaluate("😂🔥💯").reason == "emoji_only"
    assert chat_filter.evaluate("!!! <3").reason == "emoji_only"


def test_rejects_unintelligible_words_without_rejecting_short_valid_chat():
    chat_filter = ChatCommentFilter(min_recognized_words=1)

    assert chat_filter.evaluate("asdfgh qwrty").reason == "unintelligible"
    assert chat_filter.evaluate("why?").accepted is True
    assert chat_filter.evaluate("gg").reason == "unintelligible"


def test_minimum_recognized_words_is_configurable():
    chat_filter = ChatCommentFilter(min_recognized_words=2)

    assert chat_filter.evaluate("hello xqz").reason == "unintelligible"
    assert chat_filter.evaluate("hello streamer").accepted is True


@pytest.mark.parametrize(
    "text",
    [
        "😂🔥",
        "hello",
        "hello friendly",
    ],
)
def test_default_rejects_fewer_than_three_recognized_words(text):
    chat_filter = ChatCommentFilter()

    assert chat_filter.evaluate(text).accepted is False


def test_default_accepts_three_recognized_words():
    assert ChatCommentFilter().evaluate("hello friendly streamer").accepted is True


def test_reaction_words_do_not_count_toward_recognized_word_minimum():
    chat_filter = ChatCommentFilter()

    result = chat_filter.evaluate("pog lol lmao lel rofl kekw poggers omegalul")
    assert result.reason == "unintelligible"
    assert result.recognized_word_count == 0

    mixed = chat_filter.evaluate("what microphone do you use pog lol")
    assert mixed.accepted is True
    assert mixed.recognized_word_count == 5


def test_twitch_and_extension_emote_names_do_not_count_as_words():
    chat_filter = ChatCommentFilter()

    emotes = chat_filter.evaluate("4Head Kappa PogChamp ResidentSleeper Jebaited catJAM PepeHands")
    assert emotes.reason == "emoji_only"
    assert emotes.recognized_word_count == 0

    mixed = chat_filter.evaluate("what microphone today Kappa PogChamp catJAM")
    assert mixed.accepted is True
    assert mixed.recognized_word_count == 3
