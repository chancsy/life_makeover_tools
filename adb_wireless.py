"""
Wireless adb setup for all Life Makeover tools. The working address is saved in
common/config.json; get_adb() then reconnects to it automatically (and finds a
paired Wireless debugging device again over mDNS when its port has changed).

Usage:
    python adb_wireless.py pair                 Android 11+: Settings > Developer options > Wireless debugging >
                                                "Pair device with pairing code" - enter the IP:port and code shown
    python adb_wireless.py usb [PORT]           Any Android: device on USB now -> adb tcpip PORT (5555) -> Wi-Fi.
                                                Lasts until the device reboots; then unplug the cable.
    python adb_wireless.py connect HOST[:PORT]  Connect to an address (and save it)
    python adb_wireless.py status               Attached devices, saved address, mDNS-advertised devices
    python adb_wireless.py disconnect           Disconnect Wi-Fi devices and forget the saved address

Any tool also takes --connect HOST[:PORT].
"""

import sys

from common.lm_adb import new_adb, read_common_config, save_wireless_address


def cmd_pair(adb):
    print('On the device: Settings > Developer options > Wireless debugging (turn on) >')
    print('  "Pair device with pairing code". Keep that dialog open.')
    pair_addr = input('  Pairing IP address & port (e.g. 192.168.1.5:37123): ').strip()
    code = input('  Wi-Fi pairing code: ').strip()
    if not adb.pair(pair_addr, code):
        return 1
    print('Paired. Now the address on the Wireless debugging screen itself (NOT the pairing port).')
    host = pair_addr.rsplit(':', 1)[0]
    conn = input(f'  IP address & port [{host}:?]: ').strip()
    if conn.isdigit():
        conn = f'{host}:{conn}'
    if not conn:
        # The connect port is advertised over mDNS right after pairing
        found = [a for _, s, a in adb.mdns_services() if s.startswith('_adb-tls-connect') and a.startswith(host + ':')]
        if not found:
            print('No address given and none found over mDNS.')
            return 1
        conn = found[0]
    return cmd_connect(adb, conn)


def cmd_usb(adb, port=5555):
    devices = [d for d in adb.get_devices() if not adb.is_wireless(d)]
    if not devices:
        print('No USB device attached. Plug the device in with USB debugging on.')
        return 1
    adb.set_device(devices[0])
    print(f'USB device {devices[0]}: switching to Wi-Fi on port {port}...')
    serial = adb.switch_to_wifi(port)
    if not serial:
        return 1
    save_wireless_address(serial)
    print(f'Connected over Wi-Fi: {serial} (saved). You can unplug the cable.')
    print('Note: adb tcpip lasts until the device reboots; run this again after a reboot.')
    return 0


def cmd_connect(adb, address):
    serial = adb.connect(address)
    if not serial:
        return 1
    save_wireless_address(serial)
    print(f'Connected over Wi-Fi: {serial} (saved for the tools).')
    return 0


def cmd_status(adb):
    print('Attached devices:', adb.get_devices() or 'none')
    print('Saved Wi-Fi address:', read_common_config().get('adb', {}).get('wireless') or 'none')
    services = adb.mdns_services()
    print('mDNS-advertised devices:' if services else 'mDNS-advertised devices: none')
    for name, service, address in services:
        print(f'  {name}  {service}  {address}')
    return 0


def cmd_disconnect(adb):
    print(adb.disconnect())
    save_wireless_address(None)
    print('Forgot the saved Wi-Fi address.')
    return 0


def main(argv):
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__)
        return 0
    adb = new_adb()
    cmd, args = argv[0], argv[1:]
    if cmd == 'pair':
        return cmd_pair(adb)
    if cmd == 'usb':
        return cmd_usb(adb, int(args[0]) if args else 5555)
    if cmd == 'connect' and args:
        return cmd_connect(adb, args[0])
    if cmd == 'status':
        return cmd_status(adb)
    if cmd == 'disconnect':
        return cmd_disconnect(adb)
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
