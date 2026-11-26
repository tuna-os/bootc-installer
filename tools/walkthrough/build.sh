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
	# gnome-setup from upstream at the PIN of tunaOS, with the tunaOS patch
	# series (installer-medium/frontends/gnome-setup), as the medium builds
	# it. The series needs blueprint-compiler 0.20 or newer; Fedora 44 has
	# an older one, so build the commit that the medium's build.sh names.
	if [[ ! -x /out/gnome/gnome-setup/usr/bin/gnome-setup ]]; then
		gs=/pins/tunaos/installer-medium/frontends/gnome-setup
		bp_ref="$(sed -n 's/^BP_REF=//p' /pins/tunaos/installer-medium/frontends/gnome/build.sh)"
		# shellcheck disable=SC1091
		source "${gs}/PIN"
		fetch() { # fetch DIR COMMIT REPO...: one commit, from the first repo that has it
			local dir="$1" commit="$2" repo
			shift 2
			rm -rf "${dir}"
			git init -q "${dir}"
			for repo in "$@"; do
				if git -C "${dir}" fetch -q --depth 1 "${repo}" "${commit}"; then
					git -C "${dir}" checkout -q FETCH_HEAD
					return 0
				fi
			done
			return 1
		}
		fetch /tmp/bp "${bp_ref}" https://gitlab.gnome.org/GNOME/blueprint-compiler.git \
			https://github.com/GNOME/blueprint-compiler.git
		meson setup /tmp/bp/build /tmp/bp --prefix=/usr >/dev/null
		meson install -C /tmp/bp/build >/dev/null
		fetch /tmp/gs-src "${GNOME_SETUP_PIN}" "${GNOME_SETUP_UPSTREAM}" \
			https://github.com/hanthor/gnome-setup.git
		rm -rf /tmp/gs-build
		"${gs}/apply-and-build" --source /tmp/gs-src --build-dir /tmp/gs-build -- \
			--prefix=/usr --libdir=lib --buildtype=release \
			-Dlive-marker-path=/run/tunaos/live -Dpost-wizard-command=
		mkdir -p /out/gnome/gnome-setup
		meson install -C /tmp/gs-build --destdir /out/gnome/gnome-setup >/dev/null
		rm -rf /tmp/gs-build /tmp/gs-src /tmp/bp
	fi
	;;
esac
