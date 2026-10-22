import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
// ignore: depend_on_referenced_packages
import 'package:flutter_blue_plus_platform_interface/flutter_blue_plus_platform_interface.dart';
import 'package:pcflash/main.dart';
import 'package:pcflash/usb_launch.dart';
import 'widget_test.dart' show BluetoothOffPlatform;

void main() {
  for (final fail in [false, true]) {
    testWidgets('late startup snapshot ($fail) cannot replace newer USB attach',
        (tester) async {
      FlutterBluePlusPlatform.instance = BluetoothOffPlatform();
      final initial = Completer<Map<String, dynamic>>();
      final messenger =
          TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
      messenger.setMockMethodCallHandler(
          UsbLaunch.channel, (call) => initial.future);
      addTearDown(
          () => messenger.setMockMethodCallHandler(UsbLaunch.channel, null));
      await tester.pumpWidget(const PcFlashApp());
      await tester.pump();
      const codec = StandardMethodCodec();
      // ignore: deprecated_member_use
      await messenger.handlePlatformMessage(
          UsbLaunch.channel.name,
          codec.encodeMethodCall(const MethodCall('changed', {
            'serial': 'AABBCCDDEEFF',
            'session': 'AABBCCDDEEFF:2',
            'remoteId': 'AA:BB:CC:DD:EE:01',
            'deviceId': 'epaper-01',
          })),
          (_) {});
      await tester.pumpAndSettle();
      expect(find.textContaining('已识别USB控制板'), findsOneWidget);
      if (fail) {
        initial.completeError(PlatformException(code: 'stale'));
      } else {
        initial
            .complete({'serial': 'AABBCCDDEEFF', 'session': 'AABBCCDDEEFF:1'});
      }
      await tester.pumpAndSettle();
      expect(find.textContaining('已识别USB控制板'), findsOneWidget);
      expect(find.textContaining('首次连接：'), findsNothing);
      expect(find.text('请打开手机蓝牙，开启后会自动寻找控制板'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      await tester.pump();
    });
  }
}
