# MCHOSE G87 Controller for Ubuntu

Control the RGB lighting and check the battery of the **MCHOSE G87** keyboard on Linux,
without the official M HUB web driver.

- GTK settings window: effect, brightness, speed, color, palette cycling
- System tray indicator with battery percentage, quick effect switching and a low-battery notification
- `mchose` command-line tool
- English and Vietnamese interface
- Talks to the keyboard directly over HID: no cloud, no browser, no root

Currently supported: MCHOSE G87 connected through its **2.4 GHz receiver** (USB ID `41e4:2001`).
Key remapping and macros are planned.

## Why

The official driver is a web app (WebHID) served from China. On Ubuntu it is slow for several reasons:

- the page loads slowly from outside China
- Linux browsers can't reach the keyboard without a udev rule
- the driver polls for wireless responses only once per second

The keyboard itself answers in about 60 ms.

## Install

Build and install the Debian package:

```sh
packaging/build-deb.sh                              # -> dist/mchose-ctl_<version>_all.deb
sudo apt install ./dist/mchose-ctl_0.2.2_all.deb
```

The package installs:

- `/usr/bin/mchose`
- a udev rule, so that the logged-in user can access the keyboard without root
- an app launcher, "MCHOSE G87"
- an autostart entry that starts the app hidden in the tray at login. You can turn it off in GNOME Tweaks under *Startup Applications*.

Dependencies (pulled in automatically): `python3-gi`, `gir1.2-gtk-3.0`, `gir1.2-ayatanaappindicator3-0.1`.
On GNOME, the tray icon needs the AppIndicator extension, which Ubuntu enables by default.

Uninstall with `sudo apt remove mchose-ctl`.

### Run from source

```sh
sudo cp data/70-mchose.rules /etc/udev/rules.d/
sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=hidraw
./mchose-bin
```

## Usage

```sh
mchose                         # open the settings window (and tray)
mchose gui --hidden            # tray only
mchose status                  # effect, brightness, speed, color, battery
mchose battery                 # battery level in %
mchose effects                 # list effects and which options they support
mchose set static -c ff0000 -b 4
mchose set breathing -c 00aaff -s 2
mchose set breathing --palette # cycle the built-in 7-color palette instead of one color
mchose set off
mchose backup [prefix]         # save the lighting config to prefix-perf.bin / prefix-color.bin
mchose restore [prefix]
```

Brightness and speed range from 0 to 4.

### Language

The interface is available in English and Vietnamese. By default it follows the system locale.
You can switch it from the drop-down in the settings window; the choice is saved in
`~/.config/mchose/config.json`. To override it for one run, use `mchose --lang en` or `mchose --lang vi`.

Effects: `static`, `breathing`, `rainbow`, `reactive`, `rain`, `ripple`, `stars`, `stream`, `flow`,
`shadow`, `sine`, `pinwheel`, `waterfall`, `flowers`, `off`.

## Protocol

The protocol was reverse-engineered from the M HUB web driver's JavaScript.

The vendor HID interface uses usage page `0xFF02`. Every packet is report `0x13`, 19 bytes:

```
[cmd, total, index, len, data × 14, checksum]
checksum = (0x13 + sum of the 18 preceding bytes) & 0xFF
```

| Block | Read | Write | Size |
|---|---|---|---|
| Performance: light mode, per-mode brightness/speed/palette, polling rate, … | `0x44` | `0x04` | 128 bytes |
| Colors: a 7-color RGB palette per mode, stored at `21 × mode` | `0x49` | `0x09` | 490 bytes, plus a 28-byte tail with a `5A A5` marker on write |
| Battery: `[level %, charging << 4 \| full]` | `0x4a` | — | 2 bytes |

- **Read:** send `[cmd, 0x01]`. The keyboard replies with `total` packets carrying 14 data bytes each.
- **Write:** split the payload into 14-byte chunks. Each chunk is acknowledged with a packet that echoes `cmd` and `index`.
- **Light mode:** stored at performance offset 10. For each mode, a `(brightness, speed << 4 | multicolor)` byte pair starts at offset 58.

The tool always reads, modifies and writes whole blocks, so bytes it doesn't understand are preserved.

## Project layout

```
mchose/device.py     protocol and high-level API (Keyboard, effects)
mchose/cli.py        command-line interface
mchose/gui.py        GTK 3 window and Ayatana tray indicator
mchose/i18n.py       UI strings (English, Vietnamese) and language setting
data/                udev rule, .desktop file
packaging/           Debian package build script and metadata
```

## License

[MIT](LICENSE)

## Disclaimer

This project is not affiliated with MCHOSE. Use it at your own risk. It never sends firmware-update commands.
