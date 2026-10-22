import 'dart:convert';
import 'dart:typed_data';
import 'package:crypto/crypto.dart';
import 'package:http/http.dart' as http;
import 'firmware_image.dart';

class DownloadedFirmware {
  final Uint8List bytes;
  final String version;
  const DownloadedFirmware(this.bytes, this.version);
}

class AppOtaClient {
  final Uri base;
  final http.Client _client;
  final bool _ownsClient;
  AppOtaClient(this.base, {http.Client? client})
      : _client = client ?? http.Client(),
        _ownsClient = client == null {
    if (base.scheme != 'https') throw ArgumentError('HTTPS required');
  }
  void close() {
    if (_ownsClient) _client.close();
  }

  Uri _uri(String path) => Uri.parse(
      "${base.toString().replaceFirst(RegExp(r'/$'), '')}/app-ota/$path");
  Future<Map<String, dynamic>> _post(
      String path, Map<String, dynamic> body) async {
    final response = await _client
        .post(_uri(path),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode(body))
        .timeout(const Duration(seconds: 25));
    if (response.statusCode != 200) {
      throw Exception('升级授权失败或已过期，请重新连接后重试（${response.statusCode}）');
    }
    if (response.bodyBytes.length > 4096) {
      throw const FormatException('升级服务响应过大');
    }
    final dynamic obj = jsonDecode(response.body);
    if (obj is! Map<String, dynamic>) throw const FormatException('升级服务响应无效');
    return obj;
  }

  Future<DownloadedFirmware> download(
      String device, Future<List<int>> Function(List<int>) sign) async {
    final challenge = await _post('challenge', {'device': device});
    final nonce = challenge['challenge'];
    if (nonce is! String || !RegExp(r'^[0-9a-f]{64}$').hasMatch(nonce)) {
      throw const FormatException('升级挑战无效');
    }
    final raw = List.generate(
        32, (i) => int.parse(nonce.substring(i * 2, i * 2 + 2), radix: 16));
    final proof = await sign(raw);
    if (proof.length != 32) throw const FormatException('控制板升级授权响应无效');
    final grant = await _post('authorize', {
      'device': device,
      'challenge': nonce,
      'proof': proof.map((b) => b.toRadixString(16).padLeft(2, '0')).join()
    });
    final size = grant['size'],
        digest = grant['sha256'],
        version = grant['version'],
        ticket = grant['ticket'];
    if (size is! int ||
        size < 4096 ||
        size > FirmwareImage.maxSize ||
        digest is! String ||
        !RegExp(r'^[0-9a-f]{64}$').hasMatch(digest) ||
        version is! String ||
        !RegExp(r'^[A-Za-z0-9._-]{1,31}$').hasMatch(version) ||
        ticket is! String ||
        !RegExp(r'^[A-Za-z0-9_-]{43}$').hasMatch(ticket)) {
      throw const FormatException('固件下载凭证无效');
    }
    final request = http.Request('GET', _uri('image'));
    request.headers['Authorization'] = 'Bearer $ticket';
    final response =
        await _client.send(request).timeout(const Duration(seconds: 25));
    if (response.statusCode != 200) throw Exception('固件下载失败，请重试');
    if (response.contentLength != null && response.contentLength != size) {
      throw const FormatException('固件下载长度不符');
    }
    final builder = BytesBuilder(copy: false);
    var received = 0;
    await for (final chunk
        in response.stream.timeout(const Duration(seconds: 30))) {
      received += chunk.length;
      if (received > size) throw const FormatException('固件下载超过声明长度');
      builder.add(chunk);
    }
    final bytes = builder.takeBytes();
    if (bytes.length != size || sha256.convert(bytes).toString() != digest) {
      throw const FormatException('固件下载不完整或 SHA256 校验失败，请重试');
    }
    return DownloadedFirmware(bytes, version);
  }
}
