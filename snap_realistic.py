"""Play sign-in and Snapchat signup with the on-screen hand.

No input text, no keyevent, no input swipe, no monkey.
Play is opened by the market link, which the hand skill allows for that passage.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
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

from decisions import play_decision, snap_decision
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
from store import write_run
from telephort_sdk import TelephortClient

DEVICE = os.environ.get("SNAP_DEVICE", "")
SNAP = "com.snapchat.android"
RUNS = ROOT / "data" / "runs"

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


class Hand:
    def __init__(self, session, screen, rng: random.Random):
        self.session = session
        self.screen = screen
        self.rng = rng
        self.page = "letters"
        self.last_label = ""
        self.last_label_at = 0.0

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

    def same_press(self, label: str) -> bool:
        if label in ("Allow", "Don't allow", "Deny", "Not now"):
            return False
        return label == self.last_label and time.time() - self.last_label_at < 25

    def remember(self, label: str) -> None:
        self.last_label = label
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

    async def type_char(self, char: str) -> None:
        if char.isalpha():
            await self.letters()
            if char.isupper():
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

    async def type_text(self, value: str) -> None:
        for char in value:
            await self.type_char(char)

    async def type_pin(self, value: str) -> None:
        # The keys on the screen are the phone pad. Do not switch to ?123.
        for char in value:
            if char not in PAD:
                raise RuntimeError("pin has a character that is not on the phone pad")
            await self.tap_key(*PAD[char])
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
        await self.session.adb_shell("screencap /sdcard/kb.raw", timeout=25)
        header = await self.session.adb_shell("od -An -tu4 -N 12 /sdcard/kb.raw", timeout=15)
        parts = [int(item) for item in header.split()[:2]]
        width = parts[0] if parts else self.screen[0]
        height = parts[1] if len(parts) > 1 else self.screen[1]
        x = round(470 * width / 540)
        y = round(856 * height / 1200)
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
                self.page = "pad"
                return True
        self.page = "letters"
        return False

    async def checkmark(self) -> None:
        await self.between("submit")
        await self.tap_key(*CHECK)

    async def nav(self, which: str) -> None:
        width, height = self.screen
        top = height - 88
        bottom = height - 12
        if which == "back":
            left, right = 16, width // 3 - 16
        elif which == "home":
            left, right = width // 3 + 16, 2 * width // 3 - 16
        else:
            raise RuntimeError(which)
        x = left + self.rng.randrange(right - left)
        y = top + self.rng.randrange(bottom - top)
        print(f"nav {which}", flush=True)
        await self.tap_xy(x, y)

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


def load_local() -> dict:
    path = ROOT / "data" / "local.json"
    if path.exists():
        return json.loads(path.read_text())
    return {}


def load_play() -> tuple[str, str, str]:
    if os.environ.get("PLAY_STATE"):
        state_path = Path(os.environ["PLAY_STATE"])
    else:
        state_path = None
        for parent in (Path.cwd(), *Path.cwd().parents):
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


async def play_loop(hand: Hand, email: str, password: str, secret: str) -> None:
    nodes = await _play_nodes(hand.session)
    on_account = any("identifierId" in str(node.get("resource_id") or "") for node in nodes)
    # Reopening the store link leaves a sign-in page that is already on screen.
    if not on_account and play_decision(nodes)["op"] == "wait":
        await hand.session.adb_shell(
            f"am start -a android.intent.action.VIEW -d market://details?id={SNAP}",
            timeout=20,
        )
        print("opened Play by the store link, not by a finger on the icon", flush=True)
        await asyncio.sleep(3)
    for _ in range(40):
        nodes = await _play_nodes(hand.session)
        texts = _texts(nodes)
        if "Open" in texts and "Snapchat" in texts:
            print("play listing is on screen", flush=True)
            return
        decision = play_decision(nodes)
        print("play", decision["op"], decision.get("text") or "", _safe_label(nodes, email, password), flush=True)
        op = decision["op"]
        if op == "block":
            raise RuntimeError(decision.get("reason") or "play blocked")
        if op in ("signed_in", "installed"):
            return
        if op == "wait":
            await asyncio.sleep(2)
            continue
        if op == "tap":
            label = decision["text"]
            if hand.same_press(label):
                await hand.between("action")
                continue
            if label in ("Allow", "Don't allow", "Deny", "Not now"):
                await hand.between("dialog")
            await tap_named(hand, nodes, label, decision.get("class_name"))
            hand.remember(label)
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
            await hand.type_text(email)
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
                await hand.type_text(email)
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
            field = _edit_text(nodes)
            await hand.show_keyboard(field)
            length = max(_bullet_length(nodes), _field_length(nodes))
            if length:
                await hand.backspaces(length)
            await hand.type_text(password)
            fresh = await _play_nodes(hand.session)
            if max(_bullet_length(fresh), _field_length(fresh)) != len(password):
                raise RuntimeError("password length did not match")
            await submit_field(hand, fresh)
        elif op == "type_code":
            field = _edit_text(nodes)
            await hand.show_keyboard(field)
            length = _field_length(nodes)
            if length:
                print("clearing the code with the phone-pad delete key", flush=True)
                await hand.pad_delete(length)
            fresh = await _play_nodes(hand.session)
            if _field_length(fresh) and (_edit_text(fresh) or {}).get("text") not in ("", "Enter code"):
                raise RuntimeError("code field was not cleared")
            code = _totp(secret)
            print("typing the code on the phone pad", flush=True)
            await hand.type_pin(code)
            fresh = await _play_nodes(hand.session)
            shown = str((_edit_text(fresh) or {}).get("text") or "")
            if shown != code:
                raise RuntimeError("code was not entered as six digits")
            await submit_field(hand, fresh)
        elif op in ("hide_keyboard", "back_or_get_started"):
            await hand.nav("back")
        else:
            raise RuntimeError(f"unhandled play {op}")
        await hand.between("action")
    raise RuntimeError("play sign-in did not finish")


async def install_snap(hand: Hand) -> None:
    deadline = time.time() + 180
    tapped = False
    while time.time() < deadline:
        installed = await hand.session.adb_shell(f"pm path {SNAP}", timeout=20)
        nodes = await _play_nodes(hand.session)
        texts = _texts(nodes)
        print("install", "open" if "Open" in texts else "page", flush=True)
        if installed.startswith("package:") and "Open" in texts:
            await tap_named(hand, nodes, "Open")
            print("opened Snapchat from the Open button", flush=True)
            return
        if not tapped and "Install" in texts:
            await tap_named(hand, nodes, "Install")
            tapped = True
        await asyncio.sleep(5)
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
    record = {
        "run_number": next_run(),
        "device_id": DEVICE,
        "status_history": [],
        "notes": ["realistic hand"],
    }
    write_run(record["run_number"], {**record, "plan_name": plan["first"]})
    client = TelephortClient("https://demo.telephort.app/api", timeout=120)
    client.auth.login(local["telephort_email"], local["telephort_password"])
    client.set_team_id(client.teams.list_mine()["items"][0]["id"])
    session = await client.connect_device_automation(DEVICE, timeout=90)
    try:
        await session.initialize_adb(timeout=40)
        screen = await _screen_size(session)
        if not screen:
            raise RuntimeError("no screen size")
        print("screen", screen, flush=True)
        hand = Hand(session, screen, rng)
        await play_loop(hand, email, password, secret)
        await install_snap(hand)
        print("play done, snapchat opened", "run", record["run_number"], flush=True)
        await snap_loop(hand, plan, record, local)
    finally:
        await session.close()


async def snap_loop(hand: Hand, plan: dict, record: dict, local: dict) -> None:
    fivesim = FiveSim(local.get("fivesim_token") or "")
    order = None
    await asyncio.sleep(1)
    for _ in range(70):
        nodes = await _play_nodes(hand.session)
        decision = snap_decision(_texts(nodes), plan, nodes)
        print("snap", decision["op"], decision.get("text") or "", _safe_label(nodes, "", plan["password"]), flush=True)
        op = decision["op"]
        if op == "block":
            raise RuntimeError(decision.get("reason") or "snap blocked")
        if op == "feed":
            print("account reached the feed", flush=True)
            return
        if op == "tap":
            label = decision["text"]
            if hand.same_press(label):
                await hand.between("action")
                continue
            if label in ("Allow", "Don't allow", "Deny", "Not now"):
                await hand.between("dialog")
            await tap_named(hand, nodes, label, decision.get("class_name"))
            hand.remember(label)
        elif op == "tap_bounds":
            await hand.tap_node({"bounds": decision["bounds"]})
        elif op == "type_name":
            await type_name(hand, nodes, plan)
        elif op == "birthday":
            await birthday(hand, nodes, plan)
        elif op == "type_username":
            shown = field_text(nodes)
            if shown and "available" in " ".join(_texts(nodes)).lower():
                plan["username"] = shown
                keep_password(plan, hand.rng)
            await fill_and_continue(hand, nodes, plan["username"])
        elif op == "type_password":
            await fill_and_continue(hand, nodes, plan["password"])
        elif op == "username_taken":
            await extend_username(hand, nodes, plan)
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
        elif op == "code_rejected":
            raise RuntimeError("sms code rejected")
        elif op == "refusal":
            raise RuntimeError("phone refused")
        elif op == "type_phone":
            order = await enter_phone(hand, nodes, fivesim, order)
        elif op == "type_sms":
            await enter_code(hand, nodes, fivesim, order)
        elif op == "unknown":
            await asyncio.sleep(2)
            continue
        else:
            raise RuntimeError(f"unhandled snap {op}")
        await hand.between("action")
    raise RuntimeError("signup did not finish")


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
    raise RuntimeError("checkmark did not close the keyboard")


async def tap_after_keyboard(hand: Hand, label: str | None = None) -> None:
    await close_keyboard(hand)
    nodes = await _play_nodes(hand.session)
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
        await hand.type_text(target)
        fresh = await _play_nodes(hand.session)
        if field_text(fresh) != target:
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
    await hand.type_text(extra)
    fresh = await _play_nodes(hand.session)
    typed = field_text(fresh)
    if not typed.endswith(extra):
        raise RuntimeError("digits were not added at the end of the username")
    plan["username"] = typed
    keep_password(plan, hand.rng)
    print("username extended", "len", len(typed), flush=True)


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
    if hand.page == "pad" and value.isdigit():
        await hand.type_pin(value)
    else:
        await hand.type_text(value)
    fresh = await _play_nodes(hand.session)
    shown = field_text(fresh)
    if value.isdigit():
        if digits_of(shown) != value:
            raise RuntimeError("digits were not entered once")
    elif _bullet_length(fresh) == len(value) or shown == value:
        return
    else:
        raise RuntimeError("field text was not entered once")


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


async def birthday(hand: Hand, nodes, plan: dict) -> None:
    from register import _column, _visible_year

    async def wheel(kind: str, direction: str, scale: float = 1, swipe: bool = False) -> bool:
        fresh = await _play_nodes(hand.session)
        node = _column(fresh, kind)
        if node is None or not node.get("bounds"):
            print("no wheel", kind, flush=True)
            return False
        bounds = node["bounds"]
        row = max(48, bounds["bottom"] - bounds["top"])
        # The selected row sits just above the nav bar. A stroke that starts
        # there and goes down leaves the wheel. Stay on the three visible rows.
        top = max(80, bounds["top"] - row + 8)
        bottom = min(hand.screen[1] - 100, bounds["bottom"] + row - 8)
        x = bounds["left"] + hand.rng.randrange(max(1, bounds["right"] - bounds["left"]))
        if direction == "down":
            start, end = (x, top), (x, bottom)
        else:
            start, end = (x, bottom), (x, top)
        if scale != 1:
            start = (int(start[0] * scale), int(start[1] * scale))
            end = (int(end[0] * scale), int(end[1] * scale))
        print("swipe" if swipe else "finger", kind, direction, flush=True)
        await hand.finger(start, end, swipe=swipe)
        await asyncio.sleep(0.7 if swipe else 0.45)
        return True

    if not plan.get("sides_scrolled"):
        await wheel("month", plan["month_direction"])
        await wheel("day", plan["day_direction"])
        plan["sides_scrolled"] = True
    fresh = await _play_nodes(hand.session)
    year = _visible_year(fresh)
    print("birthday year", year, flush=True)
    if year is not None and 1970 <= year <= 2006:
        print("tap Continue on the birthday screen", flush=True)
        await tap_named(hand, fresh, "Continue")
        return
    before = year
    await wheel("year", "down", swipe=True)
    fresh = await _play_nodes(hand.session)
    after = _visible_year(fresh)
    print("birthday year", after, flush=True)
    if after == before:
        raise RuntimeError("the downward swipe did not move the year")
    if before is not None and after is not None and after > before:
        raise RuntimeError("the downward swipe moved the year upward")


async def enter_phone(hand: Hand, nodes, fivesim: FiveSim, order):
    if order is None:
        countries = prepared_countries(fivesim.prices())
        if not countries:
            raise RuntimeError("no verification number in stock")
        order = fivesim.buy(countries[0])
        print("bought a number", countries[0], flush=True)
    phone = str(order.get("phone") or "")
    digits = "".join(char for char in phone if char.isdigit())
    await fill_and_continue(hand, nodes, digits)
    return order


async def enter_code(hand: Hand, nodes, fivesim: FiveSim, order) -> None:
    if not order:
        raise RuntimeError("no number")
    deadline = time.time() + 120
    code = None
    while time.time() < deadline:
        checked = fivesim.check(order.get("id"))
        from register import _sms_code
        code = _sms_code(checked if isinstance(checked, dict) else {})
        if code:
            break
        await asyncio.sleep(5)
    if not code:
        raise RuntimeError("no sms code")
    await fill_and_continue(hand, nodes, code)


if __name__ == "__main__":
    asyncio.run(main())
