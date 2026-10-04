"""MCHOSE G87 protocol over the 2.4G dongle (41e4:2001).

Reverse-engineered from the M HUB web driver. Every packet is HID report
0x13, 19 bytes: [cmd, total, index, len, data(14), checksum], where
checksum = (0x13 + sum(previous 18 bytes)) & 0xFF.
"""
import fcntl
import glob
import os
import select
import time
from dataclasses import dataclass

VID, PID = 0x41E4, 0x2001
REPORT_ID = 0x13
CHUNK = 14

CMD_GET_PERF, CMD_SET_PERF = 0x44, 0x04
CMD_GET_COLOR, CMD_SET_COLOR = 0x49, 0x09
CMD_GET_BATTERY = 0x4A

PERF_LEN = 128
OFF_LIGHT_MODE = 10
COLOR_LEN = 490
# the web driver appends this tail (with the 5A A5 marker) to every color write
COLOR_TAIL = bytes(14) + bytes([0, 0, 0x5A, 0xA5]) + bytes(10)

LEVEL_MAX = 4  # brightness and speed range 0..LEVEL_MAX
PALETTE_SIZE = 7  # multicolor value that cycles the whole 7-color palette


@dataclass(frozen=True)
class Effect:
    mode: int
    name: str
    label: str
    perf_offset: int | None  # (brightness, speed<<4 | multicolor) pair
    brightness: bool
    speed: bool
    color: bool


# Mode numbers, offsets and capability flags as used by M HUB for the G87.
EFFECTS = [
    Effect(1, "static", "Tĩnh", 58, True, False, True),
    Effect(2, "breathing", "Thở", 60, True, True, True),
    Effect(3, "rainbow", "Cầu vồng", 62, True, True, False),
    Effect(4, "reactive", "Phản hồi phím", 64, True, True, True),
    Effect(5, "rain", "Mưa rơi", 66, True, True, True),
    Effect(7, "ripple", "Gợn sóng", 70, True, True, True),
    Effect(8, "stars", "Sao trời", 72, True, True, True),
    Effect(10, "stream", "Dòng chảy", 76, True, True, True),
    Effect(11, "flow", "Trôi theo sóng", 78, True, True, True),
    Effect(12, "shadow", "Bóng đuổi", 80, True, True, True),
    Effect(13, "sine", "Sóng sin", 82, True, True, True),
    Effect(15, "pinwheel", "Chong chóng", 84, False, False, False),
    Effect(16, "waterfall", "Thác bảy màu", 88, True, True, False),
    Effect(17, "flowers", "Hoa nở", 90, False, False, False),
    Effect(0, "off", "Tắt đèn", None, False, False, False),
]
EFFECT_BY_MODE = {e.mode: e for e in EFFECTS}
EFFECT_BY_NAME = {e.name: e for e in EFFECTS}


class DeviceNotFound(Exception):
    pass


@dataclass
class LightState:
    effect: Effect
    brightness: int | None = None
    speed: int | None = None
    multicolor: int | None = None
    color: tuple[int, int, int] | None = None

    @property
    def hex_color(self):
        return None if self.color is None else "#%02x%02x%02x" % self.color


@dataclass
class Battery:
    level: int
    charging: bool


def find_device():
    for d in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            with open(f"{d}/device/uevent") as f:
                uevent = f.read()
            with open(f"{d}/device/report_descriptor", "rb") as f:
                desc = f.read()
        except OSError:
            continue
        # the vendor interface starts with Usage Page 0xFF02
        if f"{VID:08X}:{PID:08X}" in uevent and desc.startswith(b"\x06\x02\xff"):
            return "/dev/" + os.path.basename(d)
    raise DeviceNotFound("MCHOSE G87 not found (is the dongle plugged in?)")


def _lock_path():
    return os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "mchose.lock")


class Keyboard:
    """One exclusive session with the keyboard: `with Keyboard() as kb: ...`"""

    def __init__(self, path=None):
        self.path = path or find_device()

    def __enter__(self):
        self.lock = open(_lock_path(), "w")
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        try:
            self.fd = os.open(self.path, os.O_RDWR)
        except OSError:
            self.lock.close()
            raise
        return self

    def __exit__(self, *exc):
        os.close(self.fd)
        self.lock.close()

    # --- transport -------------------------------------------------------

    def _send(self, body):
        body = bytes(body).ljust(18, b"\0")
        os.write(self.fd, bytes([REPORT_ID]) + body + bytes([(REPORT_ID + sum(body)) & 0xFF]))

    def _recv(self, timeout, first_timeout=None):
        """Yield report-0x13 payloads (without report id) until `timeout` passes with none.

        `first_timeout` allows a longer wait for the first packet: a sleeping
        keyboard takes a while to wake up and answer.
        """
        deadline = time.monotonic() + (first_timeout or timeout)
        while (left := deadline - time.monotonic()) > 0:
            if not select.select([self.fd], [], [], left)[0]:
                return
            pkt = os.read(self.fd, 64)
            if pkt and pkt[0] == REPORT_ID:
                deadline = time.monotonic() + timeout
                yield pkt[1:]

    def _drain(self):
        for _ in self._recv(0.01):
            pass

    def read_block(self, cmd, attempts=4, timeout=0.2, first_timeout=1.0):
        # the first request after the keyboard idles can lose packets: just retry
        for _ in range(attempts):
            self._drain()
            self._send([cmd, 0x01])
            data, expected = bytearray(), 0
            for p in self._recv(timeout, first_timeout):
                if p[0] != cmd or p[2] != expected:
                    continue
                data += p[4:18]
                expected += 1
                if expected == p[1]:
                    return bytes(data)
        raise TimeoutError(f"no complete response to 0x{cmd:02x}")

    def write_block(self, cmd, payload, last_len):
        chunks = [payload[i:i + CHUNK] for i in range(0, len(payload), CHUNK)]
        self._drain()
        for idx, chunk in enumerate(chunks):
            length = last_len(chunk) if idx == len(chunks) - 1 else CHUNK
            for attempt in range(3):
                if attempt:
                    self._drain()
                self._send([cmd, len(chunks), idx, length, *chunk])
                if any(p[0] == cmd and p[2] == idx for p in self._recv(0.5)):
                    break
            else:
                raise TimeoutError(f"no ack for 0x{cmd:02x} packet {idx}")

    # --- raw blocks ------------------------------------------------------

    def get_perf(self):
        return bytearray(self.read_block(CMD_GET_PERF)[:PERF_LEN])

    def set_perf(self, perf):
        self.write_block(CMD_SET_PERF, bytes(perf), len)

    def get_colors(self):
        return bytearray(self.read_block(CMD_GET_COLOR)[:COLOR_LEN])

    def set_colors(self, colors):
        self.write_block(CMD_SET_COLOR, bytes(colors) + COLOR_TAIL,
                         lambda c: len(bytes(c).rstrip(b"\0")))

    # --- high level ------------------------------------------------------

    def battery(self):
        data = self.read_block(CMD_GET_BATTERY)
        return Battery(level=data[0], charging=bool(data[1] >> 4))

    def light(self):
        perf = self.get_perf()
        effect = EFFECT_BY_MODE.get(perf[OFF_LIGHT_MODE])
        if effect is None:
            effect = Effect(perf[OFF_LIGHT_MODE], f"mode{perf[OFF_LIGHT_MODE]}",
                            f"Chế độ {perf[OFF_LIGHT_MODE]}", None, False, False, False)
        state = LightState(effect)
        if effect.perf_offset is not None:
            o = effect.perf_offset
            state.brightness = perf[o]
            state.speed = perf[o + 1] >> 4
            state.multicolor = perf[o + 1] & 0x0F
        if effect.color:
            c = self.get_colors()[21 * effect.mode:21 * effect.mode + 3]
            state.color = tuple(c)
        return state

    def set_light(self, effect, brightness=None, speed=None, color=None, multicolor=None):
        """Switch to `effect`, changing only the given settings. Returns the new state."""
        if color is not None and multicolor is None:
            multicolor = 0
        perf = self.get_perf()
        perf[OFF_LIGHT_MODE] = effect.mode
        if effect.perf_offset is not None:
            o = effect.perf_offset
            if brightness is not None:
                perf[o] = max(0, min(LEVEL_MAX, brightness))
            old_speed, old_multi = perf[o + 1] >> 4, perf[o + 1] & 0x0F
            new_speed = old_speed if speed is None else max(0, min(LEVEL_MAX, speed))
            new_multi = old_multi if multicolor is None else multicolor
            perf[o + 1] = (new_speed & 0x0F) << 4 | (new_multi & 0x0F)
        self.set_perf(perf)
        if color is not None and effect.color:
            colors = self.get_colors()
            colors[21 * effect.mode:21 * effect.mode + 3] = bytes(color)
            self.set_colors(colors)
        return self.light()

    def backup(self, prefix):
        with open(f"{prefix}-perf.bin", "wb") as f:
            f.write(self.get_perf())
        with open(f"{prefix}-color.bin", "wb") as f:
            f.write(self.get_colors())

    def restore(self, prefix):
        with open(f"{prefix}-perf.bin", "rb") as f:
            perf = f.read()
        with open(f"{prefix}-color.bin", "rb") as f:
            colors = f.read()
        if len(perf) != PERF_LEN or len(colors) != COLOR_LEN:
            raise ValueError("backup files have the wrong size")
        self.set_colors(colors)
        self.set_perf(perf)


def parse_color(s):
    s = s.strip().lstrip("#")
    if len(s) != 6:
        raise ValueError(f"invalid color {s!r}, expected RRGGBB")
    return tuple(bytes.fromhex(s))
