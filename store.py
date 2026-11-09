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


def save_account(account: dict) -> None:
    upsert_account(account)


def upsert_account(account: dict) -> Path:
    """Keep one row per run so a later step updates the password and phone already saved."""
    ensure()
    with ACCOUNTS.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        rows = json.loads(handle.read() or "[]")
        key = account.get("run_number")
        if key is None:
            rows.append(account)
        else:
            for index, row in enumerate(rows):
                if row.get("run_number") == key:
                    rows[index] = {**row, **account}
                    break
            else:
                rows.append(account)
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
        handle.flush()
    return ACCOUNTS
