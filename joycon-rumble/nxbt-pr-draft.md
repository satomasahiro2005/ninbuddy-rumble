# nxbt PR draft (brikwerk/nxbt)

## Title

Fix Enable Vibration (0x48) ACK so games actually send rumble

## Body

### What

One-byte protocol fix: reply to subcommand `0x48` (Enable Vibration) with a
plain ACK (`0x80`), as a real controller does, instead of `0x82`.

```diff
     def enable_vibration(self):
 
-        # ACK Reply
-        self.report[14] = 0x82
+        # ACK Reply. A real controller replies to subcommand 0x48 with a
+        # plain ACK (x80 x48, see dekuNukem's bluetooth_hid_subcommands
+        # notes); 0x82 declares "ACK with device-info data" and makes the
+        # console treat the vibration device as unusable for applications.
+        self.report[14] = 0x80
 
         # Subcommand reply
         self.report[15] = 0x48
```

### Why

With the stock `0x82` ACK, the console pairs fine and system rumble
(pairing buzz, Find Controllers, vibration on/off notification) reaches the
virtual controller, but **no game ever sends rumble** — the application
vibration path appears to be disabled console-side when the enable-vibration
handshake reply is malformed. With `0x80`, games stream HD rumble to the
virtual controller in `0x10` output reports.

`0x82` is the correct ACK for subcommand `0x02` (Request Device Info, ACK +
data type), which is likely where the value was copied from.

### Testing

- Raspberry Pi (onboard BT), NXBT virtual PRO_CONTROLLER, retail Switch.
- Before: logged `itr.recv()` in the mainloop during gameplay — zero
  non-neutral rumble payloads from games; system rumble present.
- After (re-pair required): games produce a steady stream of `0x10` output
  reports with real HD rumble payloads, verified end-to-end by forwarding
  them to a physical Joy-Con (L) over raw L2CAP and feeling the game rumble.

Note: in my setup I also had to relax the `cached_msg` input-report dedup in
`server.py` (a real controller streams ~60 Hz full reports unconditionally;
the dedup starves the console's output/rumble scheduling) and I replaced the
static `vibrator_report = 0xA0` with values matching real-hardware behaviour
(`0x70` idle / `0xF0` after consuming rumble; a sniffed real Joy-Con L goes
`0x30`→`0xB0`). I can split those into separate PRs if there's interest —
this PR intentionally stays minimal.

### Limitations

- I don't own a real Pro Controller, so the reference behaviour comes from
  dekuNukem's protocol notes and from sniffing a real Joy-Con (L) rather
  than from a captured Pro Controller session.
- HOME menu haptic feedback (if real hardware produces any) still doesn't
  arrive; unclear whether that's a further emulation gap or normal console
  behaviour.
