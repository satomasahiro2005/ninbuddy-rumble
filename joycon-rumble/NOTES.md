# Joy-Con L rumble bridge notes

Date: 2026-07-03 JST
Host: `oppi@raspberrypi.local`
Repo: `/home/oppi/ninbuddy`
NXBT runtime files:

- `/home/oppi/ninbuddy-venv/lib/python3.11/site-packages/nxbt/controller/server.py`
- `/home/oppi/ninbuddy-venv/lib/python3.11/site-packages/nxbt/controller/protocol.py`

Goal: USB Xbox controller drives the virtual Switch Pro Controller through
NinBuddy/NXBT, while a real Joy-Con L on the Pi is used only as the physical
rumble actuator.

Joy-Con L: `BC:74:4B:8B:98:82`
Switch: `BC:74:4B:C1:B8:BE`

## Current fixed configuration

Keep this order:

1. NXBT virtual controller connects to the Switch.
2. Only after the Switch link is up, the Joy-Con L rumble bridge may connect.

Do not preconnect the Joy-Con before the virtual controller is connected to the
Switch. `RawJoyConRumbleBridge.preconnect()` is left as a debug helper, but
`ControllerServer.run()` must not call it.

## Proven pieces

### Switch -> virtual Pro rumble

Game rumble depends on ACKing subcommand `0x48` as a plain ACK:

- Good: `report[14] = 0x80`, `report[15] = 0x48`
- Bad: `report[14] = 0x82`, `report[15] = 0x48`

The vibrator input byte in the standard input report does not need generated
ACK modes. Stock NXBT's constant `0xA0` works. The runtime A/B file
`/tmp/vib_ack_mode` was only an experiment and is no longer used.

Known-good table from testing:

| configuration | `0x48` ACK | game rumble |
| --- | --- | --- |
| streaming + generated ACK mode 1 | `0x82` | zero |
| streaming + generated ACK mode 1 | `0x80` | works |
| stock dedup + constant `0xA0` | `0x80` | works |
| unmodified NXBT before this work | `0x82` | zero |

### Virtual Pro -> real Joy-Con L

Raw L2CAP reports to the Joy-Con interrupt PSM need the Bluetooth HIDP output
header:

- Enable vibration: `A2 01 <timer> 0001404000014040 48 01`
- Rumble only: `A2 10 <timer> <8 rumble bytes>`

The Joy-Con L has one actuator, while Switch/Pro rumble is stereo. For this
use case we want mono output, so the bridge picks the active 4-byte half and
duplicates it to both halves before sending to the Joy-Con.

LED command for "1001" is sent as subcommand `0x30 0x09`. The log has shown
`player lights ack 0x80`, so the command is accepted by the Joy-Con.

### NXBT multiprocessing

NXBT constructs `ControllerServer` in the parent process, then runs
`ControllerServer.run()` in a forked child process. Threads created before the
fork stay in the parent and do not see Switch output reports.

Therefore rumble state changes and Joy-Con writes must happen from the child
mainloop path (`handle_switch_report()` / `tick()`). A connection helper thread
is OK only when launched lazily from that child after the Switch link exists.

## Current live evidence

At around 23:41 JST the bridge had both links connected:

- `hcitool con` showed the Switch link and the Joy-Con L link both
  `AUTH ENCRYPT`.
- Joy-Con input reports `joycon_rx id=0x30` were flowing.
- `player lights ack 0x80` was observed.
- Switch game rumble frames arrived and were forwarded:
  - `raw=d8c83640d8c83640`
  - `raw=6d036380d8c83640`
  - `raw=6c006380d8c83640`
- Counters reached `active=26`, `sent_active=24`, `fails=0`.

After the service was restarted with the fixed `0xA0` protocol code, the Switch
link came back first and game rumble was visible before the Joy-Con connected:

- `ack enable_vibration report14=0x80 report15=0x48`
- `nxbt_tx ... vib=0xa0 ... reply=0x48`
- `raw=0000000002786040` and later many `d8c83640...` frames arrived.

The Joy-Con then needed to be woken with SYNC and a known-MAC HCI page. After
that, the bridge opened L2CAP, enabled vibration, got LED ACK, and forwarded a
game rumble frame:

- `joycon connected + vibration enabled`
- `player lights ack 0x80`
- `switch active ... raw=d8c83640d8c83640 ... conn=1`
- `sent rumble d8c83640d8c83640`

Do not prime the ACL with `hcitool cc <Joy-Con MAC>` before opening raw L2CAP.
That experiment caused repeated `errno=114 Operation already in progress`
failures after a service restart. The bridge should page the Joy-Con by opening
the raw control/interrupt L2CAP sockets directly, as in the successful run.

This retires the earlier "single adapter is impossible" note. Single-adapter
operation is not guaranteed under all timing/load conditions, but it has now
been shown to pass real game rumble while the Switch and Joy-Con are both
connected.

## Airtime rules

Do not send Joy-Con rumble every NXBT tick. That made input heavy. The current
bridge deduplicates identical rumble frames, forwards changes immediately, and
allows only a slow keepalive for unchanged data.

Do not connect the Joy-Con before the Switch controller link. It complicates
pairing and can make the user lose the controller link at exactly the wrong
time.

Keep the virtual controller frequency at `66`, not `120`, when sharing the
adapter with a Joy-Con rumble sink. Also do not request Joy-Con report mode
`0x30` for normal rumble bridging: it creates a 60 Hz Joy-Con input stream that
competes with the Switch link. The bridge now sends report mode `0x3F` once
after enabling Joy-Con vibration so the Joy-Con remains low-traffic while still
accepting rumble and LED subcommands.

## Useful runtime files

- `/tmp/rumble_debug.log` - detailed bridge/protocol log
- `/tmp/jc_off` - pause Joy-Con connection attempts while leaving Switch input up
- `/tmp/joycon_test_pulse` - debug-only trigger for a short synthetic Joy-Con pulse
- `/tmp/rumble_capture_on` - start a bounded CSV capture in `/tmp/rumble_capture.log`

## Files in this directory

- `nxbt_server_patched.py` - snapshot of deployed `server.py`
- `nxbt_protocol_patched.py` - snapshot of deployed `protocol.py`
- `nxbt-issue-draft.md` / `nxbt-pr-draft.md` - upstream notes
- `apply_patch.py` - older helper for swapping the bridge class

After editing the venv runtime files, keep the two `nxbt_*_patched.py`
snapshots in sync so this directory remains a usable work record.
