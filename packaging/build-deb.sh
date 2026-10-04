#!/bin/sh
# Build dist/mchose-ctl_<version>_all.deb
set -e
cd "$(dirname "$0")/.."
VERSION=$(python3 -c 'import mchose; print(mchose.__version__)')
PKG=mchose-ctl
umask 022
ROOT=$(mktemp -d)
chmod 755 "$ROOT"
trap 'rm -rf "$ROOT"' EXIT

# code
install -d "$ROOT/usr/lib/$PKG/mchose"
install -m 644 mchose/*.py "$ROOT/usr/lib/$PKG/mchose/"
install -D -m 755 packaging/mchose.launcher "$ROOT/usr/bin/mchose"

# system integration
install -D -m 644 data/70-mchose.rules "$ROOT/usr/lib/udev/rules.d/70-mchose.rules"
install -D -m 644 data/io.github.mchose_ctl.desktop \
    "$ROOT/usr/share/applications/io.github.mchose_ctl.desktop"
install -d "$ROOT/etc/xdg/autostart"
sed 's|^Exec=.*|Exec=mchose gui --hidden|' data/io.github.mchose_ctl.desktop \
    > "$ROOT/etc/xdg/autostart/io.github.mchose_ctl.desktop"
echo "X-GNOME-Autostart-enabled=true" >> "$ROOT/etc/xdg/autostart/io.github.mchose_ctl.desktop"
chmod 644 "$ROOT/etc/xdg/autostart/io.github.mchose_ctl.desktop"

# docs
install -D -m 644 README.md "$ROOT/usr/share/doc/$PKG/README.md"
install -m 644 packaging/copyright "$ROOT/usr/share/doc/$PKG/copyright"

# control
install -d "$ROOT/DEBIAN"
sed "s/@VERSION@/$VERSION/; s/@SIZE@/$(du -sk --exclude=DEBIAN "$ROOT" | cut -f1)/" \
    packaging/control > "$ROOT/DEBIAN/control"
echo "/etc/xdg/autostart/io.github.mchose_ctl.desktop" > "$ROOT/DEBIAN/conffiles"
install -m 755 packaging/postinst packaging/postrm "$ROOT/DEBIAN/"

mkdir -p dist
dpkg-deb --root-owner-group -Zxz --build "$ROOT" "dist/${PKG}_${VERSION}_all.deb"
