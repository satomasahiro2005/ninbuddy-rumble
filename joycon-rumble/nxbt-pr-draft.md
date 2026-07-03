# nxbt PR draft — ブランチはpush済み: satomasahiro2005/nxbt の fix-enable-vibration-ack
# 提出URL: https://github.com/satomasahiro2005/nxbt/pull/new/fix-enable-vibration-ack
# base が Brikwerk/nxbt : master になっていることを確認して出す
# 本文中の #NNN は先に出したissueの番号に置き換える

## Title (そのままコピー)

Reply to Enable Vibration (0x48) with a plain ACK so games send rumble

## Body (以下をそのまま貼る、#NNN を差し替え)

Fixes #NNN

### What

One-byte protocol fix: reply to subcommand `0x48` (Enable Vibration) with a
plain ACK (`0x80`), as a real controller does, instead of `0x82`.

### Why

With the stock `0x82` ACK, the console pairs fine and system rumble
(pairing buzz, Find Controllers, vibration on/off notification) reaches the
virtual controller, but **no game ever sends rumble** — the application
vibration path appears to be disabled console-side when the
enable-vibration reply is malformed. With `0x80`, games stream HD rumble to
the virtual controller in `0x10` output reports.

`0x82` is the correct ACK for subcommand `0x02` (Request Device Info,
ACK + data type `0x02`), which is likely where the value was copied from.
dekuNukem's `bluetooth_hid_subcommands_notes.md` documents the `0x48` reply
as `x80 x48`.

### Testing

- Raspberry Pi (onboard BT), NXBT virtual `PRO_CONTROLLER`, retail Switch.
- Before: logged `itr.recv()` in the mainloop during gameplay — zero
  non-neutral rumble payloads from games; system rumble present.
- After (re-pair required): games produce a steady stream of `0x10` output
  reports with real HD rumble payloads, verified end-to-end by forwarding
  them to a physical Joy-Con (L) over raw L2CAP and feeling the game
  rumble.

Note: my test rig also streams input reports every tick (instead of the
`cached_msg` dedup) and generates `vibrator_report` from consumed rumble
frames instead of the static `0xA0` — details in #NNN. I can follow up with
separate PRs for those if there's interest; this PR intentionally stays
minimal.

### Limitations

I don't own a real Pro Controller, so the reference behaviour comes from
dekuNukem's protocol notes and from sniffing a real Joy-Con (L) rather than
from a captured Pro Controller session.
