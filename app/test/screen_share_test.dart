import 'dart:convert';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:pcflash/ble_ota_service.dart';
import 'package:pcflash/board_info.dart';
import 'package:pcflash/screen_share.dart';

class Board extends BleOtaService {
  @override
  Future<BoardInfo?> readInfo() async =>
      BoardInfo('epaper-01', 'test', 'a' * 64, 'b' * 32, 2);
  @override
  Future<List<int>> signDownloadChallenge(List<int> value) async =>
      List.filled(32, 1);
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test(
      'late grant after page/USB cancellation is revoked without opening consent',
      () async {
    var current = true;
    var nativeCalls = 0;
    var revoked = false;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(ScreenShare.channel, (_) async {
      nativeCalls++;
      return null;
    });
    addTearDown(() => TestDefaultBinaryMessengerBinding
        .instance.defaultBinaryMessenger
        .setMockMethodCallHandler(ScreenShare.channel, null));
    final client = MockClient((r) async {
      if (r.url.path.endsWith('/challenge')) {
        return http.Response(jsonEncode({'challenge': 'a' * 64}), 200);
      }
      if (r.url.path.endsWith('/authorize')) {
        current = false;
        return http.Response(
            jsonEncode({'scope': 'screen-frames', 'ticket': 'a' * 43}), 200);
      }
      if (r.url.path.endsWith('/stop')) {
        revoked = r.headers['Authorization'] == 'Bearer ${'a' * 43}';
        return http.Response('', 200);
      }
      throw StateError('unexpected request');
    });
    await expectLater(
        ScreenShare.start(Board(),
            client: client,
            isCurrent: () => current,
            usbSession: 'AABBCCDDEEFF:1'),
        throwsStateError);
    expect(nativeCalls, 0);
    expect(revoked, isTrue);
  });
  test(
      'USB session reaches native consent and native refusal revokes the grant',
      () async {
    final calls = <MethodCall>[];
    var revoked = false;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(ScreenShare.channel, (call) async {
      calls.add(call);
      throw PlatformException(code: 'usb_detached');
    });
    addTearDown(() => TestDefaultBinaryMessengerBinding
        .instance.defaultBinaryMessenger
        .setMockMethodCallHandler(ScreenShare.channel, null));
    final client = MockClient((r) async {
      if (r.url.path.endsWith('/challenge')) {
        return http.Response(jsonEncode({'challenge': 'a' * 64}), 200);
      }
      if (r.url.path.endsWith('/authorize')) {
        return http.Response(
            jsonEncode({'scope': 'screen-frames', 'ticket': 'a' * 43}), 200);
      }
      revoked = true;
      return http.Response('', 200);
    });
    await expectLater(
        ScreenShare.start(Board(),
            client: client,
            isCurrent: () => true,
            usbSession: 'AABBCCDDEEFF:1'),
        throwsA(isA<PlatformException>()));
    expect(calls.single.arguments['usbSession'], 'AABBCCDDEEFF:1');
    expect(revoked, isTrue);
  });
}
