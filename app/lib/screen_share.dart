import 'dart:convert';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'ble_ota_service.dart';
import 'screen_task_status.dart';

class ScreenShare {
  static const channel = MethodChannel('pcflash/screen');
  static const base =
      'https://erweima.zhangyue.site/phone-controller/app-screen';
  static Future<Map<String, dynamic>> _post(
      http.Client client, String path, Map<String, dynamic> body) async {
    final response = await client
        .post(Uri.parse('$base/$path'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode(body))
        .timeout(const Duration(seconds: 25));
    if (response.statusCode != 200 || response.bodyBytes.length > 4096) {
      throw const FormatException('屏幕共享授权失败，请重试');
    }
    final dynamic data = jsonDecode(response.body);
    if (data is! Map<String, dynamic>) throw const FormatException('共享授权格式无效');
    return data;
  }

  static Future<bool> isActive() async {
    final value = await channel.invokeMethod<String>('status');
    return value != null && (jsonDecode(value) as Map)['active'] == true;
  }

  static Future<void> start(BleOtaService service,
      {http.Client? client,
      bool Function()? isCurrent,
      String? usbSession}) async {
    void check() {
      if (isCurrent != null && !isCurrent()) throw StateError('共享请求已取消');
    }

    check();
    final info = await service.readInfo();
    check();
    if (info == null) throw const FormatException('请先更新控制板基础固件');
    final ownsClient = client == null;
    client ??= http.Client();
    String? issued;
    var handedOff = false;
    try {
      final challenge =
          await _post(client, 'challenge', {'device': info.device});
      check();
      final nonce = challenge['challenge'];
      if (nonce is! String || !RegExp(r'^[0-9a-f]{64}$').hasMatch(nonce)) {
        throw const FormatException('共享挑战无效');
      }
      final bytes = List.generate(
          32, (i) => int.parse(nonce.substring(i * 2, i * 2 + 2), radix: 16));
      final proof = await service.signDownloadChallenge(bytes);
      check();
      if (proof.length != 32) throw const FormatException('控制板授权失败');
      final grant = await _post(client, 'authorize', {
        'device': info.device,
        'challenge': nonce,
        'proof': proof.map((b) => b.toRadixString(16).padLeft(2, '0')).join()
      });
      final ticket = grant['ticket'];
      if (grant['scope'] != 'screen-frames' ||
          ticket is! String ||
          !RegExp(r'^[A-Za-z0-9_-]{43}$').hasMatch(ticket)) {
        throw const FormatException('共享凭证无效');
      }
      issued = ticket;
      check();
      await channel.invokeMethod<void>('start',
          {'ticket': ticket, if (usbSession != null) 'usbSession': usbSession});
      handedOff = true;
    } finally {
      if (issued != null && !handedOff) {
        try {
          await client.post(Uri.parse('$base/stop'), headers: {
            'Authorization': 'Bearer $issued'
          }).timeout(const Duration(seconds: 3));
        } catch (_) {/* Capability also expires server-side. */}
      }
      if (ownsClient) client.close();
    }
  }

  static Future<void> stop() => channel.invokeMethod<void>('stop');
  static Future<ScreenTaskStatus> status() async =>
      ScreenTaskStatus.parse(await channel.invokeMethod<String>('status') ??
          '{"capture":"未共享","task":""}');
}
