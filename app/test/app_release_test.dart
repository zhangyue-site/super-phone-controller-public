import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:pcflash/app_release.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('uses installed metadata and opens official update entry',
      (tester) async {
    final calls = <String>[];
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(AppRelease.channel, (call) async {
      calls.add(call.method);
      return call.method == 'info'
          ? {'versionName': '9.8.7', 'versionCode': 123}
          : null;
    });
    addTearDown(() => TestDefaultBinaryMessengerBinding
        .instance.defaultBinaryMessenger
        .setMockMethodCallHandler(AppRelease.channel, null));
    await tester.pumpWidget(MaterialApp(
        home: Builder(
            builder: (context) => TextButton(
                onPressed: () => AppRelease.show(context),
                child: const Text('版本')))));
    await tester.tap(find.text('版本'));
    await tester.pumpAndSettle();
    expect(find.textContaining('9.8.7（123）'), findsOneWidget);
    await tester.tap(find.text('官方下载与更新'));
    await tester.pump();
    expect(calls, ['info', 'openDownload']);
  });
  testWidgets('metadata failure does not claim release version is installed',
      (tester) async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(AppRelease.channel,
            (_) async => throw PlatformException(code: 'unavailable'));
    addTearDown(() => TestDefaultBinaryMessengerBinding
        .instance.defaultBinaryMessenger
        .setMockMethodCallHandler(AppRelease.channel, null));
    await tester.pumpWidget(MaterialApp(
        home: Builder(
            builder: (context) => TextButton(
                onPressed: () => AppRelease.show(context),
                child: const Text('版本')))));
    await tester.tap(find.text('版本'));
    await tester.pumpAndSettle();
    expect(find.textContaining('暂时无法读取'), findsOneWidget);
    expect(find.textContaining('1.0.7'), findsNothing);
  });
}
