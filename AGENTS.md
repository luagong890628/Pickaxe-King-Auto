# Pickaxe King Auto — Project Rules

All general rules in the parent `D:\project\AGENTS.md` apply; this file lists only project-specific items.

## Environment

- Always use this project's `.venv` Python: `.venv\Scripts\python.exe` (never the system Python — it has no cv2).
- Dependencies: see `requirements.txt` (opencv-python, numpy).
- Device: Samsung SM-S9360 (**Android 17**). adb defaults to `D:/Tools/scrcpy-win64-v3.3.4/adb.exe` (36.0.0); override with the `PKAUTO_ADB` environment variable. A newer 37.0.1 is installed at `D:/Tools/platform-tools/` but is deliberately not used yet — see the known-findings section of the README.
- Connection: Wi-Fi uses the **fixed port** from `adb tcpip 5555` (not wireless debugging). After a phone reboot the port is gone and `tcpip 5555` must be re-issued over USB; the launcher does this automatically.
- Game: `com.rogueuniongames.pickaxekingisland` (Unity).

## Principles

- Every interaction with the phone must be independently replayable: save screenshots to `captures/` (not version-controlled).
- Automated taps are allowed only inside the game's visible play area (`pkauto.vision.PLAY_BOX`): x 260–1140, y 700–2900. Never tap blindly on the left/right UI columns or the top resource bar.
- Prefer measurable signals for screen decisions (phase-correlation displacement, template-match score), and verify them in `tests/` with synthetic images — never guess by eye.
- Movement / gathering logic must be able to answer "where is the character now, where is the target, did this step work"; verify the effect from before/after screenshot differences.

## Current Approach (user decision 2026-10-21: purely mechanical fixed flow)

- The only main program is `cycle_fixed.py`: **no screen detection at all**, everything is fixed coordinates + fixed step counts.
- One round: teleport to the small village → 3 steps north → left 1, north 1, right 2, south 1 → teleport to the starting land → 2 steps north → tap (721,1839) to rest → left 1, north 1, right 2, south 1 → wait 30 seconds. Measured: 112 seconds per round.
- Teleport stone (1340,1670); menu cells (330,1464)/(720,1434) (swipe the menu up once manually first to reset it).
- One step = drag 250px, hold 950ms ≈ walk 300px (joystick-style: distance depends on hold time, not drag length).
- **Do not reintroduce screen detection**: every previous detection / map / touch-replay approach proved unstable and was removed (see the history section of the README and git history).

## Process Management (learned the hard way)

- **Hermes's process kill only kills the outer process**; the `python.exe` child stays alive → multiple leftover `record_touch.py` processes writing the same JSON → corrupted file, data lost.
- After finishing, always verify with
  `powershell Get-CimInstance Win32_Process | Where CommandLine -like '*Pickaxe*'`
  and only continue once nothing is left over.
- Files recorded over long runs must always be written **atomically** (write `.tmp`, then `os.replace`).

## Tests

```
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Documentation

- `README.md` records the current state and how to operate; write investigation conclusions into its known-findings section.
- Never state unverified conclusions; mark anything uncertain as "to be confirmed".
- **Every image shown to the user must be saved into `captures/`** (the user cannot see the agent's scratch directory); include the full path when reporting. When the user needs to judge a position, draw a grid or annotate coordinates on the image, and list the coordinates as text in the message as well.
