import 'dart:typed_data';
import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:pcflash/firmware_image.dart';

Uint8List fixture() {
  final bytes = Uint8List(4128);
  final data = ByteData.sublistView(bytes);
  bytes[0] = 0xe9;
  bytes[1] = 1;
  bytes[23] = 1;
  data.setUint16(12, 9, Endian.little);
  data.setUint32(28, 4048, Endian.little);
  data.setUint32(32, 0xabcd5432, Endian.little);
  bytes.setAll(48, 'test-1'.codeUnits);
  bytes.setAll(80, 'phone_controller_epaper'.codeUnits);
  var checksum = 0xef;
  for (var i = 32; i < 4080; i++) {
    checksum ^= bytes[i];
  }
  bytes[4095] = checksum;
  bytes.setAll(4096, sha256.convert(bytes.sublist(0, 4096)).bytes);
  return bytes;
}

void main() {
  test('valid S3 controller image is accepted', () {
    expect(FirmwareImage.parse(fixture()).version, 'test-1');
  });
  test('wrong chip and project rejected before transfer', () {
    final chip = fixture()..[12] = 0;
    expect(() => FirmwareImage.parse(chip), throwsFormatException);
    final project = fixture()..[80] = 120;
    expect(() => FirmwareImage.parse(project), throwsFormatException);
  });
  test('truncation checksum SHA and trailing bytes rejected', () {
    final original = fixture();
    for (final bytes in [
      Uint8List.sublistView(original, 0, 4100),
      fixture()..[4095] ^= 1,
      fixture()..[4127] ^= 1,
      Uint8List.fromList([...original, 0]),
    ]) {
      expect(() => FirmwareImage.parse(bytes), throwsFormatException);
    }
  });
}
