CODE_WAIT_START_SECONDS = 120
PURCHASE_WAIT_START_SECONDS = 30
ACCOUNT_LIMIT = 50
RUN_LIMIT = 300
SAMPLE_RUNS = 10
WAIT_MARGIN = 1.4


def adjusted_wait(success_seconds: list[float], default_seconds: int) -> int:
    if not success_seconds:
        return default_seconds
    longest = max(success_seconds)
    return int(round(longest * WAIT_MARGIN))


class Campaign:
    def __init__(self) -> None:
        self.accounts = 0
        self.finished_runs = 0
        self.code_arrivals: list[float] = []
        self.purchase_times: list[float] = []

    @property
    def stopped(self) -> bool:
        return self.accounts >= ACCOUNT_LIMIT or self.finished_runs >= RUN_LIMIT

    def _sampled(self) -> bool:
        return self.finished_runs >= SAMPLE_RUNS

    def code_wait_for(self, already_waiting: bool) -> int:
        if already_waiting or not self._sampled():
            return CODE_WAIT_START_SECONDS
        return adjusted_wait(self.code_arrivals, CODE_WAIT_START_SECONDS)

    def purchase_wait_for(self, already_waiting: bool) -> int:
        if already_waiting or not self._sampled():
            return PURCHASE_WAIT_START_SECONDS
        return adjusted_wait(self.purchase_times, PURCHASE_WAIT_START_SECONDS)


class Misses:
    def __init__(self) -> None:
        self.count = 0
        self.refusal_row = 0
        self.stopped = False

    def silence(self) -> None:
        self._miss()

    def rejected_code(self) -> None:
        self._miss()

    def refusal(self) -> None:
        if self.stopped:
            return
        self.refusal_row += 1
        if self.refusal_row >= 5:
            self.stopped = True

    def _miss(self) -> None:
        if self.stopped:
            return
        self.refusal_row = 0
        self.count += 1
        if self.count >= 3:
            self.stopped = True


def boot_action(phase: str, status: str) -> str:
    """Keep a device that is already stopped, starting, or running.

    Those three can be set by hand. Provisioning still waits. Any other status
    is off the path and the device is replaced. After start has begun, falling
    back to provisioning is also off the path.
    """
    status = status.lower()
    if status == "running":
        return "ready"
    if status == "stopped":
        return "start"
    if status == "starting":
        return "wait"
    if status == "provisioning" and phase == "provision":
        return "wait"
    if phase not in ("provision", "start"):
        raise ValueError(phase)
    return "replace"


def device_name(form_name: str, run_number: int) -> str:
    name = f"{form_name} {run_number}"
    return name[:60]
