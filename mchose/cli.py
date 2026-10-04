import argparse
import sys

from . import i18n
from .device import (EFFECT_BY_NAME, EFFECTS, LEVEL_MAX, PALETTE_SIZE, DeviceNotFound,
                     Keyboard, parse_color)


def print_light(state):
    e = state.effect
    print(f"effect:     {e.name} ({i18n.effect_label(e)})")
    if e.brightness:
        print(f"brightness: {state.brightness}/{LEVEL_MAX}")
    if e.speed:
        print(f"speed:      {state.speed}/{LEVEL_MAX}")
    if e.color:
        palette = "on" if state.multicolor else "off"
        print(f"color:      {state.hex_color}  (palette cycling {palette})")


def level(s):
    v = int(s)
    if not 0 <= v <= LEVEL_MAX:
        raise argparse.ArgumentTypeError(f"must be 0..{LEVEL_MAX}")
    return v


def color(s):
    try:
        return parse_color(s)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mchose", description="MCHOSE G87 control for Linux")
    ap.add_argument("--lang", choices=list(i18n.LANGUAGES),
                    help="interface language (default: saved setting, then system locale)")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("gui", help="open the settings window (default)").add_argument(
        "--hidden", action="store_true", help="start in the tray only")
    sub.add_parser("status", help="show lighting and battery")
    sub.add_parser("battery", help="print battery level")
    sub.add_parser("effects", help="list lighting effects")
    s = sub.add_parser("set", help="change lighting")
    s.add_argument("effect", choices=list(EFFECT_BY_NAME))
    s.add_argument("-b", "--brightness", type=level)
    s.add_argument("-s", "--speed", type=level)
    s.add_argument("-c", "--color", type=color, help="RRGGBB")
    s.add_argument("--palette", action=argparse.BooleanOptionalAction,
                   help="cycle the 7-color palette instead of a single color")
    for name in ("backup", "restore"):
        p = sub.add_parser(name, help=f"{name} lighting config to/from PREFIX-*.bin")
        p.add_argument("prefix", nargs="?", default="backup")
    args = ap.parse_args(argv)
    i18n.init(args.lang)

    if args.cmd in (None, "gui"):
        from .gui import run
        return run(hidden=getattr(args, "hidden", False))

    try:
        with Keyboard() as kb:
            if args.cmd == "status":
                print_light(kb.light())
                b = kb.battery()
                print(f"battery:    {b.level}%{' (charging)' if b.charging else ''}")
            elif args.cmd == "battery":
                print(kb.battery().level)
            elif args.cmd == "effects":
                for e in EFFECTS:
                    opts = [n for n, ok in (("brightness", e.brightness), ("speed", e.speed),
                                            ("color", e.color)) if ok]
                    print(f"{e.name:10} {i18n.effect_label(e):15} {', '.join(opts)}")
            elif args.cmd == "set":
                multi = None if args.palette is None else (PALETTE_SIZE if args.palette else 0)
                print_light(kb.set_light(EFFECT_BY_NAME[args.effect], args.brightness,
                                         args.speed, args.color, multi))
            elif args.cmd == "backup":
                kb.backup(args.prefix)
                print(f"saved {args.prefix}-perf.bin and {args.prefix}-color.bin")
            elif args.cmd == "restore":
                kb.restore(args.prefix)
                print_light(kb.light())
    except (DeviceNotFound, TimeoutError, OSError, ValueError) as e:
        sys.exit(f"mchose: {e}")
