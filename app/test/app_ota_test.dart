import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:crypto/crypto.dart';
import 'package:pcflash/app_ota_client.dart';
import 'package:pcflash/board_info.dart';

Map<String, dynamic> info(
        {String boot = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
        String version = 'ci99',
        String elf =
            'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
        int state = 2,
        String device = 'one'}) =>
    {
      'protocol': 1,
      'device': device,
      'version': version,
      'elfSha256': elf,
      'boot': boot,
      'imageState': state
    };
void main() {
  test('boot confirmation requires new boot, correct identity and valid image',
      () {
    final before = BoardInfo.parse(utf8.encode(jsonEncode(info())));
    bool matches(Map<String, dynamic> data) =>
        BoardInfo.parse(utf8.encode(jsonEncode(data)))
            .confirms(before, 'ci99', 'b' * 64);
    expect(matches(info()), isFalse);
    expect(matches(info(boot: 'c' * 32)), isTrue);
    expect(matches(info(boot: 'c' * 32, state: 1)), isFalse);
    expect(matches(info(boot: 'c' * 32, version: 'old')), isFalse);
    expect(matches(info(boot: 'c' * 32, device: 'two')), isFalse);
    expect(matches(info(boot: 'c' * 32, elf: 'd' * 64)), isFalse);
    expect(() => BoardInfo.parse(utf8.encode(jsonEncode(info(boot: '')))),
        throwsFormatException);
  });
  test('download exchanges BLE proof and checks bounded image SHA and size',
      () async {
    final data = Uint8List.fromList(List.filled(4096, 1));
    final digest = sha256.convert(data).toString();
    var signed = false;
    final client = MockClient((request) async {
      expect(request.url.origin, 'https://example.test');
      switch (request.url.path) {
        case '/app-ota/challenge':
          return http.Response(jsonEncode({'challenge': 'a' * 64}), 200);
        case '/app-ota/authorize':
          expect(signed, isTrue);
          expect(jsonDecode(request.body)['proof'], 'b' * 64);
          return http.Response(
              jsonEncode({
                'version': 'ci99',
                'size': 4096,
                'sha256': digest,
                'ticket': 't' * 43
              }),
              200);
        case '/app-ota/image':
          expect(request.headers['Authorization'],
              'Bearer ttttttttttttttttttttttttttttttttttttttttttt');
          expect(request.url.query, isEmpty);
          return http.Response.bytes(data, 200);
      }
      return http.Response('', 404);
    });
    final result =
        await AppOtaClient(Uri.parse('https://example.test'), client: client)
            .download('one', (nonce) async {
      expect(nonce, List.filled(32, 0xaa));
      signed = true;
      return List.filled(32, 0xbb);
    });
    expect(result.bytes, data);
    expect(result.version, 'ci99');
  });
  test('denied authorization and corrupted payload never reach BLE transfer',
      () async {
    final bad = MockClient((r) async => http.Response('{}', 403));
    await expectLater(
        AppOtaClient(Uri.parse('https://example.test'), client: bad)
            .download('one', (_) async => []),
        throwsA(isA<Exception>()));
    final badHash = MockClient((r) async {
      if (r.url.path.endsWith('challenge')) {
        return http.Response(jsonEncode({'challenge': 'a' * 64}), 200);
      }
      if (r.url.path.endsWith('authorize')) {
        return http.Response(
            jsonEncode({
              'version': 'ci99',
              'size': 4096,
              'sha256': 'c' * 64,
              'ticket': 't' * 43
            }),
            200);
      }
      return http.Response.bytes(List.filled(4096, 1), 200);
    });
    await expectLater(
        AppOtaClient(Uri.parse('https://example.test'), client: badHash)
            .download('one', (_) async => List.filled(32, 0xbb)),
        throwsFormatException);
  });
}
