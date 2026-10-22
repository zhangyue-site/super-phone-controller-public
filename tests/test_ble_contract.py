"""Cross-check real firmware UUID byte order against the updater's UUID strings."""
import re, unittest, uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class BleContractTests(unittest.TestCase):
    def test_board_and_phone_use_identical_services(self):
        board=(ROOT/'firmware-epaper/main/ble_ota.c').read_text()
        app=(ROOT/'app/lib/ble_ota_service.dart').read_text()
        for name, field in [('SVC','svc'),('CTRL','ctrl'),('STAT','stat')]:
            values=re.search(rf'{name}_UUID = BLE_UUID128_INIT\(([^)]+)\)',board)[1]
            actual=bytes(int(v.strip(),0) for v in values.split(','))[::-1]
            expected=re.search(rf"{field}Uuid = '([^']+)'",app)[1]
            self.assertEqual(str(uuid.UUID(bytes=actual)),expected)
    def test_audio_assets_are_bounded_16bit_samples(self):
        for path in (ROOT/'firmware-epaper/main/audio').glob('*.pcm'):
            self.assertGreater(path.stat().st_size,0)
            self.assertLessEqual(path.stat().st_size,96000)
            self.assertEqual(path.stat().st_size%2,0)
