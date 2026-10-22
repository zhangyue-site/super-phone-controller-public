import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
// ignore: depend_on_referenced_packages
import 'package:flutter_blue_plus_platform_interface/flutter_blue_plus_platform_interface.dart';
import 'package:pcflash/main.dart';

final class BluetoothOffPlatform extends FlutterBluePlusPlatform {
  @override
  Future<BmBluetoothAdapterState> getAdapterState(
          BmBluetoothAdapterStateRequest request) async =>
      BmBluetoothAdapterState(adapterState: BmAdapterStateEnum.off);
}

void main() {
  testWidgets('Bluetooth off shows actionable recovery without scanning',
      (tester) async {
    tester.view.physicalSize = const Size(320, 568);
    tester.view.devicePixelRatio = 1;
    tester.platformDispatcher.textScaleFactorTestValue = 1.6;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    FlutterBluePlusPlatform.instance = BluetoothOffPlatform();
    await tester.pumpWidget(const PcFlashApp());
    await tester.pumpAndSettle();
    expect(find.text('控制板升级'), findsOneWidget);
    expect(find.text('请打开手机蓝牙，开启后会自动寻找控制板'), findsOneWidget);
    expect(find.text('重新寻找控制板'), findsOneWidget);
    expect(find.text('正在寻找板子…'), findsNothing);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
    await tester.pump();
  });
}
