# nxbt issue draft — 提出はGitHubの New issue でタイトルと本文を貼るだけ

## Title (そのままコピー)

Games never send rumble: malformed ACK for subcommand 0x48 (Enable Vibration)

## Body (以下をそのまま貼る)

### Summary

With an NXBT virtual Pro Controller, **system-generated rumble reaches the
controller, but application (game) rumble never does**. "Find Controllers"
chirps and the vibration on/off notification arrive as `0x10` output
reports, while games produce zero rumble output reports no matter what
happens on screen. This is probably the answer to #106 as well.

The cause appears to be the ACK byte NXBT returns for subcommand `0x48`
(Enable Vibration). `protocol.py` replies with `0x82`:

```python
def enable_vibration(self):
    # ACK Reply
    self.report[14] = 0x82
```

A real controller replies to `0x48` with a plain ACK, `x80 x48`
(dekuNukem `bluetooth_hid_subcommands_notes.md`). `0x82` is the
ACK-with-data type that belongs to the device info reply (`0x02`), so it
looks like a copy-paste leftover. The console accepts the pairing but seems
to treat the vibration device as unusable for applications: the privileged
system-rumble path still sends frames, the application vibration API sends
nothing.

After changing the ACK to `0x80` and re-pairing, games stream real HD
rumble data (`0x10` output reports with non-neutral rumble payloads) to the
virtual controller. I'll open a small PR with the one-byte fix.

### Environment / repro

- NXBT master (also present in 086293d), Python 3.11, Raspberry Pi
  (onboard UART Bluetooth), retail Switch.
- Repro: pair a virtual `PRO_CONTROLLER`, enter any game with rumble, log
  `itr.recv()` in the mainloop. Stock: only system features (pairing buzz,
  Find Controllers) ever produce rumble payloads. With the fix: game rumble
  streams in.

### Related observations

Two more deviations from real-controller behaviour affected rumble delivery
in my testing; I applied all three together before games rumbled, so the
individual contributions are only partially isolated. Listing them in case
they deserve their own issues:

1. **Input report dedup starves the output stream.** The mainloop
   suppresses input reports whose payload matches the previous one
   (`cached_msg`), falling back to one keepalive every 132 ticks (~2 s).
   A real Pro Controller streams full reports at ~60 Hz unconditionally in
   mode 0x30. With the dedup in place the console sent almost no output
   reports; with an unconditional resend every tick it settled into a
   steady output/rumble stream.
2. **`vibrator_report` (input report byte 12) is a made-up constant
   (`0xA0`).** dekuNukem documents byte 12 as "decides if next vibration
   pattern should be sent" with observed values `x70/xC0/xB0`. Sniffing a
   real Joy-Con (L) over raw L2CAP shows it idling at `0x30` and switching
   to `0xB0` once it has consumed rumble data. I made it emulate that
   transition (`0x70` idle → `0xF0` after consuming rumble).

### Limitations

- I don't own a real Pro Controller, so I could not capture a genuine Pro
  Controller session for byte-level comparison; reference values come from
  dekuNukem's notes and from sniffing a real Joy-Con (L).
- The three changes were verified together on my rig; the 0x48 ACK is the
  only one where stock NXBT contradicts the documented protocol outright.
