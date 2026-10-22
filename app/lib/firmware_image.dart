import 'dart:typed_data';
import 'package:crypto/crypto.dart';

/// Validates the same S3 app image contract as the private cloud publisher.
class FirmwareImage {
  final String version;
  final String sha;
  final String elfSha256;
  const FirmwareImage(this.version, this.sha, this.elfSha256);
  static const maxSize = 0x340000;

  static FirmwareImage parse(Uint8List bytes) {
    void reject(String message) => throw FormatException(message);
    if (bytes.length < 4096 || bytes.length > maxSize) {
      reject('固件大小无效，必须是槽位范围内的 app.bin');
    }
    final data = ByteData.sublistView(bytes);
    if (bytes[0] != 0xe9 ||
        bytes[1] < 1 ||
        bytes[1] > 16 ||
        data.getUint16(12, Endian.little) != 9) {
      reject('固件不是 ESP32-S3 应用镜像');
    }
    if (data.getUint32(28, Endian.little) < 256 ||
        data.getUint32(32, Endian.little) != 0xabcd5432) {
      reject('固件缺少有效应用描述');
    }
    String field(int offset) {
      final raw = bytes.sublist(offset, offset + 32);
      final end = raw.indexOf(0);
      if (end <= 0) reject('固件版本或项目字段无效');
      final value = String.fromCharCodes(raw.sublist(0, end));
      if (!RegExp(r'^[a-zA-Z0-9._-]{1,31}$').hasMatch(value)) {
        reject('固件版本或项目字段无效');
      }
      return value;
    }

    final version = field(48);
    if (field(80) != 'phone_controller_epaper') reject('固件与控制板项目不匹配');
    var offset = 24;
    var checksum = 0xef;
    for (var i = 0; i < bytes[1]; i++) {
      if (offset + 8 > bytes.length) reject('固件段头不完整');
      final size = data.getUint32(offset + 4, Endian.little);
      offset += 8;
      if (size > bytes.length - offset) reject('固件段数据不完整');
      for (var n = offset; n < offset + size; n++) {
        checksum ^= bytes[n];
      }
      offset += size;
    }
    final end = (offset ~/ 16 + 1) * 16;
    if (end > bytes.length || bytes[end - 1] != checksum) {
      reject('固件镜像校验失败');
    }
    if (bytes[23] != 1 || bytes.length != end + 32) {
      reject('固件缺少完整 SHA256 校验');
    }
    final digest = sha256.convert(Uint8List.sublistView(bytes, 0, end)).bytes;
    for (var i = 0; i < 32; i++) {
      if (bytes[end + i] != digest[i]) reject('固件 SHA256 校验失败');
    }
    return FirmwareImage(
        version,
        sha256.convert(bytes).toString(),
        bytes
            .sublist(176, 208)
            .map((b) => b.toRadixString(16).padLeft(2, '0'))
            .join());
  }
}
