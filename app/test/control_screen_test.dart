import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:pcflash/control_client.dart';
import 'package:pcflash/control_screen.dart';
import 'control_client_test.dart' show FakeBoard;

http.Response reply(String body, int status) => http.Response(body, status,
    headers: {'content-type': 'application/json; charset=utf-8'});

void main() {
  testWidgets(
      'preview never confirms automatically; STOP wins over late confirm',
      (tester) async {
    final operations = <String>[];
    final confirm = Completer<http.Response>();
    final client = ControlClient(client: MockClient((request) async {
      final body = jsonDecode(request.body) as Map;
      if (request.url.path.endsWith('/challenge')) {
        return reply(jsonEncode({'challenge': 'a' * 64}), 200);
      }
      if (request.url.path.endsWith('/authorize')) {
        return reply(
            jsonEncode({
              'ticket': 't' * 43,
              'scope': 'phone-commands',
              'expiresIn': 300
            }),
            200);
      }
      final op = body['operation'] as String;
      operations.add(op);
      if (op == 'confirm') return confirm.future;
      return reply(
          jsonEncode({
            'task_id': 'c' * 32,
            'state': op == 'stop' ? 'stopped' : 'pending',
            'reply': op == 'stop' ? '本次手机操作已停止' : '计划：从桌面搜索联系人',
            'terminal': op == 'stop'
          }),
          200);
    }));
    await tester.pumpWidget(
        MaterialApp(home: ControlScreen(service: FakeBoard(), client: client)));
    await tester.enterText(find.byType(TextField), '打开微信找到张三');
    await tester.tap(find.text('生成计划'));
    await tester.pumpAndSettle();
    expect(operations, ['prepare']);
    tester.testTextInput.hide();
    await tester.pump();
    await tester.scrollUntilVisible(find.text('确认执行'), 160,
        scrollable: find.byType(Scrollable).first);
    expect(find.text('确认执行'), findsOneWidget);
    await tester.ensureVisible(find.text('确认执行'));
    await tester.tap(find.text('确认执行'));
    await tester.pump();
    await tester.tap(find.text('停止手机操作'));
    await tester.pumpAndSettle();
    expect(operations, ['prepare', 'confirm', 'stop']);
    expect(find.text('已停止'), findsOneWidget);
    confirm.complete(
        reply(jsonEncode({'state': 'queued', 'reply': '晚到的确认'}), 200));
    await tester.pumpAndSettle();
    expect(find.text('晚到的确认'), findsNothing);
    expect(find.text('已停止'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });
}
