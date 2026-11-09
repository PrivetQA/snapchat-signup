---
name: snapchat-signup
description: >-
  Register one Snapchat account on a running Telephort device by running the
  saved script. Use when the user asks to repeat that registration, sign into
  Play, install Snapchat, and sign up. Does not create the device.
---

# Snapchat signup

Run the script in this repository. Do not reimplement the taps, the typing, or the screen decisions.

```bash
export TELEPHORT_SDK=/path/to/backend/sdk/python
export SNAP_DEVICE=<device-id>
python3 snap_realistic.py
```

The device is already running. One device per run. Do not start a second copy against the same device.

Credentials stay out of the repo. `data/local.json` has `telephort_email`, `telephort_password`, and `fivesim_token`. The Play account is `play_account` in the play-store skill `state.json` (`email:password:totp`). Set `PLAY_STATE` when that file is somewhere else. Do not print the Play password, the TOTP, the Snapchat password, the phone number, or the SMS code.

The script opens Play by the store link, types from the on-screen keyboard, and presses with the finger described in the device-hand skill. A taken username gets more digits, up to 15 characters. Stop on SS03.

When the run stops, the script prints the failed step, how long the parts took, and a proposed fix. Change only that step, check it once, and show what changed. Push the script or a skill only after the person agrees.
