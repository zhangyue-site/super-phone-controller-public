import 'dart:convert';

/// Remote task feedback is independent from successful screenshot transport.
class ScreenTaskStatus {
  final String capture;
  final String state;
  final String reply;
  final bool pointerReady;
  final List<String> skills;
  const ScreenTaskStatus(
      {required this.capture,
      this.state = '',
      this.reply = '',
      this.pointerReady = false,
      this.skills = const []});

  factory ScreenTaskStatus.parse(String value) {
    if (value.length > 20000) throw const FormatException('共享状态过大');
    final envelope = jsonDecode(value);
    if (envelope is! Map ||
        envelope['capture'] is! String ||
        envelope['task'] is! String) {
      throw const FormatException('共享状态无效');
    }
    final capture = envelope['capture'] as String;
    if (envelope['task'] == '') return ScreenTaskStatus(capture: capture);
    final task = jsonDecode(envelope['task'] as String);
    if (task is! Map ||
        task['state'] is! String ||
        task['reply'] is! String ||
        task['pointerReady'] is! bool ||
        task['skills'] is! List ||
        task['barrier'] is! String) {
      throw const FormatException('任务状态无效');
    }
    final skills = <String>[];
    for (final skill in task['skills'] as List) {
      if (skill is! Map ||
          skill['group'] is! String ||
          skill['name'] is! String) {
        throw const FormatException('技能状态无效');
      }
      skills.add('${skill['group']} · ${skill['name']}');
    }
    return ScreenTaskStatus(
        capture: capture,
        state: task['state'],
        reply: task['reply'],
        pointerReady: task['pointerReady'],
        skills: List.unmodifiable(skills));
  }

  String get taskLabel => switch (state) {
        'idle' => '等待语音任务',
        'thinking' => '正在理解任务',
        'running' => '任务执行中',
        'verifying' => '正在核验结果',
        'speaking' => '正在播报结果',
        'waiting' => '等待控制板或新画面',
        'done' ||
        'succeeded' ||
        'success' ||
        'verified' ||
        'completed' =>
          '任务已完成',
        'error' || 'failed' => '任务失败',
        'cancelled' => '任务已取消',
        'stopped' => '任务已停止',
        '' => '等待任务状态',
        _ => '任务：$state',
      };
}
