"""Sign into Play, install Snapchat, and register one account on a running device."""

from __future__ import annotations

import asyncio
import hashlib
import random
import hmac
import re
import struct
import time
import base64
import xml.etree.ElementTree as ET
from datetime import date

from decisions import norm, play_decision, snap_decision, _welcome_signup
from fivesim import FiveSim, choose_country, prepared_countries
from identity import make_plan, password_rejected, username_rejected
from policy import CODE_WAIT_START_SECONDS, PURCHASE_WAIT_START_SECONDS, Misses
from store import save_account, write_run

SNAP_PACKAGE = "com.snapchat.android"
MONTHS = {
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
}


class RunStopped(Exception):
    def __init__(self, outcome: str, reason: str, details: list[str] | None = None) -> None:
        super().__init__(reason)
        self.outcome = outcome
        self.reason = reason
        self.details = details or []


async def register_snapchat(client, device_id: str, record: dict, local: dict) -> int:
    saved = record.get("choices") or {}
    if saved.get("username") and saved.get("password"):
        plan = dict(saved)
        plan.setdefault("year", plan.get("year_target", 1990))
        plan.setdefault("username_tries", 1)
        plan.setdefault("password_tries", 1)
        plan.setdefault("other_name", "Noah")
    else:
        plan = make_plan()
    record["choices"] = {
        "first": plan["first"],
        "last": plan["last"],
        "year_target": plan["year"],
        "month_scrolls": plan["month_scrolls"],
        "month_direction": plan["month_direction"],
        "day_scrolls": plan["day_scrolls"],
        "day_direction": plan["day_direction"],
        "notifications": plan["notifications"],
        "bitmoji": plan["bitmoji"],
        "username_pattern": plan["username_pattern"],
        "password_pattern": plan["password_pattern"],
        "username": plan["username"],
        "password": plan["password"],
    }
    record["verification_numbers"] = []
    record["steps"] = []
    record["outcome"] = "signing_up"
    write_run(record["run_number"], record)
    email, password, secret = _split_play(local.get("play_account") or "")
    session = await client.connect_device_automation(device_id, timeout=60)
    try:
        await session.initialize_adb(timeout=40)
        screen = await _screen_size(session)
        await _sign_in_and_install(session, record, email, password, secret, screen)
        await _signup(session, client, device_id, record, plan, local, screen)
    except RunStopped as stopped:
        record["outcome"] = stopped.outcome
        record["reason"] = stopped.reason
        if stopped.details:
            record["screen"] = stopped.details[:40]
        write_run(record["run_number"], record)
        print(f"{stopped.outcome}: {stopped.reason}", flush=True)
        return 1
    finally:
        await session.close()
    return 0


async def _sign_in_and_install(session, record, email, password, secret, screen) -> None:
    installed = await session.adb_shell(f"pm path {SNAP_PACKAGE}", timeout=20)
    if installed.startswith("package:"):
        print("snapchat already installed", flush=True)
        return
    current = " ".join(_texts(await _play_nodes(session))).lower()
    if not any(phrase in current for phrase in (
        "2-step verification",
        "enter code",
        "show password",
        "use your fingerprint",
        "use a passkey",
        "google authenticator",
        "verification code from",
        "account recovery",
        "i agree",
        "terms of service",
        "are you trying to sign in",
    )):
        await _open_snap_page(session)
        await asyncio.sleep(2)
    email_typed = False
    password_typed = False
    code_typed = False
    waited_out = 0
    for _ in range(40):
        nodes = await _play_nodes(session)
        decision = play_decision(nodes)
        if decision["op"] != "type_password":
            password_typed = False
        if decision["op"] != "type_code":
            code_typed = False
        _note(record, decision["op"])
        print(f"play {decision['op']}: {_safe_label(nodes, email)}", flush=True)
        if decision["op"] == "block":
            raise RunStopped("blocked", decision["reason"], _texts(nodes))
        if decision["op"] == "signed_in":
            break
        if decision["op"] == "installed":
            return
        if decision["op"] == "tap" and decision["text"] == "Install":
            await _tap(session, nodes, decision, screen)
            break
        if decision["op"] == "type_email":
            if email_typed:
                raise RunStopped("blocked", "email page stayed open", _texts(nodes))
            shown = " ".join(_texts(nodes))
            if shown.count(email) != 1 or "\\" in shown:
                field = _edit_text(nodes)
                if field:
                    await _tap_node(session, field, screen)
                await _clear_field(session)
                await _input_text(session, email)
                await asyncio.sleep(1)
                shown = " ".join(_texts(await _play_nodes(session)))
                if shown.count(email) != 1 or "\\" in shown:
                    raise RunStopped("blocked", "email was not entered once", [])
            email_typed = True
            await _submit(session, await _play_nodes(session), screen)
        elif decision["op"] == "type_password":
            blob = " ".join(_texts(nodes)).lower()
            if "loading" in blob or "indeterminate" in blob:
                await asyncio.sleep(1)
                continue
            if _bullet_length(nodes) != len(password) and _field_length(nodes) != len(password):
                field = _edit_text(nodes)
                if field:
                    await _tap_node(session, field, screen)
                await _clear_field(session)
                await _input_text(session, password)
                await asyncio.sleep(0.8)
                checked = await _play_nodes(session)
                if _bullet_length(checked) != len(password) and _field_length(checked) != len(password):
                    await _clear_field(session)
                    await _input_text(session, password)
                    await asyncio.sleep(0.8)
                    checked = await _play_nodes(session)
                    if _bullet_length(checked) != len(password) and _field_length(checked) != len(password):
                        raise RunStopped("blocked", "password field length did not match", [])
                password_typed = True
            fresh = await _play_nodes(session)
            nxt = _find(fresh, "Next", "android.widget.Button")
            if nxt and not _needs_reveal(nxt, screen):
                await _tap(session, fresh, {"op": "tap", "text": "Next", "class_name": "android.widget.Button"}, screen)
            else:
                await session.adb_shell("input keyevent 66", timeout=15)
        elif decision["op"] == "type_code":
            fresh = await _fill_code(session, nodes, secret, screen)
            await _submit_code(session, fresh, screen)
            code_typed = True
        elif decision["op"] == "hide_keyboard":
            await session.adb_shell("input keyevent 4", timeout=15)
            await asyncio.sleep(0.6)
        elif decision["op"] == "back_or_get_started":
            await _back_or_get_started(session, screen)
        elif decision["op"] == "tap":
            if decision["text"] == "Wait":
                waited_out += 1
                if waited_out >= 3 and _find(nodes, "Close app", None):
                    await _tap(session, nodes, {"op": "tap", "text": "Close app"}, screen)
                    await asyncio.sleep(1)
                    await _open_snap_page(session)
                    waited_out = 0
                    await asyncio.sleep(2)
                    continue
            else:
                waited_out = 0
            await _tap(session, nodes, decision, screen)
        await asyncio.sleep(2)
    else:
        raise RunStopped("blocked", "play sign-in did not finish", [])

    await _install_snapchat(session, record, password, screen)


async def _install_snapchat(session, record, password, screen) -> None:
    await _open_snap_page(session)
    await asyncio.sleep(2)
    tapped = False
    deadline = time.time() + 180
    while time.time() < deadline:
        installed = await session.adb_shell(f"pm path {SNAP_PACKAGE}", timeout=20)
        if installed.startswith("package:"):
            page = await _play_nodes(session)
            if any(norm(node.get("text") or "") == "Open" for node in page):
                print("snapchat installed", flush=True)
                return
        if not tapped or int(deadline - time.time()) % 20 < 3:
            nodes = await _play_nodes(session)
            if any(norm(node.get("text") or "") == "Enter a password" for node in nodes) or any(
                "Show password" == norm(node.get("text") or "") for node in nodes
            ):
                field = _edit_text(nodes)
                if field:
                    await _tap_node(session, field, screen)
                await _clear_field(session)
                await _input_text(session, password)
                await _submit(session, nodes, screen)
            install = play_decision(nodes)
            if install.get("op") == "back_or_get_started":
                await _back_or_get_started(session, screen)
            elif install.get("op") == "tap" and install.get("text") in ("Skip", "Continue"):
                await _tap_or_reveal(session, nodes, install, screen)
                _note(record, install["text"].lower())
            elif install.get("text") == "Install" and not tapped:
                await _tap(session, nodes, install, screen)
                tapped = True
                _note(record, "install")
        await asyncio.sleep(5)
    raise RunStopped("blocked", "snapchat install did not finish", [])


async def _signup(session, client, device_id, record, plan, local, screen) -> None:
    await session.adb_shell(
        f"monkey -p {SNAP_PACKAGE} -c android.intent.category.LAUNCHER 1",
        timeout=30,
    )
    await asyncio.sleep(3)
    misses = Misses()
    fivesim = FiveSim(local.get("fivesim_token") or "")
    order = None
    unknown = 0
    stuck_key = None
    stuck = 0
    for _ in range(80):
        nodes, _source = await _snap_nodes(session)
        decision = snap_decision(_texts(nodes), plan, nodes)
        key = (decision["op"], decision.get("text"), str(decision.get("bounds") or ""))
        print(f"snap {decision['op']} {decision.get('text') or ''}: {_safe_label(nodes, '', plan.get('password') or '')}", flush=True)
        if decision["op"] == "unknown":
            unknown += 1
            if unknown >= 6:
                raise RunStopped("failed", "unclear screen", _texts(nodes))
            await asyncio.sleep(2)
            continue
        unknown = 0
        if key == stuck_key and decision["op"] not in ("birthday", "type_sms", "type_phone"):
            stuck += 1
            if stuck >= 4:
                raise RunStopped("failed", "screen did not change", _texts(nodes))
        else:
            stuck_key = key
            stuck = 0
        _note(record, decision["op"])
        if plan.get("code_submitted") and decision["op"] not in ("type_sms", "code_rejected", "unknown"):
            plan["code_accepted"] = True
            _number_outcome(record, order, "accepted")
        if decision["op"] == "block":
            raise RunStopped("blocked", decision["reason"], _texts(nodes))
        if decision["op"] == "feed":
            _save(record, plan, order)
            _remove(client, device_id)
            record["outcome"] = "account"
            write_run(record["run_number"], record)
            print("account saved, device removed", flush=True)
            return
        if decision["op"] == "tap":
            await _tap(session, nodes, decision, screen, prefer_adb=_source_adb(nodes))
        elif decision["op"] == "tap_bounds":
            await _tap_node(session, {"bounds": decision["bounds"], "source": "ui"}, screen)
        elif decision["op"] == "type_name":
            await _type_name(session, nodes, plan, screen)
        elif decision["op"] == "birthday":
            await _birthday(session, nodes, plan, record, screen)
        elif decision["op"] == "type_username":
            await _replace_field(session, nodes, plan["username"], screen)
            _choice(record, plan)
            await _submit(session, nodes, screen)
        elif decision["op"] == "username_taken":
            if username_rejected(plan, __import__("random").Random()) is None:
                raise RunStopped("blocked", "usernames taken", _texts(nodes))
            _choice(record, plan)
            await _replace_field(session, nodes, plan["username"], screen)
            await _submit(session, nodes, screen)
        elif decision["op"] == "type_password":
            await _replace_field(session, nodes, plan["password"], screen)
            await _submit(session, nodes, screen)
        elif decision["op"] == "password_rejected":
            if password_rejected(plan, __import__("random").Random()) is None:
                raise RunStopped("blocked", "passwords rejected", _texts(nodes))
            _choice(record, plan)
            await _replace_field(session, nodes, plan["password"], screen)
            await _submit(session, nodes, screen)
        elif decision["op"] == "type_phone":
            order = await _enter_phone(session, nodes, plan, record, fivesim, screen, order)
        elif decision["op"] == "type_sms":
            order = await _enter_code(session, nodes, plan, record, fivesim, misses, order, screen)
        elif decision["op"] == "code_rejected":
            spent = await _reject_code(session, nodes, plan, record, fivesim, misses, order, screen)
            if misses.stopped:
                raise RunStopped("failed", "code rejected", _texts(nodes))
            if spent:
                await session.adb_shell("input keyevent 4", timeout=15)
                order = await _replace_order(record, fivesim, nodes)
        elif decision["op"] == "refusal":
            misses.refusal()
            _number_outcome(record, order, "refused")
            if order:
                fivesim.cancel(order.get("id"))
            order = None
            if misses.stopped:
                raise RunStopped("failed", "snapchat will not take a number", _texts(nodes))
        elif decision["op"] == "pick_bitmoji":
            await _pick_bitmoji(session, nodes, screen)
        await asyncio.sleep(1.5)
    raise RunStopped("failed", "unclear screen", [])


async def _enter_phone(session, nodes, plan, record, fivesim, screen, order):
    if order is None:
        order = _buy(fivesim, record)
        if order is None:
            raise RunStopped("failed", "no number", _texts(nodes))
        record["verification_numbers"].append({
            "country": order.get("country"),
            "phone": order.get("phone"),
            "outcome": "pending",
        })
        write_run(record["run_number"], record)
    phone = str(order.get("phone") or "")
    await _replace_field(session, nodes, phone, screen)
    await _submit(session, nodes, screen)
    plan["phone_entered_at"] = time.time()
    return order


async def _enter_code(session, nodes, plan, record, fivesim, misses, order, screen):
    if order is None:
        raise RunStopped("failed", "no number", _texts(nodes))
    if plan.get("entered_code"):
        await asyncio.sleep(2)
        return order
    code, seen = await _wait_for_code(session, fivesim, order, plan)
    if seen and seen["op"] == "block":
        raise RunStopped("blocked", seen["reason"], [])
    if seen and seen["op"] == "refusal":
        misses.refusal()
        _number_outcome(record, order, "refused")
        fivesim.cancel(order.get("id"))
        if misses.stopped:
            raise RunStopped("failed", "snapchat will not take a number", [])
        await session.adb_shell("input keyevent 4", timeout=15)
        return await _replace_order(record, fivesim, nodes)
    if not code:
        misses.silence()
        _number_outcome(record, order, "silence")
        fivesim.cancel(order.get("id"))
        plan["entered_code"] = None
        plan["phone_entered_at"] = None
        write_run(record["run_number"], record)
        if misses.stopped:
            raise RunStopped("failed", "no code", _texts(nodes))
        await session.adb_shell("input keyevent 4", timeout=15)
        return await _replace_order(record, fivesim, nodes)
    plan["received_code"] = code
    plan["entered_code"] = code
    plan["code_submitted"] = True
    plan["code_accepted"] = True
    await _replace_field(session, nodes, code, screen)
    await _submit(session, nodes, screen)
    return order


async def _replace_order(record, fivesim, nodes):
    replacement = _buy(fivesim, record)
    if replacement is None:
        raise RunStopped("failed", "no number", _texts(nodes))
    record["verification_numbers"].append({
        "country": replacement.get("country"),
        "phone": replacement.get("phone"),
        "outcome": "pending",
    })
    write_run(record["run_number"], record)
    return replacement


async def _wait_for_code(session, fivesim, order, plan):
    started = plan.get("phone_entered_at") or time.time()
    plan["phone_entered_at"] = started
    deadline = started + CODE_WAIT_START_SECONDS
    while time.time() < deadline:
        payload = fivesim.check(order.get("id"))
        code = _sms_code(payload)
        if code:
            return code, None
        nodes, _source = await _snap_nodes(session)
        decision = snap_decision(_texts(nodes), plan)
        if decision["op"] in ("refusal", "block"):
            return None, decision
        await asyncio.sleep(5)
    return None, None


async def _reject_code(session, nodes, plan, record, fivesim, misses, order, screen) -> bool:
    received = plan.get("received_code") or ""
    entered = plan.get("entered_code") or ""
    if received and entered != received:
        plan["entered_code"] = received
        await _replace_field(session, nodes, received, screen)
        await _submit(session, nodes, screen)
        return False
    misses.rejected_code()
    _number_outcome(record, order, "rejected_code")
    if order:
        fivesim.cancel(order.get("id"))
    plan["code_accepted"] = False
    plan["code_submitted"] = False
    plan["entered_code"] = None
    plan["received_code"] = None
    plan["phone_entered_at"] = None
    write_run(record["run_number"], record)
    return True


def _buy(fivesim: FiveSim, record: dict) -> dict | None:
    started = time.time()
    try:
        offers = fivesim.prices()
    except Exception as error:
        print(f"number prices: {error}", flush=True)
        offers = []
    prepared = prepared_countries(offers) or ["poland", "england", "netherlands", "spain", "portugal"]
    record["prepared_countries"] = prepared
    skipped: set[str] = set()
    while time.time() - started < PURCHASE_WAIT_START_SECONDS:
        country = choose_country([offer for offer in offers if offer["country"] not in skipped])
        if not country:
            break
        order = _buy_one(fivesim, country)
        if order:
            return order
        skipped.add(country)
    for country in prepared:
        if country in skipped:
            continue
        order = _buy_one(fivesim, country)
        if order:
            return order
        skipped.add(country)
    try:
        fresh = fivesim.prices()
    except Exception:
        fresh = []
    for country in prepared_countries([offer for offer in fresh if offer["country"] not in skipped]):
        order = _buy_one(fivesim, country)
        if order:
            return order
    return None


def _buy_one(fivesim: FiveSim, country: str) -> dict | None:
    try:
        order = fivesim.buy(country)
    except Exception as error:
        print(f"no number in {country}: {error}", flush=True)
        return None
    order["country"] = order.get("country") or country
    print(f"bought a {order['country']} number", flush=True)
    return order


def _save(record: dict, plan: dict, order: dict | None) -> None:
    phone = ""
    country = ""
    if order:
        phone = str(order.get("phone") or "")
        country = str(order.get("country") or "")
    account = {
        "username": plan["username"],
        "password": plan["password"],
        "name": f"{plan['first']} {plan['last']}",
        "birthday_year": record.get("birthday_year") or plan["year"],
        "month_scrolls": plan["month_scrolls"],
        "month_direction": plan["month_direction"],
        "day_scrolls": plan["day_scrolls"],
        "day_direction": plan["day_direction"],
        "verification_number": phone,
        "verification_country": country,
        "internet": record.get("internet"),
        "country": record.get("country"),
        "city": record.get("city"),
        "registered_on": date.today().isoformat(),
        "notifications": plan["notifications"],
        "bitmoji": plan["bitmoji"],
    }
    save_account(account)
    record["account"] = account


def _remove(client, device_id: str) -> None:
    from campaign import remove_device

    remove_device(client, device_id)


async def _birthday(session, nodes, plan, record, screen) -> None:
    if not plan.get("sides_scrolled"):
        await _swipe_kind(session, nodes, "month", plan["month_direction"], plan["month_scrolls"], screen)
        await _swipe_kind(session, nodes, "day", plan["day_direction"], plan["day_scrolls"], screen)
        plan["sides_scrolled"] = True
    year = _visible_year(nodes)
    print(f"birthday year {year}", flush=True)
    if year is None or not 1970 <= year <= 2006:
        direction = "down" if year is None or year > 2006 else "up"
        await _swipe_kind(session, nodes, "year", direction, 1, screen)
        return
    record["birthday_year"] = year
    write_run(record["run_number"], record)
    await _submit(session, nodes, screen)


async def _type_name(session, nodes, plan, screen) -> None:
    fields = _edit_texts(nodes)
    if len(fields) >= 2:
        await _tap_node(session, fields[0], screen)
        await _clear_field(session)
        await _input_text(session, plan["first"])
        await _tap_node(session, fields[1], screen)
        await _clear_field(session)
        await _input_text(session, plan["last"])
    else:
        await _replace_field(session, nodes, f"{plan['first']} {plan['last']}", screen)
    await _submit(session, nodes, screen)


async def _pick_bitmoji(session, nodes, screen) -> None:
    skip = {"Skip", "Not now", "Continue", "Next"}
    for node in nodes:
        text = norm(node.get("text") or "")
        if text and text not in skip and node.get("clickable") and node.get("bounds"):
            await _tap_node(session, node, screen)
            return
    await _submit(session, nodes, screen)


async def _replace_field(session, nodes, value: str, screen) -> None:
    field = _edit_text(nodes)
    if field:
        await _tap_node(session, field, screen)
    await _clear_field(session)
    await _input_text(session, value)


async def _back_or_get_started(session, screen) -> None:
    await session.adb_shell("input keyevent 4", timeout=15)
    await asyncio.sleep(0.5)
    nodes = await _play_nodes(session)
    if "link your google services" not in " ".join(_texts(nodes)).lower():
        return
    await asyncio.sleep(2)
    nodes = await _play_nodes(session)
    await _tap(session, nodes, {"op": "tap", "text": "Get started"}, screen)
    await asyncio.sleep(1)
    await session.adb_shell("input keyevent 4", timeout=15)


async def _keyboard_shown(session) -> bool:
    raw = await session.adb_shell("dumpsys input_method", timeout=15)
    return "mInputShown=true" in raw


async def _hide_keyboard(session) -> None:
    if not await _keyboard_shown(session):
        return
    await session.adb_shell("input keyevent 4", timeout=15)
    await asyncio.sleep(0.6)


def _needs_reveal(node, screen) -> bool:
    if node is None or not node.get("bounds"):
        return True
    if not screen:
        return False
    _x, y = _point(node["bounds"], screen)
    return y > int(screen[1] * 0.85)


async def _tap_or_reveal(session, nodes, decision, screen) -> None:
    node = _find(nodes, decision["text"], decision.get("class_name"))
    if _needs_reveal(node, screen):
        await session.adb_shell("input keyevent 4", timeout=15)
        await asyncio.sleep(0.6)
        nodes = await _play_nodes(session)
    await _tap(session, nodes, decision, screen)


async def _submit(session, nodes, screen) -> None:
    buttons = (
        ("Agree and Continue", None),
        ("Next", "android.widget.Button"),
        ("Continue", "android.widget.Button"),
        ("Continue", None),
        ("Next", None),
    )
    for text, class_name in buttons:
        if _find(nodes, text, class_name):
            decision = {"op": "tap", "text": text}
            if class_name:
                decision["class_name"] = class_name
            await _tap_or_reveal(session, nodes, decision, screen)
            return
    await session.adb_shell("input keyevent 4", timeout=15)
    await asyncio.sleep(0.6)
    nodes = await _play_nodes(session)
    for text, class_name in buttons:
        if _find(nodes, text, class_name):
            decision = {"op": "tap", "text": text}
            if class_name:
                decision["class_name"] = class_name
            await _tap(session, nodes, decision, screen)
            return
    await session.adb_shell("input keyevent 66", timeout=15)


async def _tap(session, nodes, decision, screen, prefer_adb: bool = True) -> None:
    node = _find(nodes, decision["text"], decision.get("class_name"))
    if node is None:
        nodes = await _play_nodes(session)
        node = _find(nodes, decision["text"], decision.get("class_name"))
        prefer_adb = True
    if node is None:
        raise RunStopped("blocked", f"missing {decision['text']}", _texts(nodes))
    await _tap_node(session, node, screen, prefer_adb=prefer_adb)


async def _tap_node(session, node, screen, prefer_adb: bool = True) -> None:
    bounds = node.get("bounds")
    if not bounds:
        raise RunStopped("blocked", "target has no bounds", [])
    x, y = _point(bounds, screen)
    if prefer_adb or node.get("source") == "ui":
        await session.adb_shell(f"input tap {x} {y}", timeout=15)
        return
    await session.action_tap(x, y)


async def _swipe_kind(session, nodes, kind: str, direction: str, times: int, screen) -> None:
    node = _column(nodes, kind)
    if node is None or not node.get("bounds"):
        return
    bounds = node["bounds"]
    x, y = _point(bounds, screen)
    for _ in range(times):
        y2 = y - 220 if direction == "up" else y + 220
        await session.adb_shell(f"input swipe {x} {y} {x} {y2} 180", timeout=15)
        await asyncio.sleep(0.4)


def _column(nodes, kind: str):
    if kind == "year":
        return _centered(nodes, lambda text: bool(re.fullmatch(r"(19|20)\d\d", text)))
    if kind == "month":
        return _centered(nodes, lambda text: text.lower() in MONTHS)
    return _centered(nodes, lambda text: bool(re.fullmatch(r"0?[1-9]|[12]\d|3[01]", text)))


def _centered(nodes, matches):
    found = []
    for node in nodes:
        text = norm(node.get("text") or "")
        bounds = node.get("bounds")
        if matches(text) and bounds:
            found.append(node)
    if not found:
        return None
    found.sort(key=lambda node: node["bounds"]["top"])
    return found[len(found) // 2]


def _usable_years(nodes) -> bool:
    return _centered(nodes, lambda text: bool(re.fullmatch(r"(19|20)\d\d", text))) is not None


def _visible_year(nodes) -> int | None:
    node = _column(nodes, "year")
    if node is None:
        return None
    return int(norm(node.get("text") or ""))


async def _play_nodes(session) -> list[dict]:
    xml = await _dump(session)
    nodes = _parse_ui(xml)
    for node in nodes:
        node["source"] = "ui"
    return nodes


async def _snap_nodes(session):
    a11y = []
    try:
        tree = await session.accessibility_tree(timeout=20)
        root = tree.get("tree") if isinstance(tree, dict) else None
        a11y = _flatten_a11y(root or {})
    except Exception as error:
        print(f"accessibility unread: {type(error).__name__}", flush=True)
    ui = await _play_nodes(session)
    if _usable_years(ui) and not _usable_years(a11y):
        return ui, "ui"
    visible = {"Sign Up", "Sign up", "Continue", "Next", "First Name", "Username"}
    a11y_texts = set(_texts(a11y))
    ui_texts = set(_texts(ui))
    if (visible & ui_texts or _welcome_signup(ui)) and not (visible & a11y_texts or _welcome_signup(a11y)):
        return ui, "ui"
    if a11y_texts:
        return a11y, "a11y"
    return ui, "ui"


def _source_adb(nodes) -> bool:
    return bool(nodes) and nodes[0].get("source") == "ui"


async def _dump(session) -> str:
    remote = "/data/local/tmp/snap-ui.xml"
    for _ in range(2):
        await session.adb_shell(f"uiautomator dump {remote}", timeout=40)
        xml = await session.adb_shell(f"cat {remote}", timeout=20)
        if "<node" in xml:
            return xml
        await asyncio.sleep(1)
    return ""


async def _open_snap_page(session) -> None:
    await session.adb_shell(
        f"am start -a android.intent.action.VIEW -d market://details?id={SNAP_PACKAGE}",
        timeout=20,
    )


async def _screen_size(session):
    raw = await session.adb_shell("wm size", timeout=15)
    match = re.search(r"(\d+)x(\d+)", raw)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


async def _input_text(session, value: str) -> None:
    encoded = value.replace(" ", "%s")
    await session.adb_shell(f"input text {encoded}", timeout=20)


def _code_rejected(nodes) -> bool:
    blob = " ".join(norm(node.get("text") or "") for node in nodes).lower()
    return "wrong code" in blob or "incorrect code" in blob


def _pin_length(nodes) -> int:
    for node in nodes:
        if "totpPin" not in str(node.get("resource_id") or ""):
            continue
        return len(re.sub(r"\D", "", node.get("text") or ""))
    for node in nodes:
        if "EditText" not in str(node.get("class_name") or ""):
            continue
        raw = re.sub(r"\s", "", node.get("text") or "")
        digits = re.sub(r"\D", "", raw)
        if digits and digits == raw:
            return len(digits)
    return 0


def _code_field(nodes):
    for node in nodes:
        if "totpPin" in str(node.get("resource_id") or "") and node.get("bounds"):
            return node
    return _edit_text(nodes)


async def _fill_code(session, nodes, secret: str, screen):
    rejected = _code_rejected(nodes)
    if _pin_length(nodes) == 6 and not rejected:
        return nodes
    field = _code_field(nodes)
    if field:
        await _tap_node(session, field, screen)
        await asyncio.sleep(0.3)
    if rejected or _pin_length(nodes):
        await _clear_field(session)
    await _input_text(session, _totp(secret, force_next=rejected))
    await asyncio.sleep(0.5)
    fresh = await _play_nodes(session)
    if _pin_length(fresh) == 6:
        return fresh
    field = _code_field(fresh) or field
    if field:
        await _tap_node(session, field, screen)
        await asyncio.sleep(0.3)
    await _clear_field(session)
    digits = _totp(secret)
    keys = " ".join(str(7 + int(char)) for char in digits if char.isdigit())
    if keys:
        await session.adb_shell(f"input keyevent {keys}", timeout=20)
        await asyncio.sleep(0.4)
    return await _play_nodes(session)


async def _submit_code(session, nodes, screen) -> None:
    if _pin_length(nodes) != 6:
        return
    # On 540x1200, Next sits under the keyboard. Enter submits the focused field.
    # Tap Next only when the keyboard is down. Do not press Back.
    if await _keyboard_shown(session):
        await session.adb_shell("input keyevent 66", timeout=15)
        return
    if _find(nodes, "Next", "android.widget.Button"):
        await _tap(session, nodes, {"op": "tap", "text": "Next", "class_name": "android.widget.Button"}, screen)
        return
    await session.adb_shell("input keyevent 66", timeout=15)


async def _clear_field(session) -> None:
    await session.adb_shell("input keyevent 123", timeout=15)
    await session.adb_shell("input keyevent " + " ".join(["67"] * 32), timeout=15)


def _parse_ui(xml: str) -> list[dict]:
    nodes = []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []

    def walk(elem, ancestors: list[dict]) -> None:
        attrs = elem.attrib
        bounds = _bounds(attrs.get("bounds"))
        node = {
            "text": attrs.get("text") or attrs.get("content-desc") or "",
            "resource_id": attrs.get("resource-id") or "",
            "class_name": attrs.get("class") or "",
            "bounds": bounds,
            "clickable": attrs.get("clickable") == "true",
        }
        if bounds is None:
            for ancestor in reversed(ancestors):
                if ancestor.get("bounds"):
                    node["bounds"] = ancestor["bounds"]
                    node["clickable"] = True
                    break
        nodes.append(node)
        for child in list(elem):
            walk(child, ancestors + [node])

    walk(root, [])
    return nodes


def _flatten_a11y(root: dict) -> list[dict]:
    nodes = []

    def visit(node: dict) -> None:
        bounds = node.get("bounds") if isinstance(node, dict) else None
        box = None
        if isinstance(bounds, dict) and all(key in bounds for key in ("left", "top", "right", "bottom")):
            box = {key: int(bounds[key]) for key in ("left", "top", "right", "bottom")}
        if isinstance(node, dict):
            nodes.append({
                "text": node.get("text") or node.get("desc") or "",
                "resource_id": node.get("viewId") or "",
                "class_name": node.get("className") or "",
                "bounds": box,
                "clickable": "clickable" in set(node.get("flags") or []),
                "source": "a11y",
            })
            for child in node.get("children") or []:
                visit(child)

    if root:
        visit(root)
    return nodes


def _bounds(raw: str | None):
    if not raw:
        return None
    nums = [int(item) for item in re.findall(r"-?\d+", raw)]
    if len(nums) != 4:
        return None
    left, top, right, bottom = nums
    if right <= left or bottom <= top:
        return None
    return {"left": left, "top": top, "right": right, "bottom": bottom}


def _point(bounds: dict, screen) -> tuple[int, int]:
    left, right = bounds["left"], bounds["right"]
    top, bottom = bounds["top"], bounds["bottom"]
    if screen and ((left + right) // 2 > screen[0] or (top + bottom) // 2 > screen[1]):
        left, right, top, bottom = left // 2, right // 2, top // 2, bottom // 2
    width = right - left
    height = bottom - top
    if width <= 1 or height <= 1:
        return left, top
    return left + random.randrange(width), top + random.randrange(height)


def _find(nodes, text: str, class_name: str | None):
    wanted = norm(text)
    matches = []
    for node in nodes:
        if norm(node.get("text") or "") != wanted:
            continue
        if class_name and node.get("class_name") != class_name:
            continue
        if not node.get("bounds"):
            continue
        matches.append(node)
    if not matches and class_name:
        return _find(nodes, text, None)
    if not matches:
        return None
    return max(matches, key=lambda node: node["bounds"]["bottom"] - node["bounds"]["top"])


def _edit_text(nodes):
    fields = _edit_texts(nodes)
    return fields[0] if fields else None


def _edit_texts(nodes):
    return [
        node for node in nodes
        if "EditText" in str(node.get("class_name") or "") and node.get("bounds")
    ]


def _bullet_length(nodes) -> int:
    best = 0
    for node in nodes:
        text = node.get("text") or ""
        if text and set(text) <= {"•", "●", "∙"}:
            best = max(best, len(text))
    return best


def _field_length(nodes) -> int:
    best = 0
    for node in _edit_texts(nodes):
        best = max(best, len(node.get("text") or ""))
    return best


def _texts(nodes) -> list[str]:
    found = []
    for node in nodes:
        text = norm(node.get("text") or "")
        if text and text not in found:
            found.append(text)
    return found


def _safe_label(nodes, email: str, *extra: str) -> str:
    label = " | ".join(_texts(nodes)[:8])[:180]
    for secret in (email, *extra):
        if secret:
            label = label.replace(secret, "[hidden]")
    return re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email]", label)


def _note(record: dict, step: str) -> None:
    record.setdefault("steps", []).append(step)
    write_run(record["run_number"], record)


def _choice(record: dict, plan: dict) -> None:
    record["choices"]["username"] = plan["username"]
    record["choices"]["password"] = plan["password"]
    record["choices"]["username_pattern"] = plan["username_pattern"]
    record["choices"]["password_pattern"] = plan["password_pattern"]
    write_run(record["run_number"], record)


def _number_outcome(record: dict, order, outcome: str) -> None:
    if not order:
        return
    phone = str(order.get("phone") or "")
    for row in record.get("verification_numbers") or []:
        if row.get("phone") == phone and row.get("outcome") == "pending":
            row["outcome"] = outcome
            return


def _sms_code(payload: dict) -> str | None:
    messages = payload.get("sms") or []
    if isinstance(messages, dict):
        messages = [messages]
    for message in messages:
        if not isinstance(message, dict):
            continue
        raw = str(message.get("code") or message.get("text") or "")
        match = re.search(r"\b(\d{4,8})\b", raw)
        if match:
            return match.group(1)
    return None


def _split_play(raw: str) -> tuple[str, str, str]:
    email, password, secret = raw.split(":", 2)
    return email.strip(), password, secret.strip()


def _totp(secret: str, force_next: bool = False) -> str:
    cleaned = re.sub(r"\s+", "", secret).upper()
    padding = "=" * ((8 - len(cleaned) % 8) % 8)
    key = base64.b32decode(cleaned + padding, casefold=True)
    remain = 30 - (int(time.time()) % 30)
    if force_next or remain < 5:
        time.sleep(remain + 0.2)
    counter = int(time.time()) // 30
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"
