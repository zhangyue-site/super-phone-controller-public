import 'usb_launch.dart';
import 'screen_task_status.dart';
import 'control_screen.dart';
import 'dart:async';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import 'app_ota_client.dart';
import 'screen_share.dart';

import 'ble_ota_service.dart';
import 'firmware_image.dart';
import 'push_screen.dart';
import 'theme.dart';
import 'widgets.dart';

/// 屏幕 2：选固件。
///
/// 核心考量：BLE 传 1.3MB 要一两分钟，推错板子/推错文件的代价很大。
/// 所以在"开始推送"之前，把版本、大小、sha256 和板子当前版本摆在一起对比。
class FirmwareScreen extends StatefulWidget {
  final BleOtaService service;
  final BluetoothDevice device;
  final UsbAttachment? usbAttachment;
  final bool Function()? isUsbCurrent;

  const FirmwareScreen({
    super.key,
    required this.service,
    required this.device,
    this.usbAttachment,
    this.isUsbCurrent,
  });

  @override
  State<FirmwareScreen> createState() => _FirmwareScreenState();
}

class _FirmwareScreenState extends State<FirmwareScreen> {
  static const otaBase = 'https://erweima.zhangyue.site/phone-controller';

  FirmwareInfo? _info;
  Uint8List? _bytes;
  int _chunkSize = 20;
  bool _busy = false;
  String? _error;
  String _deviceVersion = '';
  bool _connected = false;
  bool _autoShareAttempted = false;
  ScreenTaskStatus _screenStatus = const ScreenTaskStatus(capture: '未共享');
  Timer? _screenTimer;
  StreamSubscription? _connectionSub;

  @override
  void initState() {
    super.initState();
    _deviceVersion = ''; // Advertising names are not running-version evidence.
    _connectionSub = widget.device.connectionState.listen((state) {
      if (mounted && state != BluetoothConnectionState.connected) {
        setState(() {
          _connected = false;
          _deviceVersion = '';
        });
      }
    });
    _screenTimer = Timer.periodic(const Duration(seconds: 2), (_) async {
      try {
        final status = await ScreenShare.status();
        if (mounted) setState(() => _screenStatus = status);
      } catch (_) {
        if (mounted) {
          setState(() => _screenStatus =
              const ScreenTaskStatus(capture: '共享状态暂不可用，请稍后重试'));
        }
      }
    });
    _prepare();
  }

  Future<void> _prepare() async {
    setState(() {
      _busy = true;
      _error = null;
      _connected = false;
      _deviceVersion = '';
    });
    try {
      final chunk = await widget.service.connect(widget.device);
      if (!mounted) {
        await widget.service.disconnect();
        return;
      }
      final info = await widget.service.readInfo();
      if (!mounted) return;
      final usb = widget.usbAttachment;
      final usbCurrent = widget.isUsbCurrent?.call() == true;
      if (usb != null) {
        if (info == null || (!usbCurrent && !_autoShareAttempted)) {
          throw StateError('USB连接已改变或控制板不支持身份读取，请重新连接');
        }
        usb.validateBoard(widget.device.remoteId.str, info.device);
        if (usbCurrent && !usb.isBound) {
          await UsbLaunch.bind(usb, widget.device.remoteId.str, info.device);
        }
        if (!mounted) return;
      }
      setState(() {
        _deviceVersion = info?.version ?? _deviceVersion;
        _chunkSize = chunk;
        _connected = true;
        _busy = false;
      });
      if (usb != null && usbCurrent && !_autoShareAttempted) {
        _autoShareAttempted = true;
        await _shareScreen(automatic: true);
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = '连接失败：$e';
      });
    }
  }

  @override
  void dispose() {
    _screenTimer?.cancel();
    _connectionSub?.cancel();
    widget.service.disconnect();
    super.dispose();
  }

  Future<void> _shareScreen({bool automatic = false}) async {
    if (_busy || !_connected || !mounted) return;
    if (automatic && widget.isUsbCurrent?.call() != true) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      if (await ScreenShare.isActive()) return;
      if (!mounted) return;
      final accepted = automatic ||
          await showDialog<bool>(
                context: context,
                builder: (dialogContext) => AlertDialog(
                  title: const Text('共享屏幕给你的 AI'),
                  content: const Text(
                      '当前手机画面将传给云端 AI。操作由控制板 HID 完成，App 只提供画面。请选择共享整个屏幕，才能在桌面和微信之间导航。你可随时从系统投屏入口或通知停止；一次共享约 4 分钟。'),
                  actions: [
                    TextButton(
                        onPressed: () => Navigator.pop(dialogContext, false),
                        child: const Text('取消')),
                    FilledButton(
                        onPressed: () => Navigator.pop(dialogContext, true),
                        child: const Text('继续系统确认')),
                  ],
                ),
              ) ==
              true;
      if (!accepted || !mounted) return;
      await ScreenShare.start(
        widget.service,
        usbSession: widget.usbAttachment?.session,
        isCurrent: () =>
            mounted &&
            (widget.usbAttachment == null ||
                widget.isUsbCurrent?.call() == true),
      );
      if (mounted) {
        setState(
            () => _screenStatus = const ScreenTaskStatus(capture: '正在启动共享'));
      }
    } catch (e) {
      if (mounted) setState(() => _error = '屏幕共享：$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _pickLocal() async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final res =
          await FilePicker.pickFiles(type: FileType.any, withData: true);
      if (!mounted) return;
      final f = res?.files.single;
      if (f == null) {
        setState(() => _busy = false);
        return;
      }
      if (f.bytes == null) throw StateError('无法读取文件，请重新选择');
      await _loadBytes(f.bytes!, f.name);
    } catch (_) {
      if (mounted) {
        setState(() {
          _busy = false;
          _error = '无法读取固件，请重新选择 app.bin';
        });
      }
    }
  }

  Future<void> _fetchFromServer() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final board = await widget.service.readInfo();
      if (board == null) throw StateError('控制板需先更新一次基础固件以支持自动下载授权');
      final client = AppOtaClient(Uri.parse(otaBase));
      try {
        final result = await client.download(
            board.device, widget.service.signDownloadChallenge);
        final image = FirmwareImage.parse(result.bytes);
        if (image.version != result.version) {
          throw const FormatException('下载版本与固件不符');
        }
        await _loadBytes(result.bytes, 'app.bin');
      } finally {
        client.close();
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = '下载失败：$e';
      });
    }
  }

  Future<void> _loadBytes(Uint8List bytes, String name) async {
    if (!mounted) return;
    setState(() {
      _info = null;
      _bytes = null;
      _error = null;
    });
    late final FirmwareImage image;
    try {
      image = FirmwareImage.parse(bytes);
    } on FormatException catch (error) {
      setState(() {
        _busy = false;
        _error = error.message;
      });
      return;
    }

    setState(() {
      _bytes = bytes;
      _info = FirmwareInfo(
        name: name,
        size: bytes.length,
        sha256: image.sha,
        version: image.version,
      );
      _busy = false;
      _error = null;
    });
  }

  Future<void> _start() async {
    if (_bytes == null || _info == null || !_connected || _busy) return;
    await Navigator.of(context).push(MaterialPageRoute(
      builder: (_) => PushScreen(
        service: widget.service,
        device: widget.device,
        bytes: _bytes!,
        info: _info!,
        chunkSize: _chunkSize,
      ),
    ));
    // OTA may already have reconnected; always refresh the running version.
    if (!mounted) return;
    setState(() => _deviceVersion = '');
    if (!_connected) {
      await _prepare();
    } else {
      try {
        final board = await widget.service.readInfo();
        if (mounted && board != null) {
          setState(() => _deviceVersion = board.version);
        }
      } catch (_) {
        if (mounted) setState(() => _error = '请重新连接以核对升级后的版本');
      }
    }
  }

  bool get _sameVersion =>
      _info != null &&
      _deviceVersion.isNotEmpty &&
      _info!.version == _deviceVersion;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('控制板'),
        actions: [
          TextButton.icon(
              onPressed: _busy || !_connected
                  ? null
                  : () => Navigator.of(context).push(MaterialPageRoute(
                      builder: (_) => ControlScreen(service: widget.service))),
              icon: const Icon(Icons.phone_android),
              label: const Text('手机控制'))
        ],
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(22),
          child: Padding(
            padding: const EdgeInsets.only(left: 16, bottom: 10),
            child: Align(
              alignment: Alignment.centerLeft,
              child: Text(
                _deviceVersion.isEmpty
                    ? '目标设备 · 版本待核实'
                    : '目标设备 · 当前 $_deviceVersion',
                style: AppTheme.mono
                    .copyWith(color: AppTheme.textDim, fontSize: 12),
              ),
            ),
          ),
        ),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (widget.usbAttachment != null)
            const Padding(
              padding: EdgeInsets.only(bottom: 12),
              child: Text(
                  'USB控制板已识别。确认系统“共享整个屏幕”后，画面将上传云端AI。取消后可手动重新开启；拔出控制板会停止共享。HID许可仍按板端提示开启。'),
            ),
          if (_error != null) ...[
            InfoBanner(
                icon: Icons.error_outline,
                color: AppTheme.danger,
                text: _error!),
            const SizedBox(height: 16),
          ],
          if (!_connected && !_busy) ...[
            FilledButton.icon(
                onPressed: _prepare,
                icon: const Icon(Icons.bluetooth_connected),
                label: const Text('重新连接控制板')),
            const SizedBox(height: 16),
          ],
          Card(
              child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        const Text('AI 手机画面',
                            style: TextStyle(fontWeight: FontWeight.bold)),
                        Text(_screenStatus.capture),
                        Text(_screenStatus.taskLabel),
                        if (_screenStatus.reply.isNotEmpty)
                          Text(_screenStatus.reply),
                        if (_screenStatus.state.isNotEmpty &&
                            !_screenStatus.pointerReady)
                          const Text('等待控制板协议确认；开始操作前请在板端同意 HID 控制'),
                        for (final skill in _screenStatus.skills)
                          Text('技能：$skill'),
                        const Text(
                            '先共享整屏，语音发起任务；说“存为技能”固化为专项技能。回放从桌面开始，画面变化时再由 AI 定位。当前先支持微信，例如“打开微信找到张三”。旋转屏幕后请重新共享。'),
                        FilledButton.icon(
                            onPressed:
                                _busy || !_connected ? null : _shareScreen,
                            icon: const Icon(Icons.screen_share_outlined),
                            label: const Text('共享屏幕给 AI')),
                        TextButton(
                            onPressed: () async {
                              await ScreenShare.stop();
                              if (mounted) {
                                setState(() => _screenStatus =
                                    const ScreenTaskStatus(capture: '已停止共享'));
                              }
                            },
                            child: const Text('停止共享')),
                      ]))),
          const SizedBox(height: 12),
          const InfoBanner(
              icon: Icons.info_outline, text: '第 2 步：选择固件。传输时请保持手机靠近控制板，避免断电。'),
          const SizedBox(height: 16),
          _SourceCard(
            icon: Icons.cloud_download_outlined,
            title: '下载最新固件',
            subtitle: '通过已连接的控制板自动授权，无需选择文件',
            primary: true,
            onTap: _busy ? null : _fetchFromServer,
          ),
          const SizedBox(height: 10),
          _SourceCard(
            icon: Icons.folder_open_outlined,
            title: '选择本地固件（高级）',
            subtitle: '仅用于恢复，选择 app.bin 应用镜像',
            onTap: _busy ? null : _pickLocal,
          ),
          if (_busy) ...[
            const SizedBox(height: 20),
            const Center(
              child: SizedBox(
                width: 22,
                height: 22,
                child: CircularProgressIndicator(strokeWidth: 2.4),
              ),
            ),
          ],
          if (_info != null) ...[
            const SizedBox(height: 26),
            const Text('已选固件',
                style: TextStyle(
                    color: AppTheme.textDim,
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    letterSpacing: 0.6)),
            const SizedBox(height: 10),
            _FirmwareDetail(info: _info!),
            if (_sameVersion) ...[
              const SizedBox(height: 12),
              InfoBanner(
                icon: Icons.warning_amber_rounded,
                text: '版本和板子当前版本相同（${_info!.version}），'
                    '通常不需要推送。如果是要回刷同一版本，可以继续。',
              ),
            ],
          ],
        ],
      ),
      bottomNavigationBar: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
          child: FilledButton(
            onPressed: (_info != null && _connected && !_busy && _error == null)
                ? _start
                : null,
            child: Text(_busy
                ? '正在准备…'
                : !_connected
                    ? '请先连接控制板'
                    : _info == null
                        ? '先选择一个固件'
                        : '下一步：传输固件'),
          ),
        ),
      ),
    );
  }
}

class _SourceCard extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback? onTap;
  final bool primary;

  const _SourceCard({
    required this.icon,
    required this.title,
    required this.subtitle,
    this.onTap,
    this.primary = false,
  });

  @override
  Widget build(BuildContext context) {
    final accent = primary ? AppTheme.accent : AppTheme.text;
    return Material(
      color:
          primary ? AppTheme.accent.withValues(alpha: 0.07) : AppTheme.surface,
      borderRadius: BorderRadius.circular(14),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(14),
        child: Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(14),
            border: Border.all(
                color: primary
                    ? AppTheme.accent.withValues(alpha: 0.45)
                    : AppTheme.border),
          ),
          child: Row(
            children: [
              Icon(icon, color: accent, size: 22),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title,
                        style: TextStyle(
                            color: accent,
                            fontSize: 15,
                            fontWeight: FontWeight.w600)),
                    const SizedBox(height: 3),
                    Text(subtitle,
                        style: const TextStyle(
                            color: AppTheme.textDim, fontSize: 12)),
                  ],
                ),
              ),
              if (onTap != null)
                const Icon(Icons.chevron_right,
                    color: AppTheme.textDim, size: 20),
            ],
          ),
        ),
      ),
    );
  }
}

class _FirmwareDetail extends StatelessWidget {
  final FirmwareInfo info;

  const _FirmwareDetail({required this.info});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppTheme.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppTheme.border),
      ),
      child: Column(
        children: [
          _row('文件', info.name, mono: false),
          const SizedBox(height: 12),
          _row('版本', info.version, mono: true),
          const SizedBox(height: 12),
          _row('大小', info.sizeText, mono: true),
          const SizedBox(height: 12),
          _row('sha256', '${info.sha256.substring(0, 16)}…', mono: true),
        ],
      ),
    );
  }

  Widget _row(String k, String v, {required bool mono}) {
    return Row(
      children: [
        SizedBox(
          width: 62,
          child: Text(k,
              style: const TextStyle(color: AppTheme.textDim, fontSize: 13)),
        ),
        Expanded(
          child: Text(
            v,
            style: (mono ? AppTheme.mono : const TextStyle())
                .copyWith(color: AppTheme.text, fontSize: 13),
            overflow: TextOverflow.ellipsis,
          ),
        ),
      ],
    );
  }
}
