# nxbt issue draft (brikwerk/nxbt)

## Title

Games never send rumble to NXBT controllers: malformed ACK for subcommand 0x48 (Enable Vibration)

## Body

### Summary

With an NXBT virtual Pro Controller, **system-generated rumble reaches the
controller, but application (game) rumble never does**. "Find Controllers"
chirps and the vibration on/off notification arrive as `0x10` output reports,
while games produce zero rumble output reports no matter what happens on
screen.

The cause appears to be the ACK byte NXBT returns for subcommand `0x48`
(Enable Vibration). `protocol.py` replies with `0x82`:

```python
def enable_vibration(self):
    # ACK Reply
    self.report[14] = 0x82
```

A real controller replies to `0x48` with a plain ACK, `x80 x48`
(dekuNukem `bluetooth_hid_subcommands_notes.md`). `0x82` means "ACK with
reply data of type 0x02", which is malformed for this subcommand. The
console seems to accept the pairing but to treat the vibration device as
unusable for applications: the privileged system-rumble path still sends
frames, the application vibration API sends nothing.

After changing the ACK to `0x80` and re-pairing, games stream real HD rumble
data (`0x10` output reports with non-neutral rumble payloads) to the virtual
controller.

### Environment / repro

- NXBT commit 086293d (the pin used by NinBuddy), Python 3.11, Raspberry Pi
  (onboard UART Bluetooth), retail Switch.
- Repro: pair a virtual PRO_CONTROLLER, enter any game with rumble, log
  incoming `itr.recv()` reports in the mainloop. With stock NXBT you only
  ever see rumble payloads from system features (pairing buzz, Find
  Controllers). With the one-byte fix you also get game rumble.

### Related observations (may deserve separate issues/PRs)

While debugging this I found two more deviations from real-controller
behaviour that affected rumble delivery in my testing. I applied all three
together before games rumbled, and only partially isolated their individual
contributions afterwards, so I'm listing them for completeness:

1. **Input report dedup starves the output stream.** `server.py`'s mainloop
   suppresses input reports whose payload matches the previous one
   (`cached_msg`), falling back to one keepalive every 132 ticks (~2 s at
   66 Hz). A real Pro Controller streams full reports at ~60 Hz
   unconditionally in mode 0x30. With the dedup in place the console sent
   almost no `0x10` output reports; after resending every tick the console
   settled into a steady ~17 Hz rumble/output stream.
2. **`vibrator_report` (input report byte 12) is a made-up constant.**
   dekuNukem documents byte 12 as "decides if next vibration pattern should
   be sent" with observed values `x70/xC0/xB0`. Sniffing a real Joy-Con (L)
   over raw L2CAP shows it idling at `0x30` and switching to `0xB0` once it
   has consumed rumble data. NXBT sends a static `0xA0`, which matches none
   of the documented values. I had it emulate the observed transition
   (`0x70` idle → `0xF0` after consuming rumble, i.e. the dual-motor analog
   of the Joy-Con's `0x30`→`0xB0`).

### Limitations

- I don't own a real Pro Controller, so I could not capture a genuine
  Pro Controller pairing/rumble session for byte-level comparison; the
  reference values above come from dekuNukem's notes and from sniffing a
  real Joy-Con (L).
- HOME menu haptic feedback (if a real Pro Controller produces any there)
  still does not arrive with all three changes applied. Without real
  hardware I can't tell whether that's a remaining emulation gap or simply
  how the console behaves.
- The three changes were verified together; the 0x48 ACK fix is the only
  one where stock behaviour contradicts the documented protocol outright.
