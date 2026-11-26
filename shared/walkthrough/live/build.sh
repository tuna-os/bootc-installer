#!/usr/bin/env bash
# Build one installer and the mock daemon into /out. Runs inside the container.
# Usage: build.sh FRONTEND. /src is the repository, /out the cache, and
# /pins/fisherman and /pins/tunaos are the checkouts that PINS names.
set -euo pipefail
fe="$1"
export HOME=/out/home GOPATH=/out/go GOCACHE=/out/gocache GOFLAGS=-buildvcs=false
export CARGO_HOME=/out/cargo
mkdir -p /out/bin "$HOME"
git config --global --add safe.directory '*'

(cd /pins/fisherman/fisherman && CGO_ENABLED=0 go build -o /out/bin/fishermand ./cmd/fishermand)

case "$fe" in
kde)
	cmake -S /src/frontends/kde -B /out/kde -G Ninja -DCMAKE_BUILD_TYPE=Release \
		-DBUILD_TESTING=OFF -DCMAKE_INSTALL_PREFIX=/usr >/out/kde-configure.log
	cmake --build /out/kde
	;;
niri)
	(cd /src/frontends/niri/installer && CGO_ENABLED=0 go build -o /out/bin/tuna-installer-backend .)
	;;
cosmic)
	# The source tree is read-only here, and cargo writes next to it.
	rm -rf /tmp/b && mkdir /tmp/b
	tar -C /src --exclude=.git --exclude='*.png' -cf - frontends/cosmic shared data | tar -C /tmp/b -xf -
	(cd /tmp/b/frontends/cosmic && CARGO_TARGET_DIR=/out/cosmic-target cargo build --release --locked)
	mkdir -p /out/cosmic/release
	install -m 755 /out/cosmic-target/release/tuna-installer-cosmic /out/cosmic/release/
	strip /out/cosmic/release/tuna-installer-cosmic
	;;
xfce) ;;
gnome)
	# The patch series needs blueprint-compiler 0.20 or newer, which Fedora 44
	# has not got: the same build as the installer medium.
	if [[ ! -x /out/gnome/gnome-setup/usr/bin/gnome-setup ]]; then
		mkdir -p /out/gnome
		sed 's/^dnf -y install/: dnf -y install/' /pins/tunaos/installer-medium/frontends/gnome/build.sh \
			>/pins/tunaos/installer-medium/frontends/gnome/build-nodnf.sh
		bash /pins/tunaos/installer-medium/frontends/gnome/build-nodnf.sh /out/gnome
		rm -rf /out/gnome/meson-build /out/gnome/gnome-setup-src /out/cargo/registry/src
	fi
	;;
esac
