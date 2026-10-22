import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:pcflash/screen_task_status.dart';

void main() {
  String envelope(Map<String, dynamic> task) =>
      jsonEncode({'capture': '画面传输：已上传', 'task': jsonEncode(task)});
  final valid = <String, dynamic>{
    'state': 'running',
    'reply': '正在寻找',
    'frame': 7,
    'skills': [
      {'group': '微信', 'name': '找联系人'}
    ],
    'pointerReady': false,
    'barrier': 'b7'
  };
  test('upload success does not imply task completion or HID readiness', () {
    final status = ScreenTaskStatus.parse(envelope(valid));
    expect(status.capture, contains('已上传'));
    expect(status.taskLabel, '任务执行中');
    expect(status.pointerReady, isFalse);
    expect(status.skills, ['微信 · 找联系人']);
  });
  test('empty task is unknown, not successful', () {
    final status =
        ScreenTaskStatus.parse(jsonEncode({'capture': '共享中', 'task': ''}));
    expect(status.taskLabel, '等待任务状态');
    expect(status.skills, isEmpty);
  });
  test('reject malformed protocol fields and skill entries', () {
    for (final changed in [
      {'pointerReady': 'true'},
      {'barrier': 2},
      {
        'skills': [
          {'group': '微信'}
        ]
      }
    ]) {
      expect(() => ScreenTaskStatus.parse(envelope({...valid, ...changed})),
          throwsFormatException);
    }
  });
  test('terminal failure remains failure even when frames upload', () {
    final status =
        ScreenTaskStatus.parse(envelope({...valid, 'state': 'failed'}));
    expect(status.taskLabel, '任务失败');
  });
  test('actual server states have distinct localized task labels', () {
    const labels = {
      'thinking': '正在理解任务',
      'running': '任务执行中',
      'verifying': '正在核验结果',
      'speaking': '正在播报结果',
      'done': '任务已完成',
      'error': '任务失败',
      'waiting': '等待控制板或新画面',
      'idle': '等待语音任务',
      'stopped': '任务已停止',
    };
    for (final entry in labels.entries) {
      final status =
          ScreenTaskStatus.parse(envelope({...valid, 'state': entry.key}));
      expect(status.taskLabel, entry.value, reason: entry.key);
      expect(status.capture, contains('已上传'));
      expect(status.pointerReady, isFalse);
    }
  });
}
