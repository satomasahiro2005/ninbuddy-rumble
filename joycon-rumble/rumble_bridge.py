class RawJoyConRumbleBridge():
    """Forwards Switch rumble to a real Joy-Con L over raw L2CAP, from a worker
    thread so the NXBT<->Switch mainloop never blocks.

    IMPORTANT: this only activates when a SECOND Bluetooth adapter (hci1) is
    present, and binds the Joy-Con sockets to it. On a single adapter, holding
    the Joy-Con link (Pi as master) starves the Switch's inbound rumble reports
    -- confirmed by measurement; role-switch and sniff mode do not fix it (the
    Switch refuses to stay a slave, so the Pi is stuck bridging two piconets).
    With no hci1 the bridge stays completely inert and never touches hci0, so
    NinBuddy runs as a normal, smooth controller. See joycon-rumble/NOTES.md."""

    _NEUTRAL = bytes([0x00, 0x01, 0x40, 0x40, 0x00, 0x01, 0x40, 0x40])
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
        self._hci1 = None
        self._worker = Thread(target=self._run, daemon=True)
        self._worker.start()

    def _log(self, msg):
        try:
            with open("/tmp/rumble_debug.log", "a") as f:
                f.write("%.3f %s\n" % (time.time(), msg))
        except OSError:
            pass

    def _second_adapter(self):
        # BD address of hci1 if a dedicated second adapter is present, else None.
        import subprocess
        try:
            out = subprocess.check_output(
                ["hciconfig", "hci1"], timeout=2,
                stderr=subprocess.DEVNULL).decode()
        except Exception:
            return None
        for tok in out.split():
            if tok.count(":") == 5:
                return tok
        return None

    def _map_to_joycon(self, data):
        left, right = data[0:4], data[4:8]
        if left not in self._SILENT:
            active = left
        elif right not in self._SILENT:
            active = right
        else:
            active = bytes([0x00, 0x01, 0x40, 0x40])
        return active + active

    def handle_switch_report(self, report):
        if not report or len(report) < 11 or report[0] != 0xA2:
            return
        if report[1] not in (0x01, 0x10):
            return
        out = self._map_to_joycon(bytes(report[3:11]))
        with self._lock:
            self._latest = out

    def tick(self):
        pass

    def _run(self):
        inert_logged = False
        while self._running:
            self._hci1 = self._second_adapter()
            if not self._hci1:
                if not inert_logged:
                    self._log("no hci1: rumble bridge inert (single-adapter)")
                    inert_logged = True
                time.sleep(5.0)
                continue
            inert_logged = False
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
            self.logger.info("Raw Joy-Con L2CAP rumble ready (via hci1)")
            self._log("CONNECTED via hci1 %s" % self._hci1)
            return True
        except OSError as e:
            self._log("connect fail errno=%s" % e.errno)
            self._close_socks()
            return False

    def _pump(self):
        last_sent = None
        last_ka = 0.0
        try:
            while self._running:
                with self._lock:
                    data = self._latest
                now = time.time()
                if data != last_sent or (now - last_ka) > 1.0:
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
        # Bind to the dedicated second adapter so all Joy-Con paging/polling
        # happens on hci1, leaving hci0 entirely for the NXBT<->Switch link.
        sock.bind((self._hci1, 0))
        sock.connect((self._JOYCON_L, psm))
        return sock

    def _next_timer(self):
        self._timer = (self._timer + 1) & 0x0F
        return self._timer

    def _enable_vibration(self):
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
