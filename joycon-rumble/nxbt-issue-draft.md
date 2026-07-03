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

Per the documented ACK byte convention (dekuNukem
`bluetooth_hid_notes.md`, standard input report byte 13: MSB set = ACK,
low 7 bits = reply data type, `x00` for a simple ACK), a reply that
carries no data should be a plain `0x80`. A real Joy-Con (L) I sniffed
over raw L2CAP confirms this on the wire: it acks `0x48` with
`x80 x48`. `0x82` is the ACK-with-data type NXBT itself uses for the
device info reply (subcommand `0x02`), so it looks like a copy-paste
leftover. The console accepts the pairing but seems to treat the
vibration device as unusable for applications: the privileged
system-rumble path still sends frames, the application vibration API
sends nothing.

The fix was verified two ways:

- In two otherwise-identical setups, switching this byte from `0x82` to
  `0x80` (re-pair in between) was the difference between zero game
  rumble and games streaming HD rumble.
- With everything else left stock, the `0x80` fix alone was sufficient:
  a short play test delivered ~90 output reports with real (non-neutral)
  HD rumble payloads.

I'll open a small PR with the one-byte fix.

### Environment / repro

- NXBT master (also present in 086293d), Python 3.11, Raspberry Pi
  (onboard UART Bluetooth), retail Switch.
- Repro: pair a virtual `PRO_CONTROLLER`, enter any game with rumble, log
  `itr.recv()` in the mainloop. Stock: only system features (pairing buzz,
  Find Controllers) ever produce rumble payloads. With the fix: game rumble
  streams in.

### Related observations

Two more deviations from real-controller behaviour turned up while
debugging. Neither is required for game rumble (the 0x48 fix alone was
verified sufficient), but both improved rumble delivery cadence on my rig.
Listing them in case they deserve their own issues:

1. **Input report dedup starves the output stream.** The mainloop
   suppresses input reports whose payload matches the previous one
   (`cached_msg`), falling back to one keepalive every 132 ticks (~2 s).
   A real Pro Controller streams full reports at ~60 Hz unconditionally in
   mode 0x30. With the dedup in place, rumble output reports from the
   console arrived sparsely and irregularly (gaps from tens of ms to
   seconds); with an unconditional resend every tick they settled into a
   steady stream.
2. **`vibrator_report` (input report byte 12) is picked at random from a
   made-up value set** (`random.choice([0xA0, 0xB0, 0xC0, 0x90])` at init
   and on every subcommand reply) rather than reflecting rumble
   consumption. dekuNukem documents byte 12 as "decides if next vibration
   pattern should be sent" (observed values `x70/xC0/xB0`), and the real
   Joy-Con (L) I sniffed idles at `0x30` and switches to `0xB0` once it
   has consumed rumble data.

### Limitations

- I don't own a real Pro Controller, so I could not capture a genuine Pro
  Controller session for byte-level comparison; reference values come from
  dekuNukem's notes and from sniffing a real Joy-Con (L).
