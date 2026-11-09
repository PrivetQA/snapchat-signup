"""Play sign-in and Snapchat signup with the on-screen hand.

No keyevent, no input swipe, no monkey. No input text, except the Play
password: key taps on that page missed the masked length. One input text
into the focused field. Do not type the password key by key.
Play is opened by the market link, which the hand skill allows for that passage.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import shlex
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
if os.environ.get("TELEPHORT_SDK"):
    sys.path.insert(0, os.environ["TELEPHORT_SDK"])
else:
    for parent in (ROOT, *ROOT.parents):
        candidate = parent / "sdk" / "python"
        if (candidate / "telephort_sdk").is_dir():
            sys.path.insert(0, str(candidate))
            break

def load_local() -> dict:
    path = ROOT / "data" / "local.json"
    if path.exists():
        return json.loads(path.read_text())
    return {}


from decisions import is_snapchat_signup, play_decision, snap_decision
from fivesim import FiveSim, prepared_countries
from identity import make_plan, password_for, password_ok, password_rejected, username_for, username_rejected
from register import (
    _bullet_length,
    _edit_text,
    _edit_texts,
    _field_length,
    _find,
    _play_nodes,
    _point,
    _safe_label,
    _screen_size,
    _texts,
    _totp,
)
from store import upsert_account, write_run
from telephort_sdk import TelephortClient

_read_nodes = _play_nodes
ACTIVE: dict = {"hand": None}

DEVICE = os.environ.get("SNAP_DEVICE", "")
SNAP = "com.snapchat.android"
RUNS = ROOT / "data" / "runs"
TIMING = Path(f"/tmp/snap-timing-{DEVICE or 'run'}.json")


class RunClock:
    def __init__(self) -> None:
        self.started = time.perf_counter()
        self.last = self.started
        self.rows: list[dict] = []

    def mark(self, phase: str, detail: str = "") -> None:
        now = time.perf_counter()
        detail = re.sub(r"\S+@\S+", "[mail]", detail)
        detail = re.sub(r"\+?\d[\d\-]{6,}", "[number]", detail)[:160]
        row = {
            "t": round(now - self.started, 3),
            "step": round(now - self.last, 3),
            "phase": phase,
            "detail": detail,
        }
        self.last = now
        self.rows.append(row)
        print(f"timing {row['t']:.1f}s +{row['step']:.1f}s {phase} {detail}".rstrip(), flush=True)
        TIMING.write_text(json.dumps(self.rows, ensure_ascii=False, indent=2))


CLOCK = RunClock()
NOTES: list[dict] = []


def note_problem(where: str, what: str, fix: str) -> None:
    NOTES.append({"where": where, "what": what, "fix": fix})
    print("problem", where, what, flush=True)


def finish_report(stopped: str = "") -> None:
    parts: list[dict] = []
    for row in CLOCK.rows:
        if parts and parts[-1]["phase"] == row["phase"]:
            parts[-1]["sec"] = round(row["t"] - parts[-1]["start"], 1)
            continue
        if parts:
            parts[-1]["sec"] = round(row["t"] - parts[-1]["start"], 1)
        parts.append({"phase": row["phase"], "start": row["t"], "sec": 0.0})
    if parts:
        parts[-1]["sec"] = round(CLOCK.rows[-1]["t"] - parts[-1]["start"], 1)
    print("timing parts", flush=True)
    for part in parts:
        print(f"  {part['phase']} {part['sec']:.1f}s", flush=True)
    total = CLOCK.rows[-1]["t"] if CLOCK.rows else 0
    print(f"  total {total:.1f}s", flush=True)
    print("problems", len(NOTES), flush=True)
    if not NOTES and not stopped:
        print("по ходу скрипта проблем не было", flush=True)
    for item in NOTES:
        print(f"- {item['where']}: {item['what']}", flush=True)
        print(f"  как решить: {item['fix']}", flush=True)
    if stopped:
        print(f"- stop: {stopped}", flush=True)
        print("  как решить: смотреть stop screenshot и поправить только этот шаг", flush=True)
    if NOTES or stopped:
        print(
            "правь только упавший шаг, проверь его один раз и покажи, что изменилось. В репозиторий отправляй только после согласия.",
            flush=True,
        )
    report = Path(f"/tmp/snap-chats/report-{DEVICE or 'run'}.json")
    report.parent.mkdir(exist_ok=True)
    report.write_text(json.dumps({
        "device_id": DEVICE,
        "total_sec": total,
        "parts": [{key: value for key, value in part.items() if key != "start"} for part in parts],
        "problems": NOTES,
        "stopped": stopped,
    }, ensure_ascii=False, indent=2) + "\n")
    print("report", report, flush=True)

LETTERS = {
    "q": (29, 852), "w": (82, 852), "e": (135, 852), "r": (188, 852), "t": (241, 852),
    "y": (294, 852), "u": (347, 852), "i": (401, 852), "o": (455, 852), "p": (509, 852),
    "a": (56, 928), "s": (109, 928), "d": (162, 928), "f": (215, 928), "g": (268, 928),
    "h": (321, 928), "j": (374, 928), "k": (428, 928), "l": (482, 928),
    "z": (109, 1004), "x": (162, 1004), "c": (215, 1004), "v": (268, 1004),
    "b": (321, 1004), "n": (374, 1004), "m": (428, 1004),
}
DIGITS = {
    "1": (29, 852), "2": (82, 852), "3": (135, 852), "4": (188, 852), "5": (241, 852),
    "6": (294, 852), "7": (347, 852), "8": (401, 852), "9": (455, 852), "0": (509, 852),
}
EXTRA = {" ": (295, 1084), ",": (109, 1084), ".": (429, 1084)}
SHIFT = (42, 1004)
BACKSPACE = (496, 1004)
SYMBOL = (40, 1080)
CHECK = (496, 1084)
# Phone pad on this 540x1200 device, measured while the code field was focused.
# It is not the letter-keyboard digit row.
PAD = {
    "1": (69, 856), "2": (202, 856), "3": (335, 856),
    "4": (69, 932), "5": (202, 932), "6": (335, 932),
    "7": (69, 1008), "8": (202, 1008), "9": (335, 1008),
    "0": (202, 1084),
}
PAD_DELETE = (470, 1008)


def next_run() -> int:
    numbers = [int(path.stem.split("-")[1]) for path in RUNS.glob("run-*.json")]
    return (max(numbers) if numbers else 0) + 1


def write_account(record: dict, plan: dict) -> None:
    if os.environ.get("SNAP_RESUME") == "1":
        return
    account = {
        "run_number": record["run_number"],
        "device_id": record.get("device_id") or "",
        "name": f"{plan['first']} {plan['last']}",
        "username": plan.get("username") or "",
        "password": plan.get("password") or "",
        "birthday": plan.get("birthday") or "",
        "birthday_year": plan.get("birthday_year") or plan.get("year"),
        "phone": plan.get("phone") or "",
        "phone_country": plan.get("phone_country") or "",
        "phone_on_screen": plan.get("phone_on_screen") or "",
        "email": plan.get("email") or "",
        "status": plan.get("account_status") or "planned",
        "registered_on": time.strftime("%Y-%m-%d"),
    }
    path = upsert_account(account)
    print("account file", path, account["status"], flush=True)


def _first_diff(shown: str, expected: str) -> int:
    limit = min(len(shown), len(expected))
    for index in range(limit):
        if shown[index] != expected[index]:
            return index
    return limit


class Hand:
    def __init__(self, session, screen, rng: random.Random):
        self.session = session
        self.screen = screen
        self.rng = rng
        self.page = "letters"
        self.last_label = ""
        self.last_screen = ""
        self.last_label_at = 0.0
        self.install_tapped = False
        self.dismissed_keyboard = False
        self.open_taps = 0
        self.phone_backs = 0
        self.number_changes = 0
        self.restarts = 0
        self.last_wheel = None

    def place(self, cx: int, cy: int) -> tuple[int, int]:
        width, height = self.screen
        sx = round(cx * width / 540)
        sy = round(cy * height / 1200)
        key_w = max(8, round(47 * width / 540))
        key_h = max(8, round(60 * height / 1200))
        left = sx - key_w // 2
        top = sy - key_h // 2
        right = left + key_w
        bottom = min(top + key_h, height - 90)
        if right <= left or bottom <= top:
            return sx, sy
        return left + self.rng.randrange(right - left), top + self.rng.randrange(bottom - top)

    def key_bounds(self, cx: int, cy: int) -> dict:
        width, height = self.screen
        sx = round(cx * width / 540)
        sy = round(cy * height / 1200)
        key_w = max(8, round(47 * width / 540))
        key_h = max(8, round(60 * height / 1200))
        left = sx - key_w // 2
        top = sy - key_h // 2
        right = left + key_w
        # The bottom row sits on the navigation bar. Stay on the key, above that bar.
        bottom = min(top + key_h, height - 108)
        return {"left": left, "top": top, "right": right, "bottom": bottom}

    async def touch(self, x: int, y: int, down: int) -> None:
        payload = json.dumps({
            "type": "multi-touch",
            "id": [1],
            "x": [int(x)],
            "y": [int(y)],
            "down": down,
            "device_label": "display_0",
        })
        await self.session.send_data_channel("input-channel", payload)

    def _stay(self, x: int, y: int, bounds) -> tuple[int, int]:
        if not bounds:
            width, height = self.screen
            return max(0, min(width - 1, x)), max(0, min(height - 100, y))
        left, right = bounds["left"], max(bounds["left"], bounds["right"] - 1)
        top, bottom = bounds["top"], max(bounds["top"], bounds["bottom"] - 1)
        return max(left, min(right, x)), max(top, min(bottom, y))

    async def tap_xy(self, x: int, y: int, bounds=None, kind: str = "button") -> None:
        # The host message is only x, y, and down. A press is that finger held
        # down, shifted a few pixels, then lifted. There is no ellipse to send.
        # A longer hold on Gboard opens the alternate-character popup.
        low, high = (48, 78) if kind == "key" else (55, 110)
        hold = self.rng.randint(low, high) / 1000
        await self.touch(x, y, 1)
        await asyncio.sleep(hold * self.rng.uniform(0.4, 0.7))
        # A slide on a key makes Gboard insert the next letter. Keys stay put.
        # A button can creep a couple of pixels and still hit the same control.
        landed = (x, y)
        if kind != "key" and bounds:
            landed = self._stay(
                x + self.rng.choice((-1, 1)) * (1 + self.rng.randrange(3)),
                y + self.rng.choice((-1, 1)) * (1 + self.rng.randrange(2)),
                bounds,
            )
            await self.touch(landed[0], landed[1], 1)
            await asyncio.sleep(hold * self.rng.uniform(0.25, 0.5))
        else:
            await asyncio.sleep(hold * self.rng.uniform(0.25, 0.5))
        await self.touch(landed[0], landed[1], 0)

    def same_press(self, label: str, screen: str = "") -> bool:
        # A permission choice that is still on screen was a miss. Another point can hit it.
        if label in ("Allow", "Don't allow", "Deny", "Not now", "Not allowed", "Allowed", "Skip", "Yes, it's me"):
            return False
        if label == "Install" and self.install_tapped:
            return True
        if screen:
            # A button that is still here after a few seconds was a miss. Another point can hit it.
            if label == self.last_label and screen == self.last_screen:
                return time.time() - self.last_label_at < 8
            return False
        return label == self.last_label and time.time() - self.last_label_at < 25

    def remember(self, label: str, screen: str = "") -> None:
        self.last_label = label
        self.last_screen = screen
        self.last_label_at = time.time()

    async def between(self, kind: str) -> None:
        low, high = {
            "key": (0.22, 0.52),
            "modifier": (0.28, 0.75),
            "submit": (0.45, 1.15),
            "dialog": (1.1, 3.6),
            "action": (0.7, 2.6),
        }[kind]
        await asyncio.sleep(self.rng.uniform(low, high))

    async def tap_key(self, cx: int, cy: int) -> None:
        bounds = self.key_bounds(cx, cy)
        x, y = _point(bounds, self.screen)
        await self.tap_xy(x, y, bounds, kind="key")

    async def tap_node(self, node) -> None:
        bounds = node["bounds"]
        x, y = _point(bounds, self.screen)
        await self.tap_xy(x, y, bounds, kind="button")

    async def keyboard_open(self) -> bool:
        raw = await self.session.adb_shell("dumpsys input_method | grep mInputShown", timeout=15)
        return "mInputShown=true" in raw

    async def show_keyboard(self, field) -> None:
        if await self.keyboard_open():
            return
        if not field or not field.get("bounds"):
            raise RuntimeError("keyboard is closed and the field has no rectangle")
        print("keyboard closed, one tap inside the field", flush=True)
        await self.tap_node(field)
        if await self.keyboard_open():
            return
        print("field tap missed, another point in the same rectangle", flush=True)
        await self.tap_node(field)
        if not await self.keyboard_open():
            raise RuntimeError("field tap did not open the keyboard")

    async def letters(self) -> None:
        if self.page != "letters":
            await self.between("modifier")
            await self.tap_key(*SYMBOL)
            await self.between("key")
            self.page = "letters"

    async def symbols(self) -> None:
        if self.page != "symbols":
            await self.between("modifier")
            await self.tap_key(*SYMBOL)
            await self.between("key")
            self.page = "symbols"

    async def shift_held(self) -> bool:
        # Outline arrow: the center is the light key. Filled arrow: the center is dark.
        # Tapping Shift while it is already filled turns the capital off.
        await self.session.adb_shell("screencap /sdcard/kb.raw", timeout=25)
        header = await self.session.adb_shell("od -An -tu4 -N 12 /sdcard/kb.raw", timeout=15)
        parts = [int(item) for item in header.split()[:2]]
        width = parts[0] if parts else self.screen[0]
        height = parts[1] if len(parts) > 1 else self.screen[1]
        x = round(42 * width / 540)
        y = round(1004 * height / 1200)
        for header_size in (12, 16):
            offset = header_size + (y * width + x) * 4
            sample = await self.session.adb_shell(
                f"od -An -tu1 -N 4 -j {offset} /sdcard/kb.raw",
                timeout=15,
            )
            nums = [int(item) for item in sample.split()]
            if len(nums) < 3:
                continue
            red, green, blue = nums[0], nums[1], nums[2]
            return (red + green + blue) / 3 < 90
        return False

    async def type_char(self, char: str, hold_shift: bool = True) -> None:
        if char.isalpha():
            await self.letters()
            # A name field sometimes already holds Shift. Tapping it then
            # turns the capital off, so look at the arrow and tap only when it is off.
            if char.isupper():
                # hold_shift is false when the field already keeps the capital,
                # including the first letter and the letter after a space.
                if not hold_shift or await self.shift_held():
                    print("shift already on, not tapping it", flush=True)
                else:
                    print("shift is off, tapping it", flush=True)
                    await self.between("modifier")
                    await self.tap_key(*SHIFT)
                    await self.between("key")
            await self.tap_key(*LETTERS[char.lower()])
            await self.between("key")
            return
        if char.isdigit():
            if self.page == "pad":
                await self.tap_key(*PAD[char])
                await self.between("key")
                return
            await self.symbols()
            await self.tap_key(*DIGITS[char])
            await self.between("key")
            return
        if char in EXTRA:
            await self.letters()
            await self.tap_key(*EXTRA[char])
            await self.between("key")
            return
        if char == "@":
            await self.symbols()
            # Measured on this keyboard: @ is the first key of the symbol row, in line with 1.
            await self.tap_key(29, 928)
            await self.between("key")
            return
        raise RuntimeError(f"no measured key for this character class")

    async def type_text(self, value: str, auto_cap: bool = False, previous: str = "") -> None:
        source = previous + value
        start = len(previous)
        for offset, char in enumerate(value):
            index = start + offset
            skip_shift = (
                auto_cap
                and char.isupper()
                and (index == 0 or source[index - 1] == " ")
            )
            await self.type_char(char, hold_shift=not skip_shift)

    async def _field_nodes(self):
        return await _play_nodes(self.session)

    async def type_landed(self, value: str, secret: bool = False, auto_cap: bool = False) -> None:
        # Type every character, then read once. If one key missed, retype only
        # the tail. A read after every letter is what made the address slow.
        await self.type_text(value, auto_cap=auto_cap)
        if secret:
            return
        shown = await self._shown()
        if shown == value:
            return
        if shown in ("", "Email or phone", "First and Last name", "Username"):
            await asyncio.sleep(0.45)
            shown = await self._shown()
        if shown == value:
            return
        if not shown or shown in ("Email or phone", "First and Last name", "Username"):
            print("field empty after typing, typing once more", flush=True)
            note_problem("text", "поле осталось пустым после набора", "набирать ещё раз только если поле пустое, не добавлять символы поверх")
            await self.type_text(value, auto_cap=auto_cap)
            return
        extra = len(shown) - len(value)
        if shown.startswith(value) and 0 < extra <= 16:
            print("removing the suggestion after the text", extra, flush=True)
            await self.backspaces(extra)
            return
        await self._rewrite_tail(shown, value, auto_cap)

    async def _rewrite_tail(self, shown: str, value: str, auto_cap: bool) -> None:
        # One tail, then one read. A second rewrite is what made the field longer.
        index = _first_diff(shown, value)
        print("repair from", index, "len", len(shown), "expected", len(value), flush=True)
        await self.backspaces(max(0, len(shown) - index))
        if index == 0:
            left = await self._shown()
            if left and left not in ("", "Email or phone", "First and Last name", "Username"):
                print("clear left", len(left), flush=True)
                await self.backspaces(len(left))
        await self.type_text(value[index:], auto_cap=auto_cap, previous=value[:index])
        checked = await self._shown()
        if checked != value:
            print("tail still differs", "len", len(checked), "expected", len(value), flush=True)

    async def _shown(self) -> str:
        return field_text(await self._field_nodes())

    async def type_pin(self, value: str) -> None:
        # The keys on the screen are the phone pad. Do not switch to ?123.
        for char in value:
            if char not in PAD:
                raise RuntimeError("pin has a character that is not on the phone pad")
            await self.tap_key(*PAD[char])
            await self.between("key")

    async def burst_delete(self, count: int, point: tuple[int, int]) -> None:
        # One press per digit, then the caller reads the field once.
        for _ in range(count):
            await self.tap_xy(point[0], point[1], kind="key")
            await self.between("key")

    async def hold_delete(self, count: int, point: tuple[int, int]) -> None:
        # The finger stays on the phone delete key so the rest of the digits repeat off.
        # It does not slide. A letter key must not use this hold.
        await self.touch(point[0], point[1], 1)
        await asyncio.sleep(min(2.8, 0.45 + count * 0.08))
        await self.touch(point[0], point[1], 0)
        await self.between("key")

    async def pad_delete(self, count: int) -> None:
        for _ in range(count):
            await self.tap_key(*PAD_DELETE)

    async def backspaces(self, count: int) -> None:
        for _ in range(count):
            if self.page == "pad":
                await self.tap_key(*PAD_DELETE)
            else:
                await self.tap_key(*BACKSPACE)
            await self.between("key")

    async def see_pad(self) -> bool:
        # The phone pad's right column is light blue. One pixel is not enough:
        # a blue button at the same height used to count as the pad.
        await self.session.adb_shell("screencap /sdcard/kb.raw", timeout=25)
        header = await self.session.adb_shell("od -An -tu4 -N 12 /sdcard/kb.raw", timeout=15)
        parts = [int(item) for item in header.split()[:2]]
        width = parts[0] if parts else self.screen[0]
        height = parts[1] if len(parts) > 1 else self.screen[1]
        hits = 0
        for cx, cy in ((470, 856), (470, 932)):
            x = round(cx * width / 540)
            y = round(cy * height / 1200)
            for header_size in (12, 16):
                offset = header_size + (y * width + x) * 4
                sample = await self.session.adb_shell(
                    f"od -An -tu1 -N 4 -j {offset} /sdcard/kb.raw",
                    timeout=15,
                )
                nums = [int(item) for item in sample.split()]
                if len(nums) < 3:
                    continue
                red, green, blue = nums[0], nums[1], nums[2]
                if blue > red + 15 and (red + green + blue) / 3 > 160:
                    hits += 1
                break
        if hits >= 2:
            self.page = "pad"
            return True
        self.page = "letters"
        return False

    async def checkmark(self) -> None:
        await self.between("submit")
        await self.tap_key(*CHECK)

    async def dismiss_keyboard(self) -> None:
        # One Back while the keyboard is up hides only the keyboard.
        # The same key with the keyboard down leaves the app, so it is not sent.
        if not await self.keyboard_open():
            print("keyboard is closed, not pressing Back", flush=True)
            return
        print("closing the keyboard, staying in the app", flush=True)
        await self.session.adb_shell("input keyevent 4", timeout=15)
        self.dismissed_keyboard = True
        await asyncio.sleep(0.5)

    async def nav(self, which: str) -> None:
        print(f"not tapping system {which}, that leaves the app", flush=True)

    async def finger(self, start: tuple[int, int], end: tuple[int, int], swipe: bool = False) -> None:
        points, gaps = stroke(start, end, self.rng, swipe=swipe)
        for index, (x, y) in enumerate(points):
            down = 0 if index == len(points) - 1 else 1
            payload = json.dumps({
                "type": "multi-touch",
                "id": [1],
                "x": [int(x)],
                "y": [int(y)],
                "down": down,
                "device_label": "display_0",
            })
            await self.session.send_data_channel("input-channel", payload)
            if index < len(gaps):
                await asyncio.sleep(gaps[index] / 1000)

    def choose_wheel_swipe(self) -> tuple[str, int, int]:
        """Kind, length in pixels, and speed. The next one differs in both length and speed.

        Measured on the month, day, and year wheels. Finger down moves to the previous value.
        A stopped drag of 75–150px moves one step, at any speed from 290–640ms.
        A stopped drag of 200–250px moves two steps.
        A flick released while the finger is still moving, 100–140px in 120–160ms, moves four steps.
        The same flick at 165–190px in 165–190ms moves five steps.
        """
        rng = self.rng
        kind, travel, duration = "drag", 90, 400
        for _ in range(12):
            family = rng.choice(("one", "two", "four", "five"))
            if family == "one":
                kind, travel, duration = "drag", 78 + rng.randrange(68), 290 + rng.randrange(350)
            elif family == "two":
                kind, travel, duration = "drag", 205 + rng.randrange(46), 300 + rng.randrange(400)
            elif family == "four":
                kind, travel, duration = "flick", 100 + rng.randrange(36), 120 + rng.randrange(36)
            else:
                kind, travel, duration = "flick", 165 + rng.randrange(26), 165 + rng.randrange(26)
            previous = self.last_wheel
            if previous is None or (
                abs(travel - previous[0]) >= 16
                and abs(duration - previous[1]) >= 35
                and kind != previous[2]
            ):
                break
        self.last_wheel = (travel, duration, kind)
        return kind, travel, duration

    async def wheel_drag(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        kind: str = "drag",
        duration: int | None = None,
        label: str = "wheel",
    ) -> None:
        """A finger on one wheel. A drag stops. A flick is released while still moving."""
        rng = self.rng
        if duration is None:
            duration = 120 + rng.randrange(50) if kind == "flick" else 320 + rng.randrange(280)
        hold = 0 if kind == "flick" else rng.choice((0, 0, 40, 110))
        bow = rng.randint(-14, 14)
        shift = rng.randint(-10, 10)
        column_x = start[0]
        start = (start[0] + shift, start[1] + rng.randint(-4, 4))
        end = (end[0] + shift + rng.randint(-6, 6), end[1] + rng.randint(-3, 3))
        width, height = self.screen
        left = max(24, column_x - 40)
        right = min(width - 24, column_x + 40)
        start = (max(left, min(right, start[0])), max(840, min(height - 95, start[1])))
        end = (max(left, min(right, end[0])), max(840, min(height - 95, end[1])))
        print(
            label,
            kind,
            "px", abs(end[1] - start[1]),
            "ms", duration,
            "hold", hold,
            "bow", bow,
            flush=True,
        )
        steps = max(5, duration // 14)
        points = []
        for index in range(steps + 1):
            t = index / steps
            eased = t * t * t if kind == "flick" else t * t * (3 - 2 * t)
            x = start[0] + (end[0] - start[0]) * eased + bow * (4 * t * (1 - t))
            y = start[1] + (end[1] - start[1]) * eased
            points.append((round(x), round(y)))
        if hold:
            x, y = points[0]
            await self.session.send_data_channel("input-channel", json.dumps({
                "type": "multi-touch",
                "id": [1],
                "x": [x],
                "y": [y],
                "down": 1,
                "device_label": "display_0",
            }))
            await asyncio.sleep(hold / 1000)
        gap = duration / steps / 1000
        for index, (x, y) in enumerate(points):
            await self.session.send_data_channel("input-channel", json.dumps({
                "type": "multi-touch",
                "id": [1],
                "x": [int(x)],
                "y": [int(y)],
                "down": 0 if index == len(points) - 1 else 1,
                "device_label": "display_0",
            }))
            if index < len(points) - 1:
                await asyncio.sleep(gap)


def stroke(start, end, rng: random.Random, swipe: bool = False):
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = (dx * dx + dy * dy) ** 0.5
    if length < 1:
        return [start], []
    if swipe:
        # One finger swipe: it travels the wheel, then lifts. Not a fling and not a scroll.
        fraction = 0.78 + rng.random() * 0.2
        duration = 240 + int(rng.random() * 180)
    else:
        fraction = 0.72 + rng.random() * 0.28 if length < 48 else 0.24 + min(rng.random(), rng.random()) * 0.42
        flick = rng.random() < 0.62
        duration = 150 + int(rng.random() * 160) if flick else 280 + int(rng.random() * 200)
    travel = length * fraction
    spare = length - travel
    along = spare * (0.12 + rng.random() * 0.76)
    ux, uy = dx / length, dy / length
    origin = (start[0] + ux * along, start[1] + uy * along)
    dest = (origin[0] + ux * travel, origin[1] + uy * travel)
    bow = (rng.random() * 2 - 1) * min(16, travel * 0.09)
    shape = 1.15 + rng.random() * 2.1
    gaps = []
    elapsed = 0
    gap = 7 + int(rng.random() * 7)
    while elapsed + 4 < duration:
        fresh = 6 + rng.random() * 10
        gap = max(4, min(22, round(gap * 0.65 + fresh * 0.35 + (rng.random() - 0.5) * 6)))
        step = min(gap, duration - elapsed)
        if step < 4:
            break
        gaps.append(step)
        elapsed += step
    total = sum(gaps) or 1
    points = []
    cursor = 0
    for step_index in range(len(gaps) + 1):
        t = 0 if step_index == 0 else 1 if step_index == len(gaps) else cursor / total
        raised = t ** shape
        other = (1 - t) ** shape
        warped = t if raised + other == 0 else raised / (raised + other)
        eased = warped ** 3 * (10 - 15 * warped + 6 * warped * warped)
        curve = __import__("math").sin(__import__("math").pi * t) * bow
        points.append((
            round(origin[0] + (dest[0] - origin[0]) * eased + (-uy) * curve),
            round(origin[1] + (dest[1] - origin[1]) * eased + ux * curve),
        ))
        if step_index < len(gaps):
            cursor += gaps[step_index]
    return points, gaps


def load_play() -> tuple[str, str, str]:
    if os.environ.get("PLAY_STATE"):
        state_path = Path(os.environ["PLAY_STATE"])
    else:
        state_path = None
        for parent in (ROOT, *ROOT.parents, Path.cwd(), *Path.cwd().parents):
            candidate = parent / ".cursor" / "skills" / "play-store" / "state.json"
            if candidate.is_file():
                state_path = candidate
                break
            if parent == Path.home():
                break
        if state_path is None:
            raise RuntimeError("set PLAY_STATE to the play-store state.json")
    state = json.loads(state_path.read_text())
    raw = state.get("play_account") or ""
    if not raw:
        raise RuntimeError("no saved play account")
    email, password, secret = raw.split(":", 2)
    return email.strip(), password, secret.strip()


def supported(value: str) -> bool:
    for char in value:
        if char.isalpha() or char.isdigit() or char in EXTRA or char == "@":
            continue
        return False
    return True


async def in_app_back(hand: Hand, nodes) -> bool:
    """A control inside the app. The system navigation bar leaves the app."""
    for label in ("Navigate up", "Back"):
        node = _find(nodes, label, None)
        if node and node.get("bounds"):
            print("in-app back", label, flush=True)
            await hand.tap_node(node)
            return True
    return False


async def back_from_code_page(hand: Hand) -> None:
    """On Confirm your number, Back returns to the number field. It does not leave Snapchat."""
    print("back on the code page, returning to the number field", flush=True)
    for _ in range(2):
        await hand.session.adb_shell("input keyevent 4", timeout=15)
        await asyncio.sleep(1.0)
        nodes = await _play_nodes(hand.session)
        blob = " ".join(_texts(nodes)).lower()
        if "enter the code" not in blob and "confirm your number" not in blob:
            return
    print("still on the code page", flush=True)


async def tap_named(hand: Hand, nodes, text: str, class_name: str | None = None) -> None:
    node = _find(nodes, text, class_name)
    if node is None:
        node = _find(nodes, text, None)
    if node is None or not node.get("bounds"):
        raise RuntimeError(f"missing {text}")
    await hand.tap_node(node)


async def submit_field(hand: Hand, nodes) -> None:
    nxt = _find(nodes, "Next", "android.widget.Button")
    if nxt and nxt.get("bounds"):
        top = nxt["bounds"]["top"]
        if top < int(hand.screen[1] * 0.72):
            print("submit by Next, the button is above the keyboard", flush=True)
            await hand.tap_node(nxt)
            return
    print("submit by the keyboard checkmark", flush=True)
    await hand.checkmark()


async def _typed_password(hand: Hand, password: str):
    # Key taps missed this length twice. The field is already focused.
    # One input text. A second call clears first, so it does not append.
    fresh = await _play_nodes(hand.session)
    length = max(_bullet_length(fresh), _field_length(fresh))
    if length:
        await hand.backspaces(length)
    encoded = password.replace(" ", "%s")
    await hand.session.adb_shell(f"input text {shlex.quote(encoded)}", timeout=20)
    await asyncio.sleep(0.6)
    fresh = await _play_nodes(hand.session)
    matched = max(_bullet_length(fresh), _field_length(fresh)) == len(password)
    return fresh, matched


def _code_digits(nodes) -> str:
    shown = str((_edit_text(nodes) or {}).get("text") or "")
    return "".join(char for char in shown if char.isdigit())


async def _code_state(hand: Hand):
    fresh = await _play_nodes(hand.session)
    return fresh, _code_digits(fresh)


async def _focus_code_field(hand: Hand):
    fresh, _digits = await _code_state(hand)
    field = _edit_text(fresh)
    if not field or not field.get("bounds"):
        return
    print("tap the code field", flush=True)
    await hand.tap_node(field)
    await asyncio.sleep(0.45)


async def _clear_code(hand: Hand, count: int) -> None:
    if count <= 0:
        return
    print("clearing the code field", flush=True)
    if hand.page == "pad":
        await hand.pad_delete(count)
    else:
        await hand.backspaces(count)


async def _typed_pin(hand: Hand, code: str):
    # A keyboard left open from the password screen is not focus in this field.
    # Taps then hit keys and the code field stays empty.
    await _focus_code_field(hand)
    pad = await hand.see_pad()
    hand.page = "pad" if pad else "letters"
    print("phone pad" if pad else "digit row for the code", flush=True)
    _fresh, digits = await _code_state(hand)
    if digits:
        await _clear_code(hand, len(digits))
    for attempt in (1, 2):
        if hand.page == "pad":
            await hand.type_pin(code)
        else:
            await hand.type_text(code)
        fresh, digits = await _code_state(hand)
        print("code field", "len", len(digits), "digits", len(digits), flush=True)
        if digits == code:
            return fresh, True
        if attempt == 1 and not digits:
            print("code did not land, reading the keyboard again", flush=True)
            await _focus_code_field(hand)
            pad = await hand.see_pad()
            hand.page = "pad" if pad else "letters"
            print("phone pad" if pad else "digit row for the code", flush=True)
            continue
        return fresh, False
    return fresh, False


def link_dropped(error: BaseException) -> bool:
    return isinstance(error, (TimeoutError, ConnectionError, OSError)) or type(error).__name__ in {
        "ConnectionClosedError",
        "ConnectionClosed",
        "InvalidStateError",
        "TelephortAutomationError",
    }


async def revive(hand: Hand) -> None:
    old = hand.session
    try:
        await old.close()
    except Exception:
        pass
    session = await hand.client.connect_device_automation(DEVICE, timeout=90)
    await session.initialize_adb(timeout=40)
    hand.session = session
    print("automation session reconnected", flush=True)
    CLOCK.mark("link", "reconnected")


async def _play_nodes(session):
    current = session
    pauses = (2, 2, 2)
    for index, pause in enumerate(pauses):
        try:
            return await _read_nodes(current)
        except Exception as error:
            if not link_dropped(error):
                raise
            print("screen read timed out, reading it again", flush=True)
            CLOCK.mark("link", "read again")
            await asyncio.sleep(pause)
            hand = ACTIVE["hand"]
            if hand is None:
                continue
            current = hand.session
            if index == len(pauses) - 1:
                await revive(hand)
                current = hand.session
    return await _read_nodes(current)


async def read_screen(hand: Hand):
    return await _play_nodes(hand.session)


async def play_in_front(session) -> bool:
    resumed = await session.adb_shell(
        "dumpsys activity activities | grep topResumedActivity",
        timeout=20,
    )
    return "com.android.vending" in resumed


async def open_play_listing(hand: Hand) -> None:
    if await play_in_front(hand.session):
        print("Play is already in front, not opening the link again", flush=True)
        CLOCK.mark("play", "already in front")
        return
    await hand.session.adb_shell(
        f"am start -a android.intent.action.VIEW -d market://details?id={SNAP}",
        timeout=20,
    )
    print("opened Play by the store link, not by a finger on the icon", flush=True)
    CLOCK.mark("play", "open listing")
    await asyncio.sleep(6)


async def play_loop(hand: Hand, email: str, password: str, secret: str, reopen: bool = False) -> None:
    past_authenticator = False
    nodes = await read_screen(hand)
    on_account = any("identifierId" in str(node.get("resource_id") or "") for node in nodes)
    # Reopening the store link leaves a sign-in page that is already on screen.
    if reopen or (not on_account and play_decision(nodes)["op"] == "wait"):
        await open_play_listing(hand)
    for _ in range(40):
        nodes = await read_screen(hand)
        texts = _texts(nodes)
        if "Open" in texts and "Snapchat" in texts:
            print("play listing is on screen", flush=True)
            return
        if is_snapchat_signup(texts):
            print("snapchat signup is on screen, leaving Play", flush=True)
            CLOCK.mark("play", "snapchat signup")
            return
        decision = play_decision(nodes)
        print("play", decision["op"], decision.get("text") or "", _safe_label(nodes, email, password), flush=True)
        CLOCK.mark("play", f"{decision['op']} {decision.get('text') or ''}")
        op = decision["op"]
        if "Home screen" in texts and "Install" not in texts and "Snapchat" not in texts:
            if await play_in_front(hand.session):
                print("home text is behind Play, waiting", flush=True)
                CLOCK.mark("play", "home behind play")
                await asyncio.sleep(2)
                continue
            print("Play left on its own, opening it again", flush=True)
            CLOCK.mark("play", "left on its own, reopen")
            await open_play_listing(hand)
            continue
        if op == "block":
            raise RuntimeError(decision.get("reason") or "play blocked")
        if op in ("signed_in", "installed"):
            return
        if op == "wait":
            await asyncio.sleep(2)
            continue
        if op == "tap":
            label = decision["text"]
            screen = "|".join(texts)
            if label in ("Try another way", "Google Authenticator") and await hand.keyboard_open():
                await hand.dismiss_keyboard()
                continue
            if hand.same_press(label, screen):
                print("same button still on this screen, waiting", label, flush=True)
                await asyncio.sleep(2)
                continue
            if label in ("Allow", "Don't allow", "Deny", "Not now", "Not allowed", "Allowed"):
                await hand.between("dialog")
            await tap_named(hand, nodes, label, decision.get("class_name"))
            if label == "Not allowed" and _find(nodes, "Navigate up", None):
                print("leaving the notification access sheet", flush=True)
                await hand.between("dialog")
                fresh = await _play_nodes(hand.session)
                if _find(fresh, "Navigate up", None):
                    await tap_named(hand, fresh, "Navigate up")
            hand.remember(label, screen)
            if label == "Install":
                hand.install_tapped = True
                print("install tapped once", flush=True)
                return
            if label == "Google Authenticator":
                past_authenticator = True
        elif op == "type_email":
            field = _edit_text(nodes)
            await hand.show_keyboard(field)
            length = _field_length(nodes)
            if length:
                await hand.backspaces(length)
            fresh = await _play_nodes(hand.session)
            if _field_length(fresh):
                raise RuntimeError("field was not empty before the address")
            if not any("identifierId" in str(node.get("resource_id") or "") for node in fresh):
                raise RuntimeError("left the email page while clearing")
            await hand.type_landed(email)
            fresh = await _play_nodes(hand.session)
            typed = field_text(fresh)
            if typed != email:
                print(
                    "address mismatch",
                    "len", len(typed),
                    "at", typed.count("@"),
                    "hash", typed.count("#"),
                    flush=True,
                )
                print("в поле не то, что ожидалось, ввожу второй раз", "len", len(typed), "expected", len(email), flush=True)
                if not any("identifierId" in str(node.get("resource_id") or "") for node in fresh):
                    raise RuntimeError("left the email page while typing")
                if typed and await hand.keyboard_open():
                    for _ in range(4):
                        fresh = await _play_nodes(hand.session)
                        left = field_text(fresh)
                        if left in ("", "Email or phone"):
                            break
                        await hand.backspaces(len(left))
                    fresh = await _play_nodes(hand.session)
                    if field_text(fresh) not in ("", "Email or phone"):
                        raise RuntimeError("address was not cleared")
                elif typed:
                    raise RuntimeError("address was wrong and the keyboard is closed")
                await hand.type_landed(email)
                fresh = await _play_nodes(hand.session)
                typed = field_text(fresh)
                if typed != email:
                    print(
                        "address still wrong",
                        "len", len(typed),
                        "at", typed.count("@"),
                        "hash", typed.count("#"),
                        flush=True,
                    )
                    raise RuntimeError("address was not entered once")
            await submit_field(hand, fresh)
        elif op == "type_password":
            if any("Wrong password" in text for text in texts):
                print("password was rejected, typing it once more", flush=True)
            field = _edit_text(nodes)
            await hand.show_keyboard(field)
            length = max(_bullet_length(nodes), _field_length(nodes))
            if length:
                await hand.backspaces(length)
            fresh, matched = await _typed_password(hand, password)
            if not matched:
                print("в поле не то, что ожидалось, ввожу второй раз", "expected", len(password), flush=True)
                fresh, matched = await _typed_password(hand, password)
            if not matched:
                print("второй ввод тоже не совпал", "expected", len(password), flush=True)
                raise RuntimeError("password length did not match")
            await submit_field(hand, fresh)
        elif op == "type_code":
            past_authenticator = True
            code = _totp(secret)
            print("typing the code on the phone pad", flush=True)
            fresh, matched = await _typed_pin(hand, code)
            if not matched:
                print("в поле не шесть цифр, ввожу код ещё раз", "expected", len(code), flush=True)
                code = _totp(secret)
                fresh, matched = await _typed_pin(hand, code)
            if not matched:
                print("второй ввод тоже не совпал", "expected", len(code), flush=True)
                raise RuntimeError("code was not entered as six digits")
            fresh, digits = await _code_state(hand)
            if digits != code:
                raise RuntimeError("code was not entered as six digits")
            await submit_field(hand, fresh)
        elif op == "hide_keyboard":
            if not hand.dismissed_keyboard:
                await hand.dismiss_keyboard()
            else:
                print("keyboard already closed once, waiting for the 2FA button", flush=True)
                await asyncio.sleep(1)
        elif op == "back_or_get_started":
            if not await in_app_back(hand, nodes):
                await asyncio.sleep(1)
        else:
            raise RuntimeError(f"unhandled play {op}")
        await hand.between("action")
    raise RuntimeError("play sign-in did not finish")


async def sign_in_play(hand: Hand, email: str, password: str, secret: str) -> None:
    try:
        CLOCK.mark("play", "attempt 1")
        await play_loop(hand, email, password, secret)
        CLOCK.mark("play", "signed in")
        return
    except RuntimeError as error:
        print("первый вход в Play не удался:", error, flush=True)
        CLOCK.mark("play", f"attempt 1 failed: {type(error).__name__}")
        note_problem(
            "play",
            "первый вход не дошел до конца",
            "пароль — одним input text в уже открытое поле, не по клавишам. Если длина снова не сошлась, повторить весь вход один раз с той же почты и не менять нажатие на поле",
        )
        print("повторяю логин второй раз", flush=True)
        hand.last_label = ""
        hand.last_screen = ""
        hand.last_label_at = 0.0
        hand.page = "letters"
    try:
        CLOCK.mark("play", "attempt 2")
        await play_loop(hand, email, password, secret, reopen=True)
        CLOCK.mark("play", "signed in")
    except RuntimeError as error:
        print("второй вход в Play тоже не удался:", error, flush=True)
        CLOCK.mark("play", f"attempt 2 failed: {error}")
        raise


async def install_snap(hand: Hand) -> None:
    CLOCK.mark("install", "start")
    deadline = time.time() + 10 * 60
    next_look = 0.0
    download_started = False
    while time.time() < deadline:
        try:
            installed = await hand.session.adb_shell(f"pm path {SNAP}", timeout=30)
        except Exception as error:
            if not link_dropped(error):
                raise
            print("package check timed out, install continues", flush=True)
            CLOCK.mark("install", "package check timed out")
            await revive(hand)
            await asyncio.sleep(5)
            continue
        if installed.startswith("package:"):
            nodes = await read_screen(hand)
            texts = _texts(nodes)
            CLOCK.mark("install", "package")
            if "Home screen" in texts:
                await open_play_listing(hand)
                await asyncio.sleep(3)
                continue
            if "Open" in texts and "Uninstall" in texts and "Snapchat" in texts:
                if hand.open_taps < 2:
                    await tap_named(hand, nodes, "Open")
                    hand.open_taps += 1
                    print("tap Open", hand.open_taps, flush=True)
                    CLOCK.mark("install", f"tap open {hand.open_taps}")
                else:
                    print("Open is still on the listing", flush=True)
                    CLOCK.mark("install", "open still there")
                await asyncio.sleep(4)
                continue
            if not await play_in_front(hand.session):
                print("snapchat is open", flush=True)
            CLOCK.mark("install", "opened")
            return
        if download_started:
            print("install pending", flush=True)
            CLOCK.mark("install", "pending")
            await asyncio.sleep(15)
            continue
        now = time.time()
        if now >= next_look:
            nodes = await read_screen(hand)
            texts = _texts(nodes)
            blob = " ".join(texts).lower()
            if "Home screen" in texts:
                state = "home"
            elif any(word in blob for word in ("pending", "installing", "%")):
                state = "pending"
                download_started = True
            elif "Install" in texts:
                state = "install"
            else:
                state = "page"
            print("install", state, flush=True)
            CLOCK.mark("install", state)
            if state == "home":
                await open_play_listing(hand)
            elif state == "install" and not hand.install_tapped:
                await tap_named(hand, nodes, "Install")
                hand.install_tapped = True
                hand.remember("Install", "|".join(texts))
                print("install tapped once", flush=True)
                CLOCK.mark("install", "tapped once")
            next_look = time.time() + 20
        await asyncio.sleep(8)
    raise RuntimeError("snapchat install did not finish")


async def main() -> None:
    local = load_local()
    email, password, secret = load_play()
    if not supported(email) or not supported(password):
        raise RuntimeError("play secret uses a key that is not on the measured keyboard")
    rng = random.Random()
    plan = None
    for _ in range(40):
        candidate = make_plan(rng)
        fields = (candidate["first"], candidate["last"], candidate["username"], candidate["password"])
        if all(supported(field) for field in fields):
            plan = candidate
            break
    if plan is None:
        raise RuntimeError("signup text uses a key that is not on the measured keyboard")
    # The finished run skipped Bitmoji. Picking one has no working path here.
    plan["bitmoji"] = "skip"
    record = {
        "run_number": next_run(),
        "device_id": DEVICE,
        "status_history": [],
        "notes": ["realistic hand"],
    }
    write_run(record["run_number"], {**record, "plan_name": plan["first"]})
    if os.environ.get("SNAP_RESUME") != "1":
        plan["account_status"] = "planned"
        write_account(record, plan)
    client = TelephortClient("https://demo.telephort.app/api", timeout=120)
    client.auth.login(local["telephort_email"], local["telephort_password"])
    client.set_team_id(client.teams.list_mine()["items"][0]["id"])
    hand = None
    try:
        session = await client.connect_device_automation(DEVICE, timeout=90)
        await session.initialize_adb(timeout=40)
        screen = await _screen_size(session)
        if not screen:
            raise RuntimeError("no screen size")
        print("screen", screen, flush=True)
        CLOCK.mark("connect", f"screen {screen[0]}x{screen[1]}")
        hand = Hand(session, screen, rng)
        hand.client = client
        ACTIVE["hand"] = hand
        if os.environ.get("SNAP_RESUME") == "1":
            print("resuming on the open Snapchat screen", "run", record["run_number"], flush=True)
            CLOCK.mark("snap", "resume")
        else:
            await sign_in_play(hand, email, password, secret)
            await install_snap(hand)
            print("play done, snapchat opened", "run", record["run_number"], flush=True)
            CLOCK.mark("snap", "opened")
        await snap_loop(hand, plan, record, local)
        CLOCK.mark("finish", "feed")
    except Exception as error:
        await save_stop_shot(hand, error)
        finish_report(type(error).__name__)
        raise
    else:
        finish_report()
    finally:
        CLOCK.mark("end", "session close")
        if hand is not None:
            try:
                await hand.session.close()
            except Exception:
                pass


async def save_stop_shot(hand: Hand | None, reason: BaseException) -> None:
    if hand is None:
        return
    folder = Path("/tmp/snap-chats")
    folder.mkdir(exist_ok=True)
    path = folder / f"stop-{int(time.time())}.png"
    try:
        png = await hand.session.capture_screenshot_png(timeout=25)
        path.write_bytes(png)
        print("stop screenshot", path, type(reason).__name__, flush=True)
    except Exception as error:
        print("stop screenshot failed", type(error).__name__, flush=True)


async def snap_loop(hand: Hand, plan: dict, record: dict, local: dict) -> None:
    fivesim = FiveSim(local.get("fivesim_token") or "")
    order = None
    home_opens = 0
    await asyncio.sleep(1)
    for _ in range(70):
        nodes = await _play_nodes(hand.session)
        decision = snap_decision(_texts(nodes), plan, nodes)
        print("snap", decision["op"], decision.get("text") or "", _safe_label(nodes, "", plan["password"]), flush=True)
        CLOCK.mark("snap", f"{decision['op']} {decision.get('text') or ''}")
        op = decision["op"]
        if op == "block":
            raise RuntimeError(decision.get("reason") or "snap blocked")
        if op == "feed":
            print("account reached the feed", flush=True)
            plan["account_status"] = "feed"
            write_account(record, plan)
            return
        if op == "tap":
            label = decision["text"]
            screen = "|".join(_texts(nodes))
            if label == "Open" and "Uninstall" in screen:
                if hand.open_taps < 2:
                    await tap_named(hand, nodes, label, decision.get("class_name"))
                    hand.open_taps += 1
                    hand.remember(label, screen)
                    print("tap Open", hand.open_taps, flush=True)
                    CLOCK.mark("snap", f"tap open {hand.open_taps}")
                else:
                    print("Open is still on the listing", flush=True)
                await asyncio.sleep(3)
                continue
            if hand.same_press(label, screen):
                print("same button still on this screen, waiting", label, flush=True)
                await asyncio.sleep(2)
                continue
            if label in ("Allow", "Don't allow", "Deny", "Not now", "Not allowed", "Allowed"):
                await hand.between("dialog")
            await tap_named(hand, nodes, label, decision.get("class_name"))
            hand.remember(label, screen)
        elif op == "tap_bounds":
            bounds = decision["bounds"]
            if "already started creating an account" in " ".join(_texts(nodes)).lower():
                bounds = _continue_draft(nodes) or bounds
                print("continuing the started account", flush=True)
            await hand.tap_node({"bounds": bounds})
        elif op == "type_name":
            await type_name(hand, nodes, plan)
            plan["account_status"] = "name"
            write_account(record, plan)
        elif op == "birthday":
            await birthday(hand, nodes, plan)
            plan["account_status"] = "birthday"
            write_account(record, plan)
        elif op == "type_username":
            shown = field_text(nodes)
            if shown and "available" in " ".join(_texts(nodes)).lower():
                plan["username"] = shown
                keep_password(plan, hand.rng)
            await fill_and_continue(hand, nodes, plan["username"])
            plan["account_status"] = "username"
            write_account(record, plan)
        elif op == "type_password":
            await fill_and_continue(hand, nodes, plan["password"])
            plan["account_status"] = "password"
            write_account(record, plan)
        elif op == "username_taken":
            await extend_username(hand, nodes, plan)
            plan["account_status"] = "username"
            write_account(record, plan)
        elif op == "password_rejected":
            accepted = False
            for _try in range(6):
                if not password_rejected(plan, hand.rng):
                    break
                if supported(plan["password"]):
                    accepted = True
                    break
            if not accepted:
                raise RuntimeError("password rejected")
            plan["account_status"] = "password"
            write_account(record, plan)
        elif op == "code_rejected":
            raise RuntimeError("sms code rejected")
        elif op == "refusal":
            raise RuntimeError("phone refused")
        elif op == "change_number":
            await replace_whatsapp_number(hand, fivesim, order)
            order = None
            hand.number_changes += 1
            if hand.number_changes > 4:
                raise RuntimeError("codes keep going to WhatsApp")
            continue
        elif op == "internet":
            if hand.restarts:
                raise RuntimeError("snapchat still reports no internet")
            hand.restarts = 1
            order = None
            print("internet error, closing Snapchat and opening it again", flush=True)
            await hand.session.adb_shell("am force-stop com.snapchat.android", timeout=20)
            await asyncio.sleep(1)
            await hand.session.adb_shell(
                "am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -p com.snapchat.android",
                timeout=20,
            )
            await asyncio.sleep(3)
        elif op == "type_phone":
            order = await enter_phone(hand, nodes, fivesim, order)
            if order:
                plan["phone"] = str(order.get("phone") or "")
                plan["phone_country"] = str(order.get("country") or "")
                plan["account_status"] = "phone"
                write_account(record, plan)
        elif op == "type_sms":
            shown_number = _shown_number(_texts(nodes))
            if shown_number:
                plan["phone_on_screen"] = shown_number
                plan["account_status"] = "code"
                write_account(record, plan)
            if order is not None and _number_on_screen(order, _texts(nodes)):
                try:
                    await enter_code(hand, nodes, fivesim, order)
                except RuntimeError as error:
                    if "whatsapp" not in str(error):
                        raise
                    await replace_whatsapp_number(hand, fivesim, order)
                    order = None
                    hand.number_changes += 1
                    if hand.number_changes > 4:
                        raise RuntimeError("codes keep going to WhatsApp") from error
                    continue
                plan["code_accepted"] = True
                continue
            if order is None:
                order = buy_number(fivesim)
            if hand.phone_backs >= 2:
                raise RuntimeError("could not leave the code page to type the number")
            hand.phone_backs += 1
            print("going back to enter the bought number", flush=True)
            if await in_app_back(hand, nodes):
                await asyncio.sleep(1)
            else:
                await back_from_code_page(hand)
        elif op == "unknown":
            present = set(_texts(nodes))
            if home_opens < 2 and {"Home", "Phone", "Messages", "Chrome"} <= present:
                home_opens += 1
                print("home screen, opening Snapchat", flush=True)
                CLOCK.mark("snap", "open from home")
                await hand.session.adb_shell(
                    "am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -p com.snapchat.android",
                    timeout=20,
                )
                await asyncio.sleep(3)
                continue
            await asyncio.sleep(2)
            continue
        else:
            raise RuntimeError(f"unhandled snap {op}")
        await hand.between("action")
    raise RuntimeError("signup did not finish")


def _continue_draft(nodes) -> dict | None:
    """The upper button on the welcome-back sheet continues the draft. The lower one is No."""
    login_top = None
    for node in nodes:
        if "already have an account" not in str(node.get("text") or "").lower():
            continue
        bounds = node.get("bounds")
        if bounds:
            login_top = bounds["top"]
            break
    if login_top is None:
        return None
    buttons = []
    for node in nodes:
        if not node.get("clickable"):
            continue
        bounds = node.get("bounds")
        if not bounds:
            continue
        width = bounds["right"] - bounds["left"]
        height = bounds["bottom"] - bounds["top"]
        if width < 200 or height < 40 or height > 160:
            continue
        if bounds["bottom"] <= login_top and bounds["top"] > login_top - 400:
            buttons.append(bounds)
    if not buttons:
        return None
    return min(buttons, key=lambda bounds: bounds["top"])


def field_text(nodes) -> str:
    field = _edit_text(nodes)
    return str((field or {}).get("text") or "")


async def close_keyboard(hand: Hand) -> None:
    print("checkmark to close the keyboard", flush=True)
    await hand.checkmark()
    for _ in range(12):
        await asyncio.sleep(0.25)
        if not await hand.keyboard_open():
            print("keyboard closed", flush=True)
            hand.page = "letters"
            return
    print("keyboard stayed open, continuing", flush=True)


async def tap_after_keyboard(hand: Hand, label: str | None = None, allow_number_screen: bool = False) -> None:
    await close_keyboard(hand)
    nodes = await _play_nodes(hand.session)
    blob = " ".join(_texts(nodes)).lower()
    if not allow_number_screen and any(phrase in blob for phrase in ("mobile number", "phone number", "country or region", "enter the code", "confirm your number")):
        print("number screen is open, not pressing Continue", flush=True)
        return
    labels = (label,) if label else ("Agree and Continue", "Continue", "Next", "Sign Up")
    for name in labels:
        if name and _find(nodes, name, None):
            print("tap after keyboard", name, flush=True)
            await tap_named(hand, nodes, name)
            return
    print("screen changed, the button is not on it", flush=True)


async def type_name(hand: Hand, nodes, plan: dict) -> None:
    target = plan["first"] + " " + plan["last"]
    shown = field_text(nodes)
    if shown != target:
        field = _edit_text(nodes)
        if await hand.keyboard_open():
            print("keyboard already open, not tapping the field", flush=True)
        else:
            await hand.show_keyboard(field)
        if shown and shown not in ("First and Last name",):
            await hand.backspaces(len(shown))
            fresh = await _play_nodes(hand.session)
            if field_text(fresh) not in ("", "First and Last name"):
                raise RuntimeError("name field was not cleared")
        await hand.type_landed(target, auto_cap=True)
        fresh = await _play_nodes(hand.session)
        if field_text(fresh) != target:
            print(
                "в поле не то, что ожидалось, ввожу второй раз",
                "len", len(field_text(fresh)),
                "expected", len(target),
                flush=True,
            )
            await _clear_typed(hand, target)
            await hand.type_landed(target, auto_cap=True)
            fresh = await _play_nodes(hand.session)
            if field_text(fresh) != target:
                print(
                    "второй ввод тоже не совпал",
                    "len", len(field_text(fresh)),
                    "expected", len(target),
                    flush=True,
                )
                raise RuntimeError("name was not entered once")
    await tap_after_keyboard(hand, "Agree and Continue")


HINTS = {
    "",
    "First and Last name",
    "Username",
    "Password",
    "Mobile number",
    "Phone number",
    "Enter code",
}


def digits_of(text: str) -> str:
    return "".join(char for char in text if char.isdigit())


async def _clear_typed(hand: Hand, value: str) -> None:
    for _ in range(6):
        fresh = await _play_nodes(hand.session)
        left = field_text(fresh)
        if left in HINTS or not left:
            return
        if value.isdigit() and hand.page == "pad":
            await hand.pad_delete(len(digits_of(left)) or len(left))
        else:
            await hand.backspaces(len(left))
    raise RuntimeError("field was not cleared")


def keep_password(plan: dict, rng: random.Random) -> None:
    if password_ok(plan.get("password") or "", plan):
        return
    pattern = plan.get("password_pattern") or "word_digits"
    plan["password"] = password_for(pattern, plan, rng)
    if not supported(plan["password"]):
        plan["password"] = password_for("word_digits", plan, rng)


async def extend_username(hand: Hand, nodes, plan: dict) -> None:
    current = field_text(nodes)
    if current in HINTS or not current:
        raise RuntimeError("username field is empty")
    room = 15 - len(current)
    if room <= 0:
        raise RuntimeError("username is 15 characters and still taken")
    count = 1 if room == 1 or hand.rng.random() < 0.5 else min(2, room)
    extra = "".join(str(hand.rng.randint(0, 9)) for _ in range(count))
    field = _edit_text(nodes)
    if await hand.keyboard_open():
        print("keyboard already open, not tapping the field", flush=True)
    else:
        await hand.show_keyboard(field)
    await hand.type_landed(extra)
    fresh = await _play_nodes(hand.session)
    typed = field_text(fresh)
    if not typed.endswith(extra):
        print("в поле не то, что ожидалось, ввожу второй раз", "len", len(typed), flush=True)
        added = max(0, len(typed) - len(current))
        if added:
            await hand.backspaces(added)
        await hand.type_landed(extra)
        fresh = await _play_nodes(hand.session)
        typed = field_text(fresh)
        if not typed.endswith(extra):
            print("второй ввод тоже не совпал", "len", len(typed), flush=True)
            raise RuntimeError("digits were not added at the end of the username")
    plan["username"] = typed
    keep_password(plan, hand.rng)
    print("username extended", "len", len(typed), flush=True)


def _char_kind(char: str) -> str:
    if char.isupper():
        return "upper"
    if char.islower():
        return "lower"
    if char.isdigit():
        return "digit"
    return "other"


def text_shape(shown: str, value: str) -> str:
    marks = []
    for index, (got, expected) in enumerate(zip(shown, value)):
        if got != expected:
            marks.append(f"{index}:{_char_kind(expected)}->{_char_kind(got)}")
    if len(shown) != len(value):
        marks.append(f"len {len(shown)}/{len(value)}")
    return ",".join(marks[:8]) or "same"


def note_keyboard(hand: Hand, nodes) -> None:
    # A phone pad has no ABC or ?123. The pad check already set the page,
    # and this read must not throw that away before the digits are typed.
    if hand.page == "pad":
        return
    texts = set(_texts(nodes))
    if "ABC" in texts:
        hand.page = "symbols"
        print("keyboard shows ABC", flush=True)
    elif "?123" in texts or "!#1" in texts:
        hand.page = "letters"
        print("keyboard shows letters", flush=True)
    else:
        print("keyboard page not visible", flush=True)


def typed_on_symbol_page(shown: str, value: str) -> bool:
    """Letters came out as symbols. ABC and ?123 are not in the dump."""
    if not shown or not value or shown == value or shown in HINTS:
        return False
    if not all(char.isalnum() for char in value):
        return False
    return any(not char.isalnum() for char in shown)


async def leave_symbol_page(hand: Hand) -> None:
    print("letters landed as symbols, switching to letters once", flush=True)
    await hand.between("modifier")
    await hand.tap_key(*SYMBOL)
    hand.page = "letters"


def _friends_already(nodes) -> bool:
    """Signup already left the code page. Do not type the code onto that screen."""
    texts = _texts(nodes)
    blob = " ".join(texts).lower()
    present = set(texts)
    if "find friends" in blob or "add friends" in blob or "bitmoji" in blob:
        return True
    if {"Chat", "Stories", "Spotlight"} <= present:
        return True
    return "Chat" in present and "Memories" in present


async def replace_field(hand: Hand, nodes, value: str) -> None:
    field = _edit_text(nodes)
    if await hand.keyboard_open():
        print("keyboard already open, not tapping the field", flush=True)
    else:
        await hand.show_keyboard(field)
    if value.isdigit():
        pad = await hand.see_pad()
        print("phone pad" if pad else "letter keyboard for digits", flush=True)
    for _ in range(6):
        fresh = await _play_nodes(hand.session)
        left = field_text(fresh)
        if left in HINTS or not (digits_of(left) if value.isdigit() else left):
            break
        await hand.backspaces(len(left))
    else:
        raise RuntimeError("field was not cleared")
    fresh = await _play_nodes(hand.session)
    note_keyboard(hand, fresh)
    if value.isdigit() and (pad or hand.page == "pad"):
        await hand.type_pin(value)
    else:
        await hand.type_landed(value)
    fresh = await _play_nodes(hand.session)
    shown = field_text(fresh)

    def matches(nodes, text: str) -> bool:
        if value.isdigit():
            return digits_of(text) == value
        return _bullet_length(nodes) == len(value) or text == value

    if not matches(fresh, shown):
        if value.isdigit() and len(value) == 6 and _friends_already(fresh):
            print("code page already closed", flush=True)
            note_problem(
                "sms",
                "страница кода закрылась до проверки цифр",
                "если на экране уже друзья, не набирать код повторно",
            )
            raise RuntimeError("code page already closed")
        print(
            "в поле не то, что ожидалось, ввожу второй раз",
            "len", len(shown),
            "expected", len(value),
            "shape", text_shape(shown, value),
            flush=True,
        )
        if typed_on_symbol_page(shown, value):
            await leave_symbol_page(hand)
        await _clear_typed(hand, value)
        fresh = await _play_nodes(hand.session)
        note_keyboard(hand, fresh)
        if value.isdigit() and (pad or hand.page == "pad"):
            hand.page = "pad"
            await hand.type_pin(value)
        else:
            await hand.type_landed(value)
        fresh = await _play_nodes(hand.session)
        shown = field_text(fresh)
        if not matches(fresh, shown):
            print(
                "второй ввод тоже не совпал",
                "len", len(shown),
                "expected", len(value),
                "shape", text_shape(shown, value),
                flush=True,
            )
            raise RuntimeError("digits were not entered once" if value.isdigit() else "field text was not entered once")


async def fill_and_continue(hand: Hand, nodes, value: str) -> None:
    shown = field_text(nodes)
    if value.isdigit():
        ready = digits_of(shown) == value
    elif _bullet_length(nodes) == len(value):
        ready = True
    else:
        ready = shown == value
    if not ready:
        await replace_field(hand, nodes, value)
    await tap_after_keyboard(hand)


def _header_date(nodes) -> str:
    for node in nodes:
        text = str(node.get("text") or "").strip()
        if re.search(r"(19|20)\d\d", text) and ("," in text or "/" in text):
            return text
    return ""


def _shown_number(texts: list[str]) -> str:
    for text in texts:
        digits = "".join(char for char in text if char.isdigit())
        if len(digits) >= 10:
            return text.strip()
    return ""


def _header_year(nodes) -> int | None:
    """The date Snapchat shows above the wheels, such as Nov 9, 2009."""
    for node in nodes:
        text = str(node.get("text") or "")
        if "," not in text:
            continue
        match = re.search(r"(19|20)\d\d", text)
        if match:
            return int(match.group())
    return None


async def birthday(hand: Hand, nodes, plan: dict) -> None:
    from register import _column, _visible_year

    def shown_year(fresh) -> int | None:
        # The header is the selected date. A wheel cell can be the row above it.
        return _header_year(fresh) or _visible_year(fresh)

    async def place(node, older: bool, label: str) -> None:
        # Finger down moves to the previous month, day, or year.
        # Each swipe has its own length and speed, so the step count changes too.
        bounds = node["bounds"]
        x = (bounds["left"] + bounds["right"]) // 2
        y = (bounds["top"] + bounds["bottom"]) // 2
        kind, travel, duration = hand.choose_wheel_swipe()
        low, high = 850, min(hand.screen[1] - 95, 1105)
        if kind == "drag" and travel < 170:
            if older:
                end_y = min(high, y + travel)
                start_y = max(low, end_y - travel)
            else:
                end_y = max(low, y - travel)
                start_y = min(high, end_y + travel)
        elif older:
            start_y = low
            end_y = min(high, low + travel)
        else:
            end_y = low
            start_y = min(high, low + travel)
        print(label, "down" if older else "up", kind, flush=True)
        await hand.wheel_drag((x, start_y), (x, end_y), kind, duration, label)
        await asyncio.sleep(0.55 + hand.rng.random() * 0.35)

    async def spin(kind: str) -> None:
        # One downward swipe. That is the gesture that moved the year from 2008 to 2005.
        print(kind, "swipe", flush=True)
        fresh = await _play_nodes(hand.session)
        if "Birthday" not in _texts(fresh):
            print(kind, "wheel left the screen", flush=True)
            return
        column = _column(fresh, kind)
        if column is None or not column.get("bounds"):
            print(kind, "column is not on screen", flush=True)
            return
        await place(column, True, kind)

    async def reveal_beside_day() -> None:
        fresh = await _play_nodes(hand.session)
        day = _column(fresh, "day")
        if not day or not day.get("bounds"):
            print("no day column to place the year swipe", flush=True)
            return
        bounds = day["bounds"]
        width = max(40, bounds["right"] - bounds["left"])
        x = min(hand.screen[0] - 20, bounds["right"] + width // 2)
        y = (bounds["top"] + bounds["bottom"]) // 2
        row = max(36, bounds["bottom"] - bounds["top"])
        print("year column has no numbers, swiping beside the day", flush=True)
        await hand.wheel_drag((x, y - row // 5), (x, min(hand.screen[1] - 100, y + row)))
        await asyncio.sleep(0.45 + hand.rng.random() * 0.25)

    await spin("month")
    await spin("day")
    # The year still has to land in range. Month and day only need different swipes.
    older = True
    reverses = 0
    misses = 0
    fresh = nodes
    for _ in range(22):
        year = shown_year(fresh)
        print("birthday year", year, flush=True)
        if year is not None and 1970 <= year <= 2006:
            plan["birthday_year"] = year
            plan["birthday"] = _header_date(fresh)
            print("tap Continue on the birthday screen", flush=True)
            await tap_named(hand, fresh, "Continue")
            return
        column = _column(fresh, "year")
        if year is None or column is None or not column.get("bounds"):
            misses += 1
            if misses > 4:
                raise RuntimeError("the year column never showed a number")
            await reveal_beside_day()
            fresh = await _play_nodes(hand.session)
            continue
        if year < 1970:
            older = False
        await place(column, older, "year")
        fresh = await _play_nodes(hand.session)
        after = shown_year(fresh)
        print("birthday year", after, flush=True)
        if after is None or after == year:
            misses += 1
            if misses > 4:
                raise RuntimeError("the year swipe did not move the year")
            continue
        misses = 0
        if year > 2006 and after > year:
            reverses += 1
            if reverses > 2:
                raise RuntimeError("the year swipe does not move toward an older year")
            older = not older
            print("year got younger, reversing the swipe", flush=True)
            continue
        if year < 1970 and after < year:
            older = not older
            print("year got older, reversing the swipe", flush=True)
    raise RuntimeError("the birthday year stayed out of range")


SKIPPED: set[str] = set()


REFUSED_COUNTRIES = {
    "england",
    "netherlands",
    "poland",
    "spain",
    "portugal",
    "usa",
    "germany",
    "italy",
    "france",
    "czech",
}


def skipped_countries() -> set[str]:
    raw = os.environ.get("SNAP_SKIP_COUNTRY", "")
    return SKIPPED | REFUSED_COUNTRIES | {item.strip() for item in raw.split(",") if item.strip()}


def buy_number(fivesim: FiveSim) -> dict:
    open_order = reusable_order(fivesim)
    if open_order is not None:
        return open_order
    last = "no number"
    for attempt in range(2):
        countries = [
            name for name in prepared_countries(fivesim.prices(), limit=40) if name in DIAL
        ]
        if not countries:
            raise RuntimeError("no verification number in stock")
        for country in countries:
            if country in skipped_countries():
                continue
            try:
                order = fivesim.buy(country)
            except RuntimeError as error:
                text = str(error)
                if text.startswith("5sim 401"):
                    raise
                if text.startswith("5sim 429"):
                    last = "5sim 429"
                    break
                last = text.split(":", 1)[0]
                print("no number in", country, flush=True)
                continue
            order["country"] = order.get("country") or country
            print("bought a", order["country"], "number", flush=True)
            return order
        if last != "5sim 429" or attempt == 1:
            break
        print("5sim is busy, waiting", flush=True)
        time.sleep(20)
    raise RuntimeError(last)


def _number_on_screen(order, texts: list[str]) -> bool:
    phone = "".join(char for char in str(order.get("phone") or "") if char.isdigit())
    shown = "".join(char for char in " ".join(texts) if char.isdigit())
    tail = phone[-8:]
    return bool(tail) and tail in shown


def reusable_order(fivesim: FiveSim) -> dict | None:
    payload = fivesim._get(
        "https://5sim.net/v1/user/orders?category=activation&limit=8",
        auth=True,
    )
    items = payload.get("Data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return None
    for order in items:
        if order.get("product") != "snapchat":
            continue
        if str(order.get("status") or "").upper() not in {"PENDING", "RECEIVED"}:
            continue
        if str(order.get("country") or "") in skipped_countries():
            continue
        if not order.get("phone"):
            continue
        print("using the open", order.get("country"), "number", flush=True)
        return order
    return None


DIAL = {
    "england": "44",
    "netherlands": "31",
    "poland": "48",
    "spain": "34",
    "portugal": "351",
    "germany": "49",
    "france": "33",
    "italy": "39",
    "ukraine": "380",
    "czech": "420",
    "romania": "40",
    "usa": "1",
    "russia": "7",
}
COUNTRY_QUERY = {
    "england": "united kingdom",
    "czech": "czechia",
    "usa": "united states",
}
# The first word of "united states" is also the first word of "united kingdom".
SEARCH_WORD = {
    "england": "kingdom",
    "usa": "states",
    "czech": "czechia",
}


NATIONAL_LEN = {
    "england": (10, 10),
    "usa": (10, 10),
    "germany": (10, 12),
    "netherlands": (9, 9),
    "poland": (9, 9),
    "spain": (9, 9),
    "france": (9, 9),
    "italy": (9, 11),
    "portugal": (9, 9),
    "ukraine": (9, 9),
    "czech": (9, 9),
    "romania": (9, 9),
    "russia": (10, 10),
}


def country_from_phone(phone: str) -> str:
    """The digits decide the country. A 5sim label can say england for a +1 number."""
    digits = "".join(char for char in phone if char.isdigit())
    for country, prefix in sorted(DIAL.items(), key=lambda item: len(item[1]), reverse=True):
        if digits.startswith(prefix):
            return country
    return ""


def national_digits(phone: str, country: str) -> str:
    digits = "".join(char for char in phone if char.isdigit())
    dial = DIAL.get(country, "")
    if dial and digits.startswith(dial):
        digits = digits[len(dial):]
    if digits.startswith("0"):
        digits = digits[1:]
    return digits


def phone_field(nodes):
    fields = _edit_texts(nodes)
    if not fields:
        return None
    return max(fields, key=lambda node: node["bounds"]["right"] - node["bounds"]["left"])


def _country_name(text: str) -> str:
    letters = (char if char.isalpha() or char.isspace() else " " for char in text.lower())
    return " ".join("".join(letters).split())


async def choose_country(hand: Hand, country: str) -> None:
    query = COUNTRY_QUERY.get(country, country.replace("_", " "))
    nodes = await _play_nodes(hand.session)
    blob = " ".join(_texts(nodes)).lower()
    if "country or region" not in blob and "phone number" in blob and query in {_country_name(text) for text in _texts(nodes)}:
        print("country already", query, flush=True)
        return
    if "country or region" not in blob:
        target = None
        for node in nodes:
            text = str(node.get("text") or "")
            bounds = node.get("bounds") or {}
            if "country code" in text.lower() or text == "🌎 Invalid country code":
                if bounds and text != "Country":
                    target = node
                    break
            # The selected country is the wide row under the Country label.
            if (
                bounds
                and text
                and "EditText" not in str(node.get("class_name") or "")
                and text not in {"Country", "Phone Number", "Create account", "Use email instead"}
                and "phone" not in text.lower()
                and not text.lstrip("+").replace(" ", "").isdigit()
                and bounds.get("top", 0) > 180
                and bounds.get("bottom", 0) < 460
                and bounds.get("right", 0) - bounds.get("left", 0) > 200
            ):
                target = node
                break
        if target is None:
            raise RuntimeError("country row is not on screen")
        await hand.tap_node(target)
        await asyncio.sleep(1)
        nodes = await _play_nodes(hand.session)
    clear = _find(nodes, "Clear button", None)
    if clear is not None:
        await hand.tap_node(clear)
        await asyncio.sleep(0.3)
        nodes = await _play_nodes(hand.session)
    search = _find(nodes, "Search", None)
    if search is None:
        raise RuntimeError("country search is not on screen")
    await hand.tap_node(search)
    await asyncio.sleep(0.4)
    hand.page = "letters"
    # "uk" matches Ukraine. "united" matches both kingdom and states.
    await hand.type_landed(SEARCH_WORD.get(country, query.split()[0]))
    await asyncio.sleep(0.8)
    nodes = await _play_nodes(hand.session)
    match = None
    for node in nodes:
        text = str(node.get("text") or "")
        bounds = node.get("bounds")
        if bounds and _country_name(text) == query and bounds["top"] > 180:
            match = node
            break
    if match is None:
        raise RuntimeError("country was not in the list")
    print("country", query, flush=True)
    await hand.tap_node(match)
    await asyncio.sleep(1)


async def _phone_digits(hand: Hand) -> str:
    fresh = await _play_nodes(hand.session)
    current = phone_field(fresh)
    shown = "" if current is None else str(current.get("text") or "")
    return digits_of(shown)


async def clear_wrong_phone(hand: Hand, shown_digits: str) -> None:
    # The whole number is wrong. Press delete once per digit, then read once.
    # A dump after every digit is what made this step slow.
    if not shown_digits:
        return
    pad = await hand.see_pad()
    point = PAD_DELETE if pad else BACKSPACE
    hand.page = "pad" if pad else "letters"
    print("clearing phone field", len(shown_digits), "pad" if pad else "letters", flush=True)
    await hand.burst_delete(len(shown_digits), point)
    left = await _phone_digits(hand)
    if not left:
        return
    removed = len(shown_digits) - len(left)
    if removed <= 0:
        point = BACKSPACE if point == PAD_DELETE else PAD_DELETE
        print("delete taps missed, holding the other delete key", flush=True)
        note_problem(
            "phone",
            "короткие нажатия не попали в удаление",
            "зажать другую кнопку удаления и проверить поле один раз",
        )
        hand.page = "letters" if point == BACKSPACE else "pad"
        await hand.hold_delete(len(left) + 2, point)
    else:
        print("delete taps left", len(left), "holding the same key", flush=True)
        note_problem(
            "phone",
            "нажатий удаления не хватило на все цифры",
            "дожать удержанием оставшиеся цифры и проверить поле один раз",
        )
        await hand.hold_delete(len(left) + 2, point)
    left = await _phone_digits(hand)
    if not left:
        return
    print("hold left", len(left), "tapping delete for what remains", flush=True)
    note_problem(
        "phone",
        "удержание не очистило поле",
        "нажать удаление по числу оставшихся цифр и снова проверить один раз",
    )
    await hand.burst_delete(len(left), point)
    left = await _phone_digits(hand)
    if left:
        raise RuntimeError("phone field was not cleared")


async def type_national_number(hand: Hand, country: str, phone: str) -> None:
    digits = national_digits(phone, country)
    print("national digits", len(digits), flush=True)
    low, high = NATIONAL_LEN.get(country, (6, 15))
    if not low <= len(digits) <= high:
        raise RuntimeError("national number length does not match the country")
    nodes = await _play_nodes(hand.session)
    dial = DIAL.get(country, "")
    shown_dial = {
        text.replace(" ", "")
        for text in _texts(nodes)
        if text.startswith("+")
    }
    if dial and shown_dial and f"+{dial}" not in shown_dial:
        print("dial on screen is not the bought country", flush=True)
        note_problem("phone", "код страны на экране не совпал с номером", "не вводить цифры, пока на экране не тот код страны, который в номере")
        raise RuntimeError("country did not stick")
    field = phone_field(nodes)
    if field is None:
        raise RuntimeError("phone field is not on screen")
    shown = str(field.get("text") or "")
    if digits_of(shown) == digits:
        print("phone already entered", flush=True)
        await tap_after_keyboard(hand, allow_number_screen=True)
        return
    await hand.tap_xy(field["bounds"]["right"] - 28, (field["bounds"]["top"] + field["bounds"]["bottom"]) // 2, bounds=field["bounds"])
    await asyncio.sleep(0.4)
    await clear_wrong_phone(hand, digits_of(shown))
    await hand.type_pin(digits)
    fresh = await _play_nodes(hand.session)
    shown = "" if phone_field(fresh) is None else str(phone_field(fresh).get("text") or "")
    if digits_of(shown) != digits:
        print("phone field len", len(digits_of(shown)), "expected", len(digits), flush=True)
        raise RuntimeError("phone number was not entered")
    await tap_after_keyboard(hand, allow_number_screen=True)


def drop_refused_number(fivesim: FiveSim, nodes) -> None:
    blob = " ".join(_texts(nodes)).lower()
    if "cannot verify" not in blob and "another phone number" not in blob:
        return
    shown = "".join(char for char in " ".join(_texts(nodes)) if char.isdigit())
    print("number on screen was refused, buying another country", flush=True)
    visible = {_country_name(text) for text in _texts(nodes)}
    for country, query in COUNTRY_QUERY.items():
        if query in visible:
            SKIPPED.add(country)
            print("skip country", country, flush=True)
    for country in DIAL:
        if country in COUNTRY_QUERY:
            continue
        if country.replace("_", " ") in visible:
            SKIPPED.add(country)
            print("skip country", country, flush=True)
    payload = fivesim._get(
        "https://5sim.net/v1/user/orders?category=activation&limit=8",
        auth=True,
    )
    items = payload.get("Data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return
    for item in items:
        if item.get("product") != "snapchat":
            continue
        phone = "".join(char for char in str(item.get("phone") or "") if char.isdigit())
        tail = phone[-8:]
        if not tail or tail not in shown:
            continue
        country = country_from_phone(phone) or str(item.get("country") or "")
        if country:
            SKIPPED.add(country)
            print("skip country", country, flush=True)
        if item.get("id"):
            fivesim.cancel(item.get("id"))
            print("cancelled refused order", flush=True)


async def enter_phone(hand: Hand, nodes, fivesim: FiveSim, order):
    drop_refused_number(fivesim, nodes)
    if order is not None:
        phone = str(order.get("phone") or "")
        country = country_from_phone(phone) or str(order.get("country") or "")
        if country in skipped_countries():
            order = None
    if order is None:
        order = reusable_order(fivesim)
    if order is None:
        order = buy_number(fivesim)
    phone = str(order.get("phone") or "")
    labeled = str(order.get("country") or "")
    country = country_from_phone(phone) or labeled
    if country != labeled:
        print("number prefix", country, "label", labeled, flush=True)
        note_problem("phone", f"подпись номера {labeled or 'пусто'}, префикс {country}", "страну выбирать по цифрам номера, не по подписи 5sim")
    order["country"] = country
    await choose_country(hand, country)
    await type_national_number(hand, country, phone)
    return order


async def replace_whatsapp_number(hand: Hand, fivesim: FiveSim, order) -> None:
    print("code would be sent via WhatsApp, buying another country", flush=True)
    country = ""
    if order:
        country = country_from_phone(str(order.get("phone") or "")) or str(order.get("country") or "")
        if order.get("id"):
            fivesim.cancel(order.get("id"))
            print("cancelled the WhatsApp number", flush=True)
    if country:
        SKIPPED.add(country)
        print("skip country", country, flush=True)
    nodes = await _play_nodes(hand.session)
    if await in_app_back(hand, nodes):
        await asyncio.sleep(1)
        return
    await back_from_code_page(hand)


async def enter_code(hand: Hand, nodes, fivesim: FiveSim, order) -> None:
    if not order:
        raise RuntimeError("no number")
    blob = " ".join(_texts(nodes)).lower()
    if "sent via whatsapp" in blob or "code via whatsapp" in blob:
        raise RuntimeError("code goes to whatsapp")
    deadline = time.time() + 180
    code = None
    while time.time() < deadline:
        checked = fivesim.check(order.get("id"))
        from register import _sms_code
        code = _sms_code(checked if isinstance(checked, dict) else {})
        if code:
            break
        await asyncio.sleep(5)
    if not code:
        fivesim.cancel(order.get("id"))
        raise RuntimeError("no sms code")
    try:
        await fill_and_continue(hand, nodes, code)
    except RuntimeError as error:
        if str(error) == "code page already closed":
            return
        if "not entered" not in str(error):
            raise
        fresh = await _play_nodes(hand.session)
        blob = " ".join(_texts(fresh)).lower()
        if "enter the code" in blob or "we sent you" in blob or "verification code" in blob:
            raise
        print("code page already closed", flush=True)
        note_problem("sms", "страница кода закрылась до проверки цифр", "если на экране уже друзья, не набирать код повторно")


if __name__ == "__main__":
    asyncio.run(main())

# After a failed run, fix only the step named in the report. Check that step once.
# Show what changed. Push the script or a skill only after the person agrees.
