import fcntl
import json
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
RUNS = DATA / "runs"
ACCOUNTS = DATA / "accounts.json"


def ensure() -> None:
    RUNS.mkdir(parents=True, exist_ok=True)
    if not ACCOUNTS.exists():
        ACCOUNTS.write_text("[]\n")


def write_run(run_number: int, record: dict) -> Path:
    ensure()
    path = RUNS / f"run-{run_number:04d}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    return path


STATUS_ORDER = (
    "device_created",
    "planned",
    "name",
    "birthday",
    "username",
    "password",
    "phone",
    "code",
    "feed",
)
IDENTITY = ("name", "username", "password", "phone", "phone_on_screen")


def save_account(account: dict) -> None:
    upsert_account(account)


def save_device(device: dict) -> Path:
    """One row per device. Later signup steps fill the same row."""
    return upsert_account(device)


def load_account(device_id: str) -> dict | None:
    ensure()
    if not device_id:
        return None
    rows = json.loads(ACCOUNTS.read_text() or "[]")
    for row in rows:
        if row.get("device_id") == device_id:
            return row
    return None


def _merge(old: dict, new: dict) -> dict:
    merged = dict(old)
    for key, value in new.items():
        if value is None or value == "":
            continue
        merged[key] = value
    old_status = old.get("status")
    new_status = new.get("status")
    if old_status in STATUS_ORDER and new_status in STATUS_ORDER:
        if STATUS_ORDER.index(new_status) < STATUS_ORDER.index(old_status):
            merged["status"] = old_status
            for key in IDENTITY:
                if old.get(key):
                    merged[key] = old[key]
    return merged


def upsert_account(account: dict) -> Path:
    """Keep one row per device so a later step updates the password and phone already saved."""
    ensure()
    with ACCOUNTS.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        rows = json.loads(handle.read() or "[]")
        device_id = account.get("device_id")
        run_number = account.get("run_number")
        index = None
        for found, row in enumerate(rows):
            if device_id and row.get("device_id") == device_id:
                index = found
                break
        if index is None and run_number is not None:
            for found, row in enumerate(rows):
                if row.get("run_number") == run_number and not row.get("device_id"):
                    index = found
                    break
        if index is None:
            rows.append(account)
        else:
            rows[index] = _merge(rows[index], account)
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
        handle.flush()
    return ACCOUNTS
