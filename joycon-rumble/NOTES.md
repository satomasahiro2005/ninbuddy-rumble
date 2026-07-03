# Joy-Con L raw rumble pass-through — findings & state

Goal: forward the rumble the Switch sends to NinBuddy's virtual Pro Controller
to a **real Joy-Con L** so it physically vibrates, driven from the Raspberry Pi.

Host: `oppi@raspberrypi.local` (Pi with onboard Broadcom BT = `hci0`, UART).
Bridge lives in the venv nxbt package, not upstream ninbuddy:
`~/ninbuddy-venv/lib/python3.11/site-packages/nxbt/controller/server.py`
(`class RawJoyConRumbleBridge`, wired into `ControllerServer.mainloop`).

Joy-Con L BD address: `BC:74:4B:8B:98:82` (class 0x002508 = gamepad).
Switch console: `BC:74:4B:C1:B8:BE`.

## What is SOLVED and proven

1. **HIDP header `0xA2`.** Raw-L2CAP output reports to the Joy-Con interrupt
   PSM (0x13) must be prefixed with `0xA2` (HIDP DATA/Output):
   `A2 10 <timer> <8 rumble bytes>`. Without it the first byte is misread as
   the HIDP header and the report is silently ignored — connects but no effect.
2. **Enable vibration.** A real Joy-Con ignores rumble until it receives
   subcommand `0x48 0x01` (report 0x01: `A2 01 <timer> <8 neutral> 48 01`).
   After sending it, the Joy-Con ACKs (`a1 21 .. 80 48`) and vibrates.
   -> With 1+2, a one-shot manual test physically vibrated the Joy-Con.
3. **Motor mapping.** Switch rumble is dual-motor: left = bytes[0:4],
   right = bytes[4:8], and games drive the two halves in alternating frames.
   A Joy-Con L has ONE motor. `_map_to_joycon` picks whichever half is actually
   driven and duplicates it into both halves.
4. **Threading.** The L2CAP connect blocks up to seconds; doing it inline in
   NXBT's realtime mainloop froze the Switch link (jittery Xbox input). The
   bridge now owns a worker thread; the mainloop only stores the latest value.
5. **`frequency=120` -> `66`** in `src/modules/controller.py`
   (`nx.create_controller`). 120 Hz overloaded hci0's TX and made input
   latency unstable; 66 Hz made Xbox input "very smooth". KEEP THIS.

## The wall (unsolved on one adapter)

On the single onboard `hci0`, an **active Joy-Con ACL link (Pi as central)
starves the Switch's inbound rumble reports**. Measured with per-second
telemetry:

| adapter state | Switch output reports reaching NXBT |
|---|---|
| Joy-Con absent (`Host is down` fast-fail) | flowing (hundreds/s) |
| Joy-Con connected, 66 Hz, ~5 sends/s to Joy-Con | **0** |

Even a nearly-idle second ACL kills inbound reception, so rate/frequency tuning
does not help. Blindly paging an absent Joy-Con every ~6 s can also leave a
stuck "zombie" ACL (invalid handle 0x0F00 / 3840, state 5) that starves hci0.
Outbound (Pi->Switch, i.e. controller input) is NOT affected — only the
inbound rumble direction. This matches the earlier Codex conclusion.

## Plan (dongle arrives next day)

Add a 2nd USB BT dongle: `hci1` dedicated to the Joy-Con (central), `hci0`
stays NXBT<->Switch (peripheral). Bind the Joy-Con L2CAP sockets to the hci1
BD address before connect (`sock.bind((hci1_addr, 0))`), and gate the whole
bridge so it does nothing (never pages hci0) when hci1 is absent. Then the
proven bridge above should just work.

## Files here

- `rumble_bridge.py` — canonical debug-free bridge class (proven; see above).
- `nxbt_server_patched.py` — exact copy of the running venv server.py
  (verbose-telemetry variant that writes /tmp/rumble_debug.log). Full backup.
- `apply_patch.py` — replaces the `RawJoyConRumbleBridge` class inside a target
  nxbt server.py with the class from a given source file.

Reinstall the clean bridge:
```
python3 apply_patch.py \
  ~/ninbuddy-venv/lib/python3.11/site-packages/nxbt/controller/server.py \
  rumble_bridge.py
sudo systemctl restart ninbuddy.service
```
(server.py must already have `from threading import Thread, Lock` and the
`self.rumble.*` calls in mainloop — both already present in the venv.)
