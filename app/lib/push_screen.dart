import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';

import 'ble_ota_service.dart';
import 'theme.dart';
import 'widgets.dart';

/// 屏幕 3：推送进度。
///
/// 用户在这种等待场景下最关心两件事：还剩多久、卡在哪。所以进度环 + 步骤
/// 清单是主体，日志折叠在下面给需要排查的人。
class PushScreen extends StatefulWidget {
  final BleOtaService service;
  final BluetoothDevice device;
  final Uint8List bytes;
  final FirmwareInfo info;
  final int chunkSize;

  const PushScreen({
    super.key,
    required this.service,
    required this.device,
    required this.bytes,
    required this.info,
    required this.chunkSize,
  });

  @override
  State<PushScreen> createState() => _PushScreenState();
}

class _PushScreenState extends State<PushScreen> {
  final _logs = <String>[];
  StreamSubscription? _sub;

  int _percent = 0;
  int _sent = 0;
  int _step = 0;
  bool _done = false;
  bool _success = false;
  bool _showLogs = false;
  String? _failMsg;

  /// 估算剩余时间：记录开始时间和已发字节，用整体平均速率，避免抖动。
  final _startedAt = DateTime.now();
  int _lastSentAt = 0;
  Duration _lastSentAtWall = Duration.zero;

  static const _steps = ['连接设备', '协商 MTU', '传输固件', '校验 sha256', '等待重启确认'];

  @override
  void initState() {
    super.initState();
    _addLog('开始推送 ${widget.info.name}（${widget.info.sizeText}）');
    _addLog('每帧正文 ${widget.chunkSize} 字节');
    _run();
  }

  void _addLog(String s) {
    final t = DateTime.now();
    final stamp =
        '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}:${t.second.toString().padLeft(2, '0')}';
    if (!mounted) return;
    setState(() => _logs.add('$stamp  $s'));
  }

  Future<void> _run() async {
    setState(() {
      _step = 0;
      _percent = 0;
    });

    // 前两步在进入本页前已经完成（连接 + MTU），直接标记完成。
    await Future.delayed(const Duration(milliseconds: 250));
    if (!mounted) return;
    setState(() => _step = 2);
    _addLog('连接就绪，开始传输');

    _sub = widget.service
        .push(widget.bytes, chunkSize: widget.chunkSize)
        .listen((p) {
      if (!mounted) return;
      setState(() {
        if (p.total > 0) {
          _percent = p.percent;
          _sent = p.sent;
        }
        if (p.step == '校验 sha256') _step = 3;
        if (p.step == '等待重启确认') _step = 4;
        if (p.log != null) _logs.add(p.log!);
        if (p.done) {
          _done = true;
          _success = p.success;
          if (p.success) {
            _percent = 100;
            _step = 5;
          } else {
            _failMsg = p.log;
          }
        }
      });
      if (p.sent > _lastSentAt) {
        _lastSentAt = p.sent;
        _lastSentAtWall = DateTime.now().difference(_startedAt);
      }
    }, onError: (e) {
      if (!mounted) return;
      setState(() {
        _done = true;
        _success = false;
        _failMsg = '$e';
      });
    });
  }

  /// 剩余时间：用最近一次进度更新算平均速率。
  String? get _eta {
    if (_done || _sent == 0 || _lastSentAtWall.inMilliseconds == 0) return null;
    final perMs = _lastSentAt / _lastSentAtWall.inMilliseconds;
    final remainMs = (_info.size - _sent) / perMs;
    if (remainMs <= 0 || remainMs.isInfinite) return null;
    final s = (remainMs / 1000).round();
    if (s < 60) return '剩余约 $s 秒';
    final m = s ~/ 60;
    return '剩余约 $m 分 ${s % 60} 秒';
  }

  FirmwareInfo get _info => widget.info;

  @override
  void dispose() {
    if (!_done) widget.service.cancelPush();
    _sub?.cancel();
    super.dispose();
  }

  Future<void> _confirmCancel() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTheme.surface,
        title: const Text('中断推送？'),
        content: const Text('停止发送并断开连接。若板子已经完成校验并切换启动槽，中断无法撤销更新。'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('继续推送')),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('中断', style: TextStyle(color: AppTheme.danger)),
          ),
        ],
      ),
    );
    if (ok == true && mounted) {
      await widget.service.cancelPush();
      await _sub?.cancel();
      if (mounted) Navigator.of(context).pop();
    }
  }

  @override
  Widget build(BuildContext context) {
    final pct = _percent / 100.0;
    final color = _done
        ? (_success ? AppTheme.accent : AppTheme.danger)
        : AppTheme.accent;

    return PopScope(
      canPop: _done,
      onPopInvokedWithResult: (didPop, result) {
        if (!didPop) _confirmCancel();
      },
      child: Scaffold(
        appBar: AppBar(
          automaticallyImplyLeading: false,
          title: Text(_done ? (_success ? '升级完成' : '更新未完成') : '第 3 步：传输固件'),
          actions: [
            if (!_done)
              TextButton(
                onPressed: _confirmCancel,
                child:
                    const Text('中断', style: TextStyle(color: AppTheme.textDim)),
              ),
          ],
        ),
        body: ListView(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
          children: [
            const SizedBox(height: 12),
            Center(
              child: RingProgress(
                value: pct,
                center: _done && _success ? '✓' : '${(_percent).round()}%',
                subtitle: _done ? null : '${_fmt(_sent)} / ${_fmt(_info.size)}',
                color: color,
              ),
            ),
            if (!_done && _eta != null) ...[
              const SizedBox(height: 14),
              Center(
                child: Text(_eta!,
                    style:
                        const TextStyle(color: AppTheme.textDim, fontSize: 13)),
              ),
            ],
            if (_done && _failMsg != null) ...[
              const SizedBox(height: 18),
              InfoBanner(
                  icon: Icons.error_outline,
                  color: AppTheme.danger,
                  text: _failMsg!),
            ],
            if (_done && _success) ...[
              const SizedBox(height: 18),
              const InfoBanner(
                icon: Icons.check_circle_outline,
                color: AppTheme.accent,
                text: '已重新连接同一控制板，确认新版本启动且自检通过。',
              ),
            ],
            const SizedBox(height: 26),
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: AppTheme.surface,
                borderRadius: BorderRadius.circular(14),
                border: Border.all(color: AppTheme.border),
              ),
              child: StepList(steps: [
                for (var i = 0; i < _steps.length; i++)
                  (
                    _steps[i],
                    _done && !_success && i == _step
                        ? 1
                        : (i < _step ? 2 : (i == _step ? 1 : 0))
                  )
              ]),
            ),
            const SizedBox(height: 14),
            TextButton.icon(
              onPressed: () => setState(() => _showLogs = !_showLogs),
              icon: Icon(_showLogs ? Icons.expand_less : Icons.expand_more,
                  size: 18, color: AppTheme.textDim),
              label: Text('日志（${_logs.length}）',
                  style:
                      const TextStyle(color: AppTheme.textDim, fontSize: 13)),
            ),
            if (_showLogs)
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: const Color(0xFF0A0D11),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: AppTheme.border),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (final l in _logs)
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: 2),
                        child: Text(l,
                            style: AppTheme.mono.copyWith(
                                color: AppTheme.textDim,
                                fontSize: 11,
                                height: 1.5)),
                      ),
                  ],
                ),
              ),
          ],
        ),
        bottomNavigationBar: _done
            ? SafeArea(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
                  child: FilledButton(
                    onPressed: () {
                      Navigator.of(context).popUntil((r) => r.isFirst);
                    },
                    child: Text(_success ? '完成' : '返回'),
                  ),
                ),
              )
            : null,
      ),
    );
  }

  String _fmt(int b) {
    if (b >= 1048576) return '${(b / 1048576).toStringAsFixed(2)} MB';
    if (b >= 1024) return '${(b / 1024).toStringAsFixed(0)} KB';
    return '$b B';
  }
}
