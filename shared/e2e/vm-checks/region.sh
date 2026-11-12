# shellcheck shell=bash
# Guest check for the E2E (install <frontend>) job (#325): the booted
# system has the locale, the keyboard layout and the time zone of the
# frontend's recipe, and an encrypted root is open. Sourced by fisherman's
# scripts/boot-verify.sh (BOOTCREW_GUEST_CHECKS) in a subshell once SSH
# answers, with ssh_root set. shared/e2e/vm-install.sh exports the values
# of the recipe: E2E_LOCALE, E2E_KEYBOARD (the XKB layout), E2E_TIMEZONE
# and E2E_ENCRYPTED (true or false). An empty value is not checked.
set -u
fail=0
pass() { echo "  PASS: $*"; }
bad() { echo "  FAIL: $*"; fail=1; }

status=$(ssh_root 'localectl status' 2>&1 || true)
echo "$status" | sed 's/^/  localectl: /'

if [ -n "${E2E_LOCALE:-}" ]; then
  conf=$(ssh_root 'cat /etc/locale.conf' 2>/dev/null || true)
  if echo "$conf" | grep -qxF "LANG=$E2E_LOCALE"; then
    pass "/etc/locale.conf has LANG=$E2E_LOCALE"
  else
    bad "/etc/locale.conf has no LANG=$E2E_LOCALE: $(echo "$conf" | tr '\n' ' ')"
  fi
  if echo "$status" | grep -Eq "System Locale:.*LANG=$E2E_LOCALE([[:space:]]|$)"; then
    pass "localectl reports LANG=$E2E_LOCALE"
  else
    bad "localectl does not report LANG=$E2E_LOCALE"
  fi
fi

if [ -n "${E2E_KEYBOARD:-}" ]; then
  vconsole=$(ssh_root 'cat /etc/vconsole.conf' 2>/dev/null || true)
  echo "$vconsole" | sed 's/^/  vconsole.conf: /'
  if echo "$vconsole" | grep -qxF "XKBLAYOUT=$E2E_KEYBOARD"; then
    pass "/etc/vconsole.conf has XKBLAYOUT=$E2E_KEYBOARD"
  else
    bad "/etc/vconsole.conf has no XKBLAYOUT=$E2E_KEYBOARD"
  fi
  keymap=$(echo "$vconsole" | sed -n 's/^KEYMAP=//p' | tr -d '"')
  if [ -n "$keymap" ] && [ "$keymap" != "us" ]; then
    pass "/etc/vconsole.conf has the console keymap $keymap"
  else
    bad "/etc/vconsole.conf has no console keymap for $E2E_KEYBOARD (KEYMAP=${keymap:-})"
  fi
  if echo "$status" | grep -Eq "X11 Layout:[[:space:]]*$E2E_KEYBOARD$"; then
    pass "localectl reports the X11 layout $E2E_KEYBOARD"
  else
    bad "localectl does not report the X11 layout $E2E_KEYBOARD"
  fi
  if [ "${E2E_ENCRYPTED:-false}" = "true" ] && [ -n "$keymap" ]; then
    # The passphrase prompt runs in the initrd, before /etc is read:
    # fisherman puts the keymap on the kernel command line for it.
    if ssh_root 'cat /proc/cmdline' 2>/dev/null | tr ' ' '\n' | grep -qxF "rd.vconsole.keymap=$keymap"; then
      pass "the kernel command line has rd.vconsole.keymap=$keymap"
    else
      bad "the kernel command line has no rd.vconsole.keymap=$keymap"
    fi
  fi
fi

if [ -n "${E2E_TIMEZONE:-}" ]; then
  zone=$(ssh_root 'timedatectl show -p Timezone --value' 2>/dev/null || true)
  link=$(ssh_root 'readlink /etc/localtime' 2>/dev/null || true)
  if [ "$zone" = "$E2E_TIMEZONE" ]; then
    pass "timedatectl reports the time zone $zone"
  else
    bad "timedatectl reports the time zone '${zone:-}', not $E2E_TIMEZONE"
  fi
  case "$link" in
    */zoneinfo/"$E2E_TIMEZONE") pass "/etc/localtime points to $link" ;;
    *) bad "/etc/localtime points to '${link:-}', not zoneinfo/$E2E_TIMEZONE" ;;
  esac
fi

if [ "${E2E_ENCRYPTED:-false}" = "true" ]; then
  # SSH answers, so the system came up. The root must be on an open LUKS
  # device: the passphrase typed at the prompt unlocked it.
  crypt=$(ssh_root 'lsblk -nrpo NAME,TYPE' 2>/dev/null | awk '$2 == "crypt" { print $1 }' || true)
  root=$(ssh_root 'findmnt -no SOURCE /sysroot 2>/dev/null || findmnt -no SOURCE /' 2>/dev/null || true)
  echo "  open LUKS devices: ${crypt:-none}; root: ${root:-?}"
  if [ -n "$crypt" ] && echo "$crypt" | grep -qxF "${root%%\[*}"; then
    pass "the root ${root%%\[*} is the open LUKS device"
  else
    bad "the root is not on an open LUKS device"
  fi
fi
exit "$fail"
