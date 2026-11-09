"""What to do on a Play or Snapchat screen, from the text that is already visible."""

from __future__ import annotations


def is_snapchat_signup(texts: list[str]) -> bool:
    """Snapchat registration is in front. Play must leave it alone."""
    present = {norm(text) for text in texts if text}
    blob = " ".join(present).lower()
    if "Birthday" in present and "Continue" in present:
        return True
    return any(
        phrase in blob
        for phrase in (
            "what's your name",
            "when's your birthday",
            "when is your birthday",
            "step 1 of 5",
            "step 2 of 5",
            "step 3 of 5",
            "step 4 of 5",
            "step 5 of 5",
        )
    )


def norm(text: str) -> str:
    return text.replace("\u2019", "'").replace("\u2018", "'").strip()


def play_decision(nodes: list[dict]) -> dict:
    texts = [norm(str(node.get("text") or "")) for node in nodes]
    present = {text for text in texts if text}
    ids = " ".join(str(node.get("resource_id") or "") for node in nodes)
    blob = " ".join(texts).lower()

    # This sheet can cover Play or Snapchat at any step. Always confirm.
    if "are you trying to sign in" in blob:
        if "Yes, it's me" in present:
            return _tap("Yes, it's me", "android.widget.Button")
        return {"op": "wait"}
    if _captcha(blob):
        return {"op": "block", "reason": "play captcha"}
    if "isn't responding" in blob and "Wait" in present:
        return _tap("Wait")
    # A disabled phone row says "try again later" on the chooser. That is not a refusal
    # while Google Authenticator is still on the screen.
    phone_later = "try again later" in blob and "Google Authenticator" not in present
    if "confirm it's you" in blob or "couldn't sign in" in blob or phone_later:
        return {"op": "block", "reason": "play refused sign-in"}
    # The progress line stays on the same button. Wait until it leaves.
    if "Loading" in present:
        return {"op": "wait"}
    if is_snapchat_signup(list(present)):
        return {"op": "snapchat"}
    if "add a selfie" in blob or "selfie for sign in" in blob:
        return _tap("Not now", "android.widget.Button")
    if "can't begin video verification" in blob:
        return _tap("Cancel")
    # The intro heading stays above the code field. totpPin is the code page.
    if "totpPin" in ids or "Enter code" in present or "Enter a code" in present:
        return {"op": "type_code"}
    # The same heading stays on the chooser. Tap the Authenticator row.
    if "choose how you want to sign in" in blob:
        if "Google Authenticator" in present:
            return _tap("Google Authenticator")
        return {"op": "hide_keyboard"}
    # Intro only: Next, or Try another way on the phone prompt. Do not type yet.
    if "2-step verification" in blob and "to help keep your account safe" in blob:
        if "Next" in present:
            return _tap("Next", "android.widget.Button")
        if "Try another way" in present:
            return _tap("Try another way")
        return {"op": "wait"}
    if ("use your fingerprint" in blob or "use a passkey" in blob) and "Try another way" in present:
        return _tap("Try another way", "android.widget.Button")
    if "check your phone" in blob and "Try another way" in present:
        return _tap("Try another way")
    if "Google Authenticator" in present:
        return _tap("Google Authenticator")
    if "2-step verification" in blob and any(
        phrase in blob for phrase in ("choose how", "use your phone", "get a verification code")
    ):
        return {"op": "hide_keyboard"}
    if "Show password" in present or "Enter a password" in blob:
        return {"op": "type_password"}
    if "sign in with ease" in blob:
        if "Skip" in present:
            return _tap("Skip", "android.widget.Button")
        return {"op": "wait"}
    if "I agree" in present:
        return _tap("I agree", "android.widget.Button")
    if "google services" in blob and "More" in present:
        return _tap("More")
    if "google services" in blob and "Accept" in present and "Cancel" not in present:
        return _tap("Accept", "android.widget.Button")
    if "welcome to google play" in blob and "Get started" in present:
        return _tap("Get started", "android.widget.TextView")
    if "make purchases in seconds" in blob and "Skip" in present:
        return _tap("Skip", "android.widget.TextView")
    if "level up your experience" in blob and "Not now" in present:
        return _tap("Not now", "android.widget.TextView")
    if "Don't back up" in present:
        return _tap("Don't back up")
    if "No, thanks" in present:
        return _tap("No, thanks")
    if "link your google services" in blob and "Get started" in present:
        return {"op": "back_or_get_started"}
    if "add a payment option" in blob and "Skip" in present:
        return _tap("Skip")
    if "complete account setup" in blob and "Continue" in present:
        return _tap("Continue", "android.widget.Button")
    # Play asks to read notifications while signing in. Decline and continue.
    if "Not allowed" in present and "Allowed" in present:
        return _tap("Not allowed")
    if "identifierId" in ids and "Forgot email?" in present:
        if "loading" in blob:
            return {"op": "wait"}
        return {"op": "type_email"}
    if "Sign in" in present and "android.widget.Button" in _classes_for(nodes, "Sign in"):
        return _tap("Sign in", "android.widget.Button")
    if "Install" in present:
        return _tap("Install")
    if "Open" in present and "com.snapchat.android" in blob:
        return {"op": "installed"}
    if {"Games", "Apps", "You"} <= present and "sign in to find the latest" not in blob:
        return {"op": "signed_in"}
    if "loading" in blob:
        return {"op": "wait"}
    return {"op": "wait"}


def snap_decision(texts: list[str], plan: dict, nodes: list[dict] | None = None) -> dict:
    present = {norm(text) for text in texts if text}
    blob = " ".join(norm(text) for text in texts).lower()

    if "are you trying to sign in" in blob:
        if "Yes, it's me" in present:
            return _tap("Yes, it's me", "android.widget.Button")
        return {"op": "unknown"}
    if any(phrase in blob for phrase in (
        "confirm it's you", "try again later", "unusual activity", "captcha",
        "temporarily disabled", "suspicious activity",
    )):
        code = _support_code(blob)
        return {"op": "block", "reason": f"snapchat {code}" if code else "snapchat check"}
    if "welcome back" in blob and "No" in present:
        return _tap("No")
    if "check your internet" in blob:
        return {"op": "internet"}
    if "Uninstall" in present and "Open" in present and "Snapchat" in present:
        return _tap("Open")
    if _is_feed(present) and plan.get("code_accepted"):
        return {"op": "feed"}
    if "sent via whatsapp" in blob or "code via whatsapp" in blob:
        return {"op": "change_number"}
    if "enter the code" in blob or "verification code" in blob or "we sent you" in blob:
        return {"op": "type_sms"}
    if any(phrase in blob for phrase in ("incorrect code", "wrong code", "code is invalid", "invalid code")):
        return {"op": "code_rejected"}
    if any(phrase in blob for phrase in (
        "can't send", "cannot send", "unable to send", "isn't a valid mobile",
        "not a valid phone", "number isn't supported",
    )):
        return {"op": "refusal"}
    if "email" in blob and "Skip" in present:
        return _tap("Skip")
    if "email" in blob and "skip" not in blob and any(word in blob for word in ("required", "add your email", "what's your email")):
        if "Continue" in present or "Next" in present or "Sign Up" in present:
            return {"op": "block", "reason": "email required"}
    if any(phrase in blob for phrase in ("contact", "contacts")) and (
        "Don't allow" in present or "Deny" in present or "Don't allow access" in present or "Cancel" in present
    ):
        if "Don't allow" in present:
            return _tap("Don't allow")
        if "Deny" in present:
            return _tap("Deny")
        return _tap("Cancel")
    if "notification" in blob:
        allow = plan.get("notifications") == "allow"
        if allow and "Allow" in present:
            return _tap("Allow")
        if not allow and "Don't allow" in present:
            return _tap("Don't allow")
        if not allow and "Not now" in present:
            return _tap("Not now")
    if "bitmoji" in blob:
        if plan.get("bitmoji") == "skip" and ("Skip" in present or "Not now" in present):
            return _tap("Skip" if "Skip" in present else "Not now")
        if plan.get("bitmoji") == "pick":
            return {"op": "pick_bitmoji"}
    if "enable app permissions" in blob or "make sign up easy" in blob:
        if "Continue" in present:
            return _tap("Continue")
    if "Allow" in present and ("Don't allow" in present or "Deny" in present):
        return _tap("Allow")
    if "username" in blob and any(phrase in blob for phrase in ("taken", "not available", "already in use")):
        return {"op": "username_taken"}
    if "your username is" in blob and "Continue" in present:
        return _tap("Continue")
    if "Change my username" in present:
        return _tap("Change my username")
    if "password" in blob and any(phrase in blob for phrase in ("too short", "too weak", "try another", "not strong")):
        return {"op": "password_rejected"}
    if "Use phone number instead" in present:
        return _tap("Use phone number instead")
    if "country or region" in blob:
        return {"op": "type_phone"}
    if any(phrase in blob for phrase in ("mobile number", "phone number")) and "code" not in blob:
        return {"op": "type_phone"}
    if "birthday" in blob or "when's your birthday" in blob or "when is your birthday" in blob:
        return {"op": "birthday"}
    if "username" in blob:
        return {"op": "type_username"}
    if "password" in blob:
        return {"op": "type_password"}
    if any(phrase in blob for phrase in ("your name", "first name", "what's your name")):
        return {"op": "type_name"}
    if "Sign Up" in present:
        return _tap("Sign Up")
    signup = _welcome_signup(nodes or [])
    if signup:
        return {"op": "tap_bounds", "bounds": signup}
    if ("find friends" in blob or "add friends" in blob) and ("Skip" in present or "Not now" in present):
        return _tap("Skip" if "Skip" in present else "Not now")
    if _is_camera_home(present):
        return {"op": "feed"}
    return {"op": "unknown"}


def _support_code(blob: str) -> str | None:
    for token in blob.replace(":", " ").replace(".", " ").split():
        if token.startswith("ss") and token[2:].isdigit():
            return token.upper()
    return None


def _captcha(blob: str) -> bool:
    return any(phrase in blob for phrase in ("i'm not a robot", "type the text", "select all squares"))


def _tap(text: str, class_name: str | None = None) -> dict:
    decision = {"op": "tap", "text": text}
    if class_name:
        decision["class_name"] = class_name
    return decision


def _classes_for(nodes: list[dict], text: str) -> set[str]:
    wanted = norm(text)
    return {
        str(node.get("class_name") or "")
        for node in nodes
        if norm(str(node.get("text") or "")) == wanted
    }


def _is_feed(present: set[str]) -> bool:
    return {"Chat", "Stories", "Spotlight"} <= present


def _is_camera_home(present: set[str]) -> bool:
    return "Chat" in present and "Memories" in present and (
        "Camera Capture" in present or "Map" in present
    )


def _welcome_signup(nodes: list[dict]):
    login_top = None
    for node in nodes:
        if "already have an account" not in norm(node.get("text") or "").lower():
            continue
        bounds = node.get("bounds")
        if bounds:
            login_top = bounds["top"]
            break
    if login_top is None:
        return None
    candidates = []
    for node in nodes:
        if not node.get("clickable") or norm(node.get("text") or ""):
            continue
        bounds = node.get("bounds")
        if not bounds:
            continue
        width = bounds["right"] - bounds["left"]
        height = bounds["bottom"] - bounds["top"]
        if width < 200 or height < 40 or height > 160:
            continue
        if bounds["bottom"] <= login_top and bounds["top"] > login_top - 280:
            candidates.append(bounds)
    if not candidates:
        return None
    return max(candidates, key=lambda bounds: bounds["top"])
