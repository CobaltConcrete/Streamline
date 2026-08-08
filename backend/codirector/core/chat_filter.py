"""Cheap deterministic filtering before chat consumes batch capacity."""

import re
from dataclasses import dataclass, field
from typing import Literal

from spellchecker import SpellChecker

_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_CHAT_WORDS = {
    "afk",
    "brb",
    "mic",
    "obs",
    "tbh",
    "twitch",
}
_TWITCH_EMOTES = {
    "4head", "anele", "ambessalove", "anotherrecord", "argieb8", "arsonnosexy",
    "asexualpride", "asianglow", "bcwarrior", "bop", "babyrage", "batchest",
    "begwan", "bigbrother", "bigphish", "bigsad", "bisexualpride",
    "blacklivesmatter", "blargnaut", "bloodtrail", "brainslug", "bratchat",
    "brokeback", "buddhabar", "caitthinking", "carlsmile", "cheffrank",
    "cinheimer", "coolcat", "coolstorybob", "corgiderp", "crreamawk", "curselit",
    "daesuppy", "dbstyle", "dansgame", "darkmode", "datsheffy", "dendiface",
    "dinodance", "dogface", "doritoschip", "dxcat", "ewccrush", "earthday",
    "ekkochest", "elegiggle", "entropywins", "extralife", "fbblock", "fbcatch",
    "fbchallenge", "fbpass", "fbpenalty", "fbrun", "fbspiral", "fbtouchdown",
    "fungineer", "failfish", "feelsvi", "feverfighter", "football", "footgoal",
    "footyellow", "frankerz", "freakinstinkin", "futureman", "grasslord",
    "gaypride", "genderfluidpride", "gingerpower", "giveplz", "glitchcat",
    "glitchlit", "glitchnrg", "goatemotey", "goldplz", "grammarking", "hscheers",
    "hswp", "hassaanchop", "heyguys", "holidaycookie", "holidaylog",
    "holidaypresent", "holidaysanta", "holidaytree", "hotpokket", "imtyping",
    "intersexpride", "inuyoface", "itsboshytime", "jkanstyle", "jebaited",
    "jebasted", "jinxlul", "joncarnage", "kapow", "kappa", "kappaclaus",
    "kappapride", "kappaross", "kappawealth", "kappu", "keepo", "kevinturtle",
    "kippa", "komodohype", "koncha", "kreygasm", "lul", "laundrybasket",
    "lesbianpride", "mvgame", "mau5", "maxlol", "mercywing1", "mercywing2",
    "mikehogu", "minglee", "modlove", "morphintime", "mrdestructoid", "myavatar",
    "newrecord", "ninjagrumpy", "nomnom", "nonbinarypride", "notatk",
    "notlikethis", "osfrog", "ohmydog", "onehand", "opieop", "optimizeprime",
    "pjsalt", "pjsugar", "pmstwin", "prchase", "panicvis", "pansexualpride",
    "partyhat", "partytime", "peopleschamp", "permasmug", "pewpewpew",
    "picomause", "pinkmercy", "pipehype", "pixelbob", "pizzatime", "pogchamp",
    "poooound", "popcorn", "popnemo", "powerupl", "powerupr", "praiseit",
    "primeme", "punoko", "punchtrees", "raccattack", "ralpherz", "redcoat",
    "residentsleeper", "ritzmitz", "rlytho", "rulefive", "smorc", "ssssss",
    "subprise", "subtember", "sabaping", "seemsgood", "serioussloth", "shadylulu",
    "shazbotstix", "shush", "singsmic", "singsnote", "siptime", "smoocherz",
    "sobayed", "soonerlater", "spideythwip", "squid1", "squid2", "squid3",
    "squid4", "stinkycheese", "stinkyglitch", "stonelightning", "strawbeary",
    "streameru2026", "supervinlin", "swiftrage", "tbangel", "tf2john", "tpfufun",
    "tpcrunchyroll", "ttours", "twith", "takenrg", "tearglove", "tehepelo",
    "thankegg", "theilluminati", "theringer", "thetarfu", "thething", "thunbeast",
    "tinyface", "tombraid", "toospicy", "transgenderpride", "trihard",
    "twitchconhype", "twitchlit", "twitchrpg", "twitchsings", "twitchunity",
    "twitchvotes", "uwot", "unsane", "unclenox", "virtualhug", "vohiyo",
    "votenay", "voteyea", "wtruck", "wedidthat", "wholewheat", "wutface", "yagoo",
    "youdontsay", "youwhy", "bleedpurple", "cmonbruh", "copythis", "dududu",
    "imglitch", "mcat", "panicbasket", "pastathat", "ripepperonis", "twitchraid",
    # Common BTTV/FFZ/7TV-style emotes.
    "5head", "ayaya", "catjam", "clueless", "copium", "gachibass", "gigachad",
    "hypers", "kekw", "monka", "monkas", "omegalul", "pausechamp", "peped",
    "pepehands", "pepejam", "pepelaugh", "peepoclap", "peepohappy", "peepopog",
    "pogu", "poggers", "sadge", "weirdchamp", "widepeepohappy",
}
_NON_CONTENT_REACTIONS = {
    "ez",
    "gg",
    "haha",
    "hehe",
    "kappa",
    "kekw",
    "lel",
    "lmao",
    "lol",
    "lul",
    "monka",
    "monkas",
    "omegalul",
    "pog",
    "pogchamp",
    "poggers",
    "rofl",
}

FilterReason = Literal["emoji_only", "unintelligible"]


@dataclass(frozen=True)
class FilterResult:
    accepted: bool
    reason: FilterReason | None = None
    recognized_word_count: int = 0


@dataclass
class ChatCommentFilter:
    """Reject emoji/symbol-only and insufficiently intelligible comments."""

    min_recognized_words: int = 3
    _spellchecker: SpellChecker = field(default_factory=SpellChecker, repr=False)

    def __post_init__(self) -> None:
        if self.min_recognized_words < 1:
            raise ValueError("min_recognized_words must be at least 1")
        self._spellchecker.word_frequency.load_words(_CHAT_WORDS)

    def evaluate(self, text: str) -> FilterResult:
        without_emotes = " ".join(
            token
            for token in text.split()
            if token.strip(".,!?;:()[]{}").casefold() not in _TWITCH_EMOTES
        )
        words = [match.group(0).lower() for match in _WORD_RE.finditer(without_emotes)]
        if not words:
            return FilterResult(False, "emoji_only")

        content_words = [word for word in words if word not in _NON_CONTENT_REACTIONS]
        known_words = self._spellchecker.known(content_words)
        recognized = sum(word in known_words for word in content_words)
        if recognized < self.min_recognized_words:
            return FilterResult(False, "unintelligible", recognized)
        return FilterResult(True, recognized_word_count=recognized)
