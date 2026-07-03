# nxbt PR draft — ブランチはpush済み: satomasahiro2005/nxbt の fix-enable-vibration-ack (6c0902e)
# 提出URL: https://github.com/satomasahiro2005/nxbt/pull/new/fix-enable-vibration-ack
# base が Brikwerk/nxbt : master になっていることを確認して出す
# 本文中の #NNN は先に出したissueの番号に置き換える

## Title (そのままコピー)

Reply to Enable Vibration (0x48) with a plain ACK so games send rumble

## Body (以下をそのまま貼る、#NNN を差し替え)

Fixes #NNN

### What

One-byte protocol fix: reply to subcommand `0x48` (Enable Vibration) with a
plain ACK (`0x80`) instead of `0x82`.

### Why

With the stock `0x82` ACK, the console pairs fine and system rumble
(pairing buzz, Find Controllers, vibration on/off notification) reaches the
virtual controller, but **no game ever sends rumble** — the application
vibration path appears to be disabled console-side when the
enable-vibration reply is malformed. With `0x80`, games stream HD rumble to
the virtual controller in `0x10` output reports.

Basis for `0x80` being the correct reply:

- The documented ACK byte convention (dekuNukem `bluetooth_hid_notes.md`,
  input report byte 13): MSB set = ACK, low 7 bits = reply data type,
  `x00` for a simple ACK. The `0x48` reply carries no data.
- A real Joy-Con (L) sniffed over raw L2CAP acks `0x48` with `x80 x48`.
- `0x82` is the ACK-with-data type NXBT itself uses for the device info
  reply (subcommand `0x02`), so this looks like a copy-paste leftover.

### Testing

- Raspberry Pi (onboard BT), NXBT virtual `PRO_CONTROLLER`, retail Switch.
- Controlled A/B: in two otherwise-identical setups (re-pair in between),
  `0x82` produced zero game-rumble output reports and `0x80` produced a
  working game-rumble stream — this byte was the only difference.
- Sufficiency: with everything else left stock, the fix alone delivered
  ~90 output reports with real (non-neutral) HD rumble payloads in a short
  play test, verified end-to-end by forwarding them to a physical Joy-Con
  (L) over raw L2CAP and feeling the game rumble.

Two further real-hardware deviations that improve rumble delivery cadence
(but are not required for game rumble) are described in #NNN; happy to
follow up with separate PRs if there's interest. This PR intentionally
stays minimal.

### Limitations

I don't own a real Pro Controller, so the reference behaviour comes from
dekuNukem's protocol notes and from sniffing a real Joy-Con (L) rather than
from a captured Pro Controller session.
