import 'dart:async';
import 'package:flutter/material.dart';
import 'ble_ota_service.dart';
import 'control_client.dart';
import 'screen_share.dart';

class ControlScreen extends StatefulWidget {
  final BleOtaService service;
  final ControlClient? client;
  const ControlScreen({super.key, required this.service, this.client});
  @override
  State<ControlScreen> createState() => _ControlScreenState();
}

class _ControlScreenState extends State<ControlScreen> {
  late final ControlClient _client;
  final _text = TextEditingController();
  Map<String, dynamic> _task = {};
  String? _error;
  bool _busy = false, _polling = false, _stopping = false;
  Timer? _timer;
  int _generation = 0;
  @override
  void initState() {
    super.initState();
    _client = widget.client ?? ControlClient();
    _timer = Timer.periodic(const Duration(seconds: 2), (_) => _poll());
  }

  Future<void> _poll() async {
    if (_polling ||
        _busy ||
        _stopping ||
        !_client.authorized ||
        _task['task_id'] == null ||
        _task['terminal'] == true) {
      return;
    }
    _polling = true;
    final generation = _generation;
    try {
      final result =
          await _client.command('status', taskId: _task['task_id'] as String);
      if (mounted && generation == _generation) {
        setState(() {
          _task = result;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted && generation == _generation) setState(() => _error = '$e');
    } finally {
      _polling = false;
    }
  }

  Future<void> _run(String operation) async {
    if (_busy || _stopping) return;
    final generation = ++_generation;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      if (!_client.authorized) {
        if (operation != 'prepare') {
          throw const FormatException('授权失效，请重新生成计划后确认');
        }
        await _client.authorize(widget.service);
      }
      if (generation != _generation) return;
      final result = await _client.command(operation,
          text: operation == 'prepare' ? _text.text.trim() : null,
          taskId: operation == 'prepare' ? null : _task['task_id'] as String?);
      if (mounted && generation == _generation) {
        setState(() {
          _task = result;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted && generation == _generation) setState(() => _error = '$e');
    } finally {
      if (mounted && generation == _generation) setState(() => _busy = false);
    }
  }

  Future<void> _stop() async {
    if (_stopping) return;
    final generation = ++_generation;
    setState(() {
      _stopping = true;
      _busy = false;
      _error = null;
    });
    try {
      if (!_client.authorized) await _client.authorize(widget.service);
      final result = await _client.command('stop');
      if (mounted && generation == _generation) {
        setState(() {
          _task = result;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = '停止请求未确认：$e。请使用板子上的停止按钮。');
    } finally {
      if (mounted) setState(() => _stopping = false);
    }
  }

  Future<void> _share() async {
    final accepted = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
                title: const Text('共享整个屏幕'),
                content: const Text(
                    '画面将发给云端用于定位和核验。请在系统弹窗选择整个屏幕，保持手机解锁。可从系统通知停止共享。'),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(context, false),
                      child: const Text('取消')),
                  FilledButton(
                      onPressed: () => Navigator.pop(context, true),
                      child: const Text('继续系统确认'))
                ]));
    if (accepted != true || !mounted) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ScreenShare.start(widget.service);
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    _client.close();
    _text.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = _task['state'];
    final labels = {
      'pending': '等待你的确认',
      'queued': '已确认，等待控制板',
      'running': '控制板执行中',
      'done': _task['verified'] == true ? '结果已核验' : '执行结束，尚未核验',
      'error': '未完成',
      'stopped': '已停止',
      'expired': '已过期',
      'idle': '暂无任务',
      'replaced': '已替换',
      'saved': '已存为技能'
    };
    return Scaffold(
      appBar: AppBar(title: const Text('手机控制')),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        const Text('文字下发 · 确认后执行',
            style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
        const SizedBox(height: 8),
        const Text('当前支持打开微信找联系人，停留在搜索结果页，不发消息。需要整屏共享、手机解锁及板端 HID 许可。'),
        OutlinedButton.icon(
            onPressed: _busy || _stopping ? null : _share,
            icon: const Icon(Icons.screen_share),
            label: const Text('共享整屏给 AI')),
        const SizedBox(height: 16),
        TextField(
            controller: _text,
            maxLength: 120,
            minLines: 2,
            maxLines: 4,
            enabled: !_busy && !_stopping,
            decoration: const InputDecoration(
                labelText: '手机操作指令',
                hintText: '打开微信找到张三',
                border: OutlineInputBorder())),
        FilledButton(
            onPressed: _busy || _stopping ? null : () => _run('prepare'),
            child: Text(_busy ? '正在请求…' : '生成计划')),
        if (_error != null)
          Padding(
              padding: const EdgeInsets.symmetric(vertical: 12),
              child: Text(_error!,
                  style:
                      TextStyle(color: Theme.of(context).colorScheme.error))),
        if (_task.isNotEmpty)
          Card(
              child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Text(labels[state] ?? '任务状态',
                            style: const TextStyle(
                                fontWeight: FontWeight.bold, fontSize: 18)),
                        const SizedBox(height: 8),
                        Text(_task['reply'] as String? ?? ''),
                        if (state == 'pending')
                          FilledButton(
                              onPressed: _busy || _stopping
                                  ? null
                                  : () => _run('confirm'),
                              child: const Text('确认执行')),
                        if (state == 'done' && _task['verified'] == true)
                          OutlinedButton(
                              onPressed: _busy || _stopping
                                  ? null
                                  : () => _run('save'),
                              child: const Text('存为技能')),
                        TextButton(
                            onPressed: _busy || _stopping
                                ? null
                                : () => _run('status'),
                            child: const Text('刷新状态')),
                      ]))),
        const SizedBox(height: 12),
        const Text('App 只下发控制指令。切到微信后可回到这里查看结果；离开此页不会自动取消任务。停止也可在控制板上操作。'),
      ]),
      bottomNavigationBar: SafeArea(
          child: Padding(
              padding: const EdgeInsets.all(16),
              child: FilledButton.icon(
                  style: FilledButton.styleFrom(
                      backgroundColor: Theme.of(context).colorScheme.error),
                  onPressed: _stopping ? null : _stop,
                  icon: const Icon(Icons.stop_circle_outlined),
                  label: Text(_stopping ? '正在请求停止…' : '停止手机操作')))),
    );
  }
}
