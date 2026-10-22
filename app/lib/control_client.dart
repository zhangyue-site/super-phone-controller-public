import 'dart:convert';
import 'dart:typed_data';
import 'package:http/http.dart' as http;
import 'ble_ota_service.dart';

/// Ephemeral BLE possession capability, kept only in memory.
class ControlClient {
  static const base =
      'https://erweima.zhangyue.site/phone-controller/app-control';
  final http.Client _http;
  String? _ticket;
  DateTime? _expires;
  ControlClient({http.Client? client}) : _http = client ?? http.Client();
  bool get authorized =>
      _ticket != null && _expires != null && DateTime.now().isBefore(_expires!);
  Future<Map<String, dynamic>> _post(String path, Map<String, dynamic> body,
      {bool auth = false}) async {
    final response = await _http
        .post(Uri.parse('$base/$path'),
            headers: {
              'Content-Type': 'application/json',
              if (auth) 'Authorization': 'Bearer $_ticket',
            },
            body: jsonEncode(body))
        .timeout(const Duration(seconds: 20));
    if (response.bodyBytes.length > 8192) {
      throw const FormatException('服务器响应过大');
    }
    final decoded = jsonDecode(utf8.decode(response.bodyBytes));
    if (decoded is! Map<String, dynamic>) {
      throw const FormatException('服务器响应无效');
    }
    if (response.statusCode != 200) {
      if (response.statusCode == 403) {
        _ticket = null;
        _expires = null;
      }
      throw FormatException(decoded['reply'] as String? ?? '请求失败，请查询状态后重试');
    }
    return decoded;
  }

  Future<void> authorize(BleOtaService service) async {
    final info = await service.readInfo();
    if (info == null) throw const FormatException('请先连接控制板');
    final challenge = await _post('challenge', {'device': info.device});
    final nonce = challenge['challenge'];
    if (nonce is! String || !RegExp(r'^[0-9a-f]{64}$').hasMatch(nonce)) {
      throw const FormatException('授权挑战无效');
    }
    final bytes = Uint8List.fromList(List.generate(
        32, (i) => int.parse(nonce.substring(i * 2, i * 2 + 2), radix: 16)));
    final proof = await service.signDownloadChallenge(bytes);
    final grant = await _post('authorize', {
      'device': info.device,
      'challenge': nonce,
      'proof': proof.map((b) => b.toRadixString(16).padLeft(2, '0')).join()
    });
    final ticket = grant['ticket'];
    final ttl = grant['expiresIn'];
    if (grant['scope'] != 'phone-commands' ||
        ticket is! String ||
        !RegExp(r'^[A-Za-z0-9_-]{43}$').hasMatch(ticket) ||
        ttl is! int ||
        ttl < 1 ||
        ttl > 300) {
      throw const FormatException('授权范围无效');
    }
    _ticket = ticket;
    _expires = DateTime.now().add(Duration(seconds: ttl));
  }

  Future<Map<String, dynamic>> command(String operation,
      {String? text, String? taskId}) async {
    if (!authorized) throw const FormatException('请先连接授权，授权约五分钟有效');
    return _post(
        'command',
        {
          'operation': operation,
          if (text != null) 'text': text,
          if (taskId != null) 'task_id': taskId
        },
        auth: true);
  }

  void close() {
    _ticket = null;
    _expires = null;
    _http.close();
  }
}
