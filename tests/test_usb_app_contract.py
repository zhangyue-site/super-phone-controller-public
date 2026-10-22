import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID = '{http://schemas.android.com/apk/res/android}'

class UsbAppContractTest(unittest.TestCase):
    def test_usb_launch_matches_actual_firmware_modes_and_not_rom(self):
        firmware = (ROOT / 'firmware-epaper/main/usb.cpp').read_text()
        vid = int(re.search(r'idVendor\s*=\s*(0x[0-9a-f]+)', firmware)[1], 16)
        modes = re.search(r'idProduct=\(hid\?(0x[0-9a-f]+):(0x[0-9a-f]+)\)\|\(NETWORK_INTERFACES\?(0x[0-9a-f]+):0\)', firmware)
        self.assertIsNotNone(modes)
        hid, safe, network = (int(x, 16) for x in modes.groups())
        xml = ET.parse(ROOT / 'app/android/app/src/main/res/xml/usb_board_filter.xml')
        actual = {(int(x.attrib['vendor-id']), int(x.attrib['product-id'])) for x in xml.findall('usb-device')}
        self.assertEqual(actual, {(vid, p | n) for p in (hid, safe) for n in (0, network)})
        self.assertNotIn((vid, 0x1001), actual)
        for item in xml.findall('usb-device'):
            self.assertEqual(set(item.attrib), {'vendor-id', 'product-id'})

    def test_manifest_registers_usb_launch_without_requiring_usb_for_manual_ble(self):
        manifest = ET.parse(ROOT / 'app/android/app/src/main/AndroidManifest.xml')
        feature = next(x for x in manifest.findall('uses-feature') if x.get(ANDROID + 'name') == 'android.hardware.usb.host')
        self.assertEqual(feature.get(ANDROID + 'required'), 'false')
        activity = next(x for x in manifest.findall('application/activity') if x.get(ANDROID + 'name') == '.MainActivity')
        self.assertEqual(activity.get(ANDROID + 'launchMode'), 'singleTask')
        self.assertTrue(any(x.get(ANDROID + 'name') == 'android.hardware.usb.action.USB_DEVICE_ATTACHED' for x in activity.findall('intent-filter/action')))
        meta = next(x for x in activity.findall('meta-data') if x.get(ANDROID + 'name') == 'android.hardware.usb.action.USB_DEVICE_ATTACHED')
        self.assertEqual(meta.get(ANDROID + 'resource'), '@xml/usb_board_filter')

if __name__ == '__main__':
    unittest.main()
