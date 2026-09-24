#!/usr/bin/env python3
"""Install and provision the standalone Android Demo using a caller-owned license."""
import argparse
from pathlib import Path
import subprocess

APP_ID = 'com.lits.tts.demo31'
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', default='adb')
    parser.add_argument('--serial', help='ADB target when multiple devices are connected')
    parser.add_argument('--sn', help='Actual license-bound device SN; defaults to ADB serial')
    parser.add_argument('--license', type=Path, required=True)
    parser.add_argument('--apk', type=Path, default=ROOT / 'apk/lits-dingqiao-tts-demo-vocos24k-3.1.apk')
    args = parser.parse_args()
    license_bytes = args.license.read_bytes()
    if not license_bytes or not args.apk.is_file():
        parser.error('A nonempty license and a valid APK path are required')
    adb = [args.adb] + (['-s', args.serial] if args.serial else [])
    sn = args.sn or subprocess.check_output(adb + ['get-serialno'], text=True).strip()
    if not sn or sn == 'unknown':
        parser.error('Device SN is unavailable')
    subprocess.run(adb + ['install', '-r', str(args.apk)], check=True)
    subprocess.run(adb + ['shell', 'am', 'force-stop', APP_ID], check=True)
    setup = f'run-as {APP_ID} sh -c "mkdir -p files/lits-tts-work files/tts-provisioning; rm -rf files/lits-tts-work/tts"'
    subprocess.run(adb + ['shell', setup], check=True)
    for filename, data in [('amphion-license.lic', license_bytes), ('device-sn.txt', sn.encode())]:
        command = f'run-as {APP_ID} sh -c "cat > files/tts-provisioning/{filename}; chmod 600 files/tts-provisioning/{filename}"'
        subprocess.run(adb + ['shell', command], input=data, check=True)
    subprocess.run(adb + ['shell', 'am', 'start', '-n', APP_ID + '/com.lits.tts.sample.MainActivity'], check=True)
    print('Demo installed and configured. Check the app for license activation and warmup results.')


if __name__ == '__main__':
    main()
