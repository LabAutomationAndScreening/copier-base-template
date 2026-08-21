---
paths:
  - "**/firmware/**"
---
# Firmware & Device Drivers

Guidance for firmware / device-driver code (e.g. CircuitPython drivers) and its tests.

- **Never hand-write or hand-edit pytest-reserial `.jsonl` recording files.** Recordings must be captured from real serial port traffic by running the test with `--record` while the device is connected: `uv run pytest --record <test path> --no-cov`. The default mode replays recordings — a missing recording causes an error, which is expected until recorded against a live device.
