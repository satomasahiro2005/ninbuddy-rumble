# Joy-Con L raw rumble pass-through — findings & state

Goal: forward the rumble the Switch sends to NinBuddy's virtual Pro Controller
to a **real Joy-Con L** so it physically vibrates, driven from the Raspberry Pi.

Host: `oppi@raspberrypi.local` (Pi with onboard Broadcom BT = `hci0`, UART).
Bridge lives in the venv nxbt package, not upstream ninbuddy:
`~/ninbuddy-venv/lib/python3.11/site-packages/nxbt/controller/server.py`
(`class RawJoyConRumbleBridge`, wired into `ControllerServer.mainloop`).

Joy-Con L BD address: `BC:74:4B:8B:98:82` (class 0x002508 = gamepad).
Switch console: `BC:74:4B:C1:B8:BE`.

## SOLVED and proven

1. **HIDP header `0xA2`.** Raw-L2CAP output reports to the Joy-Con interrupt
   PSM (0x13) must be prefixed with `0xA2` (HIDP DATA/Output):
   `A2 10 <timer> <8 rumble bytes>`. Without it the first byte is misread as
   the HIDP header and the report is silently ignored.
2. **Enable vibration.** A real Joy-Con ignores rumble until it receives
   subcommand `0x48 0x01` (report 0x01: `A2 01 <timer> <8 neutral> 48 01`).
   The Joy-Con then ACKs (`a1 21 .. 80 48`) and vibrates. (1+2 physically
   vibrated the Joy-Con in a one-shot manual test.)
3. **Motor mapping.** Switch rumble is dual-motor (left=bytes[0:4],
   right=bytes[4:8]), driven in alternating frames. A Joy-Con L has ONE motor,
   so `_map_to_joycon` picks whichever half is driven and duplicates it.
4. **Threading.** L2CAP connect blocks for seconds; doing it in NXBT's mainloop
   froze the Switch link. The bridge owns a worker thread; the mainloop only
   stores the latest value.
5. **`frequency=120` -> `66`** in `src/modules/controller.py`. 120 Hz
   overloaded hci0's TX and made input jittery; 66 Hz is smooth. KEEP THIS.

## The wall (confirmed unsolvable on ONE adapter)

With the Joy-Con connected (Pi = master of that link), the Switch's inbound
rumble reports do not reach NXBT (`handle_switch_report` sees nothing).
Outbound (controller input) is unaffected. Root cause: the Pi is SLAVE to the
Switch and MASTER to the Joy-Con = a scatternet bridge across two piconets, and
the onboard Broadcom controller starves the slave-link RX. Verified by btmon:
zero `ACL Data RX` on the Switch handle while the Joy-Con link is up.

Software mitigations tried, all failed:
- **Lower send rate / 66 Hz:** even ~5 sends/s to the Joy-Con -> Switch RX = 0.
- **Sniff mode** on the Joy-Con link: engages but the controller negotiates a
  useless 15 ms interval; Switch RX still 0.
- **Role switch** (make the Pi master of the Switch link too -> single
  piconet): the HCI RX path does reopen, BUT the Switch immediately re-asserts
  master, so a keeper loop churns role switches endlessly and that churn itself
  breaks the Switch link. The Switch will not stay a slave. Dead end.

## Fix: dedicated second adapter (dongle arrives ~2026-07-04)

Add a USB BT dongle as `hci1`, dedicate it to the Joy-Con (`hci0` stays
NXBT<->Switch). The shipped `rumble_bridge.py` already does this: it stays
INERT unless `hciconfig hci1` exists, and binds the Joy-Con L2CAP sockets to
hci1's address (`sock.bind((hci1_addr, 0))`) before connecting. So with no
dongle NinBuddy runs as a normal smooth controller and never touches hci0;
plug in a dongle and rumble should just work (protocol already proven).

If a second onboard/USB adapter shows up as `hci1`, verify roles: `hcitool con`
should show the Switch on hci0 (PERIPHERAL) and the Joy-Con on hci1 (CENTRAL),
with no shared adapter.

## Files here

- `rumble_bridge.py` — the shipped bridge class (hci1-gated; currently deployed
  in the venv). Requires, in server.py: `from threading import Thread, Lock`
  and the `self.rumble.{handle_switch_report,tick,close}` calls in mainloop
  (already present).
- `nxbt_server_patched.py` — exact copy of the deployed venv server.py.
- `apply_patch.py` — swaps the `RawJoyConRumbleBridge` class in a target
  server.py with the one from a source file.

Reinstall:
```
python3 apply_patch.py \
  ~/ninbuddy-venv/lib/python3.11/site-packages/nxbt/controller/server.py \
  rumble_bridge.py
sudo systemctl restart ninbuddy.service
```

Debug variants used during investigation (verbose /tmp/rumble_debug.log with
per-second calls/sends telemetry, RAW dumps, a /tmp/jc_off pause flag, sniff,
and role-switch) are in the scratchpad on the dev machine, not committed.
