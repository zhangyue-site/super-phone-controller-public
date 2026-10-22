#!/system/bin/sh
# Run only on the authorized target phone. No package installation, no Wi-Fi.
# Default 40 rounds; configurable up to 120. No audio, screen or user data.
rounds=${CONTROLLER_CAPTURE_ROUNDS:-40}
case "$rounds" in *[!0-9]*|"") rounds=40;; esac
[ "$rounds" -ge 1 ] && [ "$rounds" -le 120 ] || rounds=40
for tick in $(seq 1 "$rounds"); do
 date '+%H:%M:%S'
 for path in /sys/class/net/usb* /sys/class/net/eth*; do
  [ -e "$path" ] || continue
  iface=${path##*/}
  ip -brief address show dev "$iface"
  ip route show dev "$iface"
  ping -I "$iface" -c 1 -W 1 192.168.77.1
 done
 sleep 2
done
