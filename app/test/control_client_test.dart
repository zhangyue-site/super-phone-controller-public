import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:pcflash/control_client.dart';
import 'package:pcflash/ble_ota_service.dart';
import 'package:pcflash/board_info.dart';

class FakeBoard extends BleOtaService {
  @override
  Future<BoardInfo?> readInfo() async =>
      const BoardInfo('test-board', 'ci67', '', '', 2);
  @override
  Future<List<int>> signDownloadChallenge(List<int> nonce) async {
    expect(nonce, List.filled(32, 170));
    return List.filled(32, 187);
  }
}

void main() {
  test('commands require BLE capability and never send without it', () async {
    var requests = 0;
    final client = ControlClient(client: MockClient((request) async {
      requests++;
      return http.Response('{}', 200);
    }));
    expect(client.authorized, false);
    await expectLater(
        client.command('confirm', taskId: 'a' * 32), throwsFormatException);
    await expectLater(client.command('stop'), throwsFormatException);
    expect(requests, 0);
    client.close();
  });
  test('BLE proof grants command-only capability and 403 clears it', () async {
    var commands = 0;
    final client = ControlClient(client: MockClient((request) async {
      final body = jsonDecode(request.body) as Map;
      if (request.url.path.endsWith('/challenge')) {
        expect(body, {'device': 'test-board'});
        expect(request.headers.containsKey('Authorization'), false);
        return http.Response(jsonEncode({'challenge': 'a' * 64}), 200);
      }
      if (request.url.path.endsWith('/authorize')) {
        expect(body['proof'], 'b' * 64);
        return http.Response(
            jsonEncode({
              'ticket': 't' * 43,
              'scope': 'phone-commands',
              'expiresIn': 300
            }),
            200);
      }
      expect(request.headers['Authorization'], 'Bearer ${'t' * 43}');
      commands++;
      if (commands == 1) {
        expect(body, {'operation': 'prepare', 'text': '打开微信找到张三'});
        return http.Response(
            jsonEncode({'state': 'pending', 'task_id': 'c' * 32}), 200);
      }
      return http.Response(jsonEncode({'reply': 'expired'}), 403);
    }));
    await client.authorize(FakeBoard());
    expect(client.authorized, true);
    expect((await client.command('prepare', text: '打开微信找到张三'))['state'],
        'pending');
    await expectLater(
        client.command('confirm', taskId: 'c' * 32), throwsFormatException);
    expect(client.authorized, false);
    client.close();
  });
}
