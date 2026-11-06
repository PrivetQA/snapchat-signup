# Snapchat signup

The registration script that signs into Play, installs Snapchat, and registers one account on a running Telephort device. Another agent should run this file, not reimplement the taps.

```bash
export TELEPHORT_SDK=/path/to/backend/sdk/python
export SNAP_DEVICE=<device-id>
python3 snap_realistic.py
```

`data/local.json` (see `data/local.json.example`) holds the Telephort login and the 5sim token. The Play account is `play_account` in the play-store skill `state.json`. Set `PLAY_STATE` if that file is not under the current directory. Neither file is committed.

The device is already running. This script does not create it. Taps follow [device-hand](https://github.com/PrivetQA/device-hand-skill): a finger press on the input channel, characters from the on-screen keyboard.
