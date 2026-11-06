"""English name, username, and password choices for one Snapchat run."""

from __future__ import annotations

import random

FIRST_NAMES = (
    "Emma", "Liam", "Olivia", "Noah", "Ava", "Mason", "Sophia", "Lucas",
    "Mia", "Ethan", "Amelia", "James", "Harper", "Benjamin", "Evelyn", "Henry",
)
LAST_NAMES = (
    "Walker", "Brooks", "Hayes", "Bennett", "Cooper", "Foster", "Reed", "Perry",
    "Powell", "Long", "Hughes", "Ward", "Price", "Russell", "Griffin", "Coleman",
)
NICK_WORDS = (
    "river", "maple", "cloud", "amber", "cedar", "pearl", "silver", "willow",
    "harbor", "meadow", "comet", "linen", "quartz", "birch", "coral", "flint",
)
CITIES = ("Lisbon", "Dublin", "Prague", "Athens", "Vienna", "Oslo", "Bergen", "Cork")
SYMBOLS = "!@#$%*"
USERNAME_PATTERNS = (
    "first_last",
    "last",
    "first_digits",
    "first_initial",
    "last_initial",
    "two_words",
    "one_word",
)
PASSWORD_PATTERNS = (
    "word_digits",
    "city_digits",
    "other_name_digits",
    "two_words_digit",
    "word_symbol_digits",
    "mixed",
)


def make_plan(rng: random.Random | None = None) -> dict:
    rng = rng or random.Random()
    first = rng.choice(FIRST_NAMES)
    last = rng.choice(LAST_NAMES)
    others = [
        name for name in FIRST_NAMES
        if name != first
        and first.lower() not in name.lower()
        and name.lower() not in first.lower()
        and last.lower() not in name.lower()
    ]
    pattern = rng.choice(USERNAME_PATTERNS)
    password_pattern = rng.choice(PASSWORD_PATTERNS)
    person = {
        "first": first,
        "last": last,
        "year": rng.randint(1970, 2006),
        "month_scrolls": rng.randint(1, 2),
        "month_direction": rng.choice(("up", "down")),
        "day_scrolls": rng.randint(1, 2),
        "day_direction": rng.choice(("up", "down")),
        "notifications": rng.choice(("allow", "deny")),
        "bitmoji": rng.choice(("skip", "pick")),
        "username_pattern": pattern,
        "password_pattern": password_pattern,
        "other_name": rng.choice(others),
    }
    person["username"] = username_for(pattern, person, rng)
    person["password"] = password_for(password_pattern, person, rng)
    person["username_tries"] = 1
    person["password_tries"] = 1
    return person


def username_for(pattern: str, person: dict, rng: random.Random, extra: str = "") -> str:
    first = person["first"].lower()
    last = person["last"].lower()
    if pattern == "first_last":
        base = first + rng.choice(("_", " ")) + last
    elif pattern == "last":
        base = last
    elif pattern == "first_digits":
        base = first + str(rng.randint(10, 99))
    elif pattern == "first_initial":
        base = first + last[0]
    elif pattern == "last_initial":
        base = last + first[0]
    elif pattern == "two_words":
        words = rng.sample(NICK_WORDS, 2)
        base = words[0] + words[1]
    elif pattern == "one_word":
        base = rng.choice(NICK_WORDS)
    else:
        raise ValueError(pattern)
    handle = (base + extra)[:15]
    if pattern in ("two_words", "one_word"):
        lowered = handle.lower()
        if first in lowered or last in lowered:
            raise ValueError("nickname contains the account name")
    return handle


def username_rejected(person: dict, rng: random.Random) -> str | None:
    if person["username_tries"] >= 10:
        return None
    person["username_tries"] += 1
    extra = ""
    if rng.random() < 0.5:
        person["username_pattern"] = rng.choice(USERNAME_PATTERNS)
    else:
        extra = str(rng.randint(10, 99))
    person["username"] = username_for(person["username_pattern"], person, rng, extra)
    person["password"] = password_for(person["password_pattern"], person, rng)
    return person["username"]


def password_for(pattern: str, person: dict, rng: random.Random) -> str:
    patterns = [pattern, *[item for item in PASSWORD_PATTERNS if item != pattern]]
    for candidate_pattern in patterns:
        for _ in range(20):
            candidate = _password_candidate(candidate_pattern, person, rng)
            if password_ok(candidate, person):
                return candidate
    raise RuntimeError("could not build a password for this account")


def password_rejected(person: dict, rng: random.Random) -> str | None:
    if person["password_tries"] >= 3:
        return None
    person["password_tries"] += 1
    remaining = [item for item in PASSWORD_PATTERNS if item != person["password_pattern"]]
    person["password_pattern"] = rng.choice(remaining or list(PASSWORD_PATTERNS))
    person["password"] = password_for(person["password_pattern"], person, rng)
    return person["password"]


def password_ok(password: str, person: dict, phone: str = "") -> bool:
    if not 8 <= len(password) <= 15:
        return False
    if not any(char.isupper() for char in password):
        return False
    if not any(char.islower() for char in password):
        return False
    if not any(char.isdigit() for char in password):
        return False
    lowered = password.lower()
    banned = (
        person["first"],
        person["last"],
        person.get("username") or "",
        phone,
        str(person["year"]),
    )
    return not any(part and part.lower() in lowered for part in banned)


def _password_candidate(pattern: str, person: dict, rng: random.Random) -> str:
    word = rng.choice(NICK_WORDS).capitalize()
    digits = str(rng.randint(10, 9999))
    if pattern == "word_digits":
        return (word + digits)[:15]
    if pattern == "city_digits":
        return (rng.choice(CITIES) + digits)[:15]
    if pattern == "other_name_digits":
        return (person["other_name"] + digits)[:15]
    if pattern == "two_words_digit":
        pair = "".join(part.capitalize() for part in rng.sample(NICK_WORDS, 2))
        return (pair + str(rng.randint(0, 9)))[:15]
    if pattern == "word_symbol_digits":
        return (word + rng.choice(SYMBOLS) + digits)[:15]
    mixed = "".join(rng.choice("abcdefghijkmnopqrstuvwxyz") for _ in range(4))
    return (mixed.capitalize() + rng.choice(SYMBOLS) + digits)[:15]
