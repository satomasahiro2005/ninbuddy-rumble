# Canonical (debug-free) Joy-Con L rumble bridge for NXBT.
#
# This class is injected into nxbt's controller/server.py, replacing the
# RawJoyConRumbleBridge placeholder. It also requires, at the top of
# server.py:
#     from threading import Thread, Lock
# and the ControllerServer must call, in its report loop:
#     self.rumble = RawJoyConRumbleBridge(self.logger)   # in __init__
#     self.rumble.handle_switch_report(reply)            # each mainloop iter
#     self.rumble.tick()                                 # each mainloop iter
#     self.rumble.close()                                # on shutdown
#
# See NOTES.md for the full findings. Apply with apply_patch.py.

class RawJoyConRumbleBridge():
    """Forwards Switch rumble output reports to a real Joy-Con L over raw
    L2CAP. All Bluetooth I/O to the Joy-Con runs in a dedicated worker thread
    so the NXBT realtime mainloop (which talks to the Switch) is never blocked
    by connects, reconnects, or a flaky Joy-Con link.

    NOTE: on a single Bluetooth adapter this cannot run at the same time as the
    NXBT<->Switch link -- an active Joy-Con ACL starves the Switch's inbound
    rumble reports (see NOTES.md). Intended for use with a second adapter
    (bind the sockets to hci1); left here as the working, proven bridge."""

    _NEUTRAL = bytes([0x00, 0x01, 0x40, 0x40, 0x00, 0x01, 0x40, 0x40])
    # A motor half is "silent" when zeroed or at the neutral carrier.
    _SILENT = (bytes([0x00, 0x00, 0x00, 0x00]), bytes([0x00, 0x01, 0x40, 0x40]))
    _JOYCON_L = "BC:74:4B:8B:98:82"
    _SOL_BLUETOOTH = 274
    _BT_SECURITY = 4
    _BT_SECURITY_LOW = 1
    _SOL_L2CAP = 6
    _L2CAP_LM = 3
    _L2CAP_LM_MASTER = 0x0001

    def __init__(self, logger):
        self.logger = logger
        self._lock = Lock()
        self._latest = self._NEUTRAL
        self._running = True
        self._ctrl = None
        self._intr = None
        self._timer = 0
        self._worker = Thread(target=self._run, daemon=True)
        self._worker.start()

    def _map_to_joycon(self, data):
        # Pro Controller rumble is left(0:4) + right(4:8); a Joy-Con L has one
        # motor. Forward whichever half is actually driven, duplicated into
        # both halves so the physical motor is hit regardless of which slot it
        # reads.
        left, right = data[0:4], data[4:8]
        if left not in self._SILENT:
            active = left
        elif right not in self._SILENT:
            active = right
        else:
            active = bytes([0x00, 0x01, 0x40, 0x40])
        return active + active

    # -- called from the NXBT mainloop; must never block --
    def handle_switch_report(self, report):
        if not report or len(report) < 11 or report[0] != 0xA2:
            return
        # Output reports 0x01 (subcommand) and 0x10 (rumble) both carry the
        # 8 raw rumble bytes at offsets 3..10.
        if report[1] not in (0x01, 0x10):
            return
        out = self._map_to_joycon(bytes(report[3:11]))
        with self._lock:
            self._latest = out

    def tick(self):
        # Pacing is owned by the worker thread now; kept for API compatibility.
        pass

    # -- worker thread owns the Joy-Con link --
    def _run(self):
        while self._running:
            if not self._connect():
                time.sleep(1.0)
                continue
            self._pump()

    def _connect(self):
        try:
            self._close_socks()
            self._ctrl = self._connect_channel(0x11)
            self._intr = self._connect_channel(0x13)
            self._enable_vibration()
            self.logger.info("Raw Joy-Con L2CAP rumble ready")
            return True
        except OSError:
            self._close_socks()
            return False

    def _pump(self):
        # Send only when the rumble value changes, plus a low-rate keepalive.
        last_sent = None
        last_ka = 0.0
        try:
            while self._running:
                with self._lock:
                    data = self._latest
                now = time.time()
                if data != last_sent or (now - last_ka) > 0.2:
                    self._send_rumble(data)
                    last_sent = data
                    last_ka = now
                time.sleep(0.008)
        except OSError:
            self._close_socks()

    def _connect_channel(self, psm):
        sock = socket.socket(
            socket.AF_BLUETOOTH,
            socket.SOCK_SEQPACKET,
            socket.BTPROTO_L2CAP)
        sock.settimeout(8)
        sock.setsockopt(
            self._SOL_BLUETOOTH,
            self._BT_SECURITY,
            bytes([self._BT_SECURITY_LOW, 0]))
        sock.setsockopt(
            self._SOL_L2CAP,
            self._L2CAP_LM,
            self._L2CAP_LM_MASTER.to_bytes(4, "little"))
        sock.connect((self._JOYCON_L, psm))
        return sock

    def _next_timer(self):
        self._timer = (self._timer + 1) & 0x0F
        return self._timer

    def _enable_vibration(self):
        # Real Joy-Cons ignore rumble until vibration is enabled via subcommand
        # 0x48 0x01. 0xA2 is the HIDP DATA/output header on the interrupt PSM.
        report = bytes([0xA2, 0x01, self._next_timer()]) \
            + self._NEUTRAL + bytes([0x48, 0x01])
        self._intr.send(report)

    def _send_rumble(self, rumble_bytes):
        report = bytes([0xA2, 0x10, self._next_timer()]) + bytes(rumble_bytes)
        self._intr.send(report)

    def _close_socks(self):
        for sock in (self._intr, self._ctrl):
            if sock is None:
                continue
            try:
                sock.close()
            except OSError:
                pass
        self._intr = None
        self._ctrl = None

    def close(self):
        self._running = False
        try:
            if self._intr is not None:
                self._intr.send(
                    bytes([0xA2, 0x10, self._next_timer()]) + self._NEUTRAL)
        except OSError:
            pass
        self._close_socks()
