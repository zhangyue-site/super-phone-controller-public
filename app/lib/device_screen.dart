import 'usb_launch.dart';
import 'app_release.dart';
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';

import 'ble_ota_service.dart';
import 'firmware_screen.dart';
import 'theme.dart';
import 'widgets.dart';

/// 屏幕 1：扫描并选择要刷的板子。
///
/// 设计取舍：不显示"连接中"这种阻塞态——BLE 扫描本身是流式的，用户要的是
/// 立刻看到板子出现。所以扫描一进来就启动，列表随发现增长。
class DeviceScreen extends StatefulWidget {
  const DeviceScreen({super.key});

  @override
  State<DeviceScreen> createState() => _DeviceScreenState();
}

class _DeviceScreenState extends State<DeviceScreen> {
  final _svc = BleOtaService();
  StreamSubscription? _scanSub;
  final Map<String, ScanResult> _found = {};
  bool _scanning = false;
  String? _error;
  Timer? _autoStop;
  StreamSubscription? _adapterSub;
  bool _opening = false;
  bool _bluetoothOn = false;
  UsbAttachment? _usb;
  final _usbGate = UsbAutoShareGate();
  int _usbRevision = 0;

  Future<void> _acceptUsb(dynamic value) async {
    if (!mounted) return;
    _usbRevision++;
    final previous = _usb?.session;
    try {
      final next = value == null ? null : UsbAttachment.parse(value as Map);
      setState(() => _usb = next);
      if (_opening && next != null && next.session != previous && !_svc.busy) {
        Navigator.of(context).popUntil((route) => route.isFirst);
      }
      await _tryUsbOpen();
    } catch (e) {
      if (mounted) {
        setState(() {
          _usb = null;
          _error = 'USB识别：$e';
        });
      }
    }
  }

  Future<void> _readUsb() async {
    final revision = _usbRevision;
    try {
      final value = await UsbLaunch.snapshot();
      if (!mounted || revision != _usbRevision) return;
      final previous = _usb?.session;
      setState(() => _usb = value);
      if (previous != _usb?.session || !_opening) await _tryUsbOpen();
    } catch (e) {
      if (mounted && revision == _usbRevision) {
        setState(() {
          _usb = null;
          _error = 'USB识别：$e';
        });
      }
    }
  }

  Future<void> _tryUsbOpen() async {
    final usb = _usb;
    if (!_usbGate.claim(usb, bluetoothOn: _bluetoothOn, opening: _opening)) {
      return;
    }
    await _openDevice(BluetoothDevice.fromId(usb!.remoteId!), usb: usb);
  }

  @override
  void initState() {
    super.initState();
    UsbLaunch.channel.setMethodCallHandler((call) async {
      if (call.method == 'changed') await _acceptUsb(call.arguments);
    });
    _readUsb();
    _adapterSub = FlutterBluePlus.adapterState.listen((state) {
      if (!mounted || state == BluetoothAdapterState.unknown) {
        return;
      }
      _bluetoothOn = state == BluetoothAdapterState.on;
      if (_bluetoothOn) {
        _startScan();
        _tryUsbOpen();
      } else {
        _stopScan();
        setState(() => _error = '请打开手机蓝牙，开启后会自动寻找控制板');
      }
    }, onError: (Object error) {
      if (mounted) setState(() => _error = '无法使用蓝牙，请检查权限或换用支持蓝牙的手机');
    });
  }

  Future<void> _checkBluetooth() async {
    try {
      if (!await FlutterBluePlus.isSupported) {
        if (mounted) setState(() => _error = '这台设备不支持蓝牙');
        return;
      }
      final state = await FlutterBluePlus.adapterState
          .where((s) => s != BluetoothAdapterState.unknown)
          .first
          .timeout(const Duration(seconds: 5));
      if (!mounted) return;
      if (state != BluetoothAdapterState.on) {
        setState(() => _error = '请在系统设置中开启蓝牙');
        return;
      }
      await _startScan();
    } catch (_) {
      if (mounted) setState(() => _error = '暂时无法使用蓝牙，请检查权限后重试');
    }
  }

  Future<void> _startScan() async {
    if (_scanning || _opening || !mounted) return;
    setState(() {
      _scanning = true;
      _error = null;
      _found.clear();
    });
    await _scanSub?.cancel();
    _scanSub = _svc.scanResults.listen((results) {
      if (!mounted || _opening) return;
      setState(() {
        for (final r in results) {
          _found[r.device.remoteId.str] = r;
        }
      });
    }, onError: (Object e) {
      if (mounted) {
        setState(() {
          _scanning = false;
          _error = '扫描失败，请检查蓝牙权限后重试';
        });
      }
    });
    try {
      await _svc.startScan();
      if (!mounted || _opening) {
        await _svc.stopScan();
        return;
      }
      _autoStop?.cancel();
      _autoStop = Timer(const Duration(seconds: 12), _stopScan);
    } catch (_) {
      if (mounted) {
        setState(() {
          _scanning = false;
          _error = '扫描失败，请检查蓝牙权限后重试';
        });
      }
    }
  }

  Future<void> _stopScan() async {
    _autoStop?.cancel();
    try {
      await _svc.stopScan();
    } catch (_) {}
    if (!mounted) return;
    setState(() => _scanning = false);
  }

  @override
  void dispose() {
    UsbLaunch.channel.setMethodCallHandler(null);
    _autoStop?.cancel();
    _scanSub?.cancel();
    _adapterSub?.cancel();
    _svc.stopScan();
    _svc.disconnect();
    super.dispose();
  }

  List<ScanResult> get _sorted {
    final list = _found.values.toList()
      ..sort((a, b) => b.rssi.compareTo(a.rssi));
    return list;
  }

  Future<void> _open(ScanResult r) => _openDevice(r.device, usb: _usb);

  Future<void> _openDevice(BluetoothDevice device, {UsbAttachment? usb}) async {
    if (_opening) return;
    _opening = true;
    if (usb != null) _usbGate.consume(usb);
    await _stopScan();
    if (!mounted) return;
    await Navigator.of(context).push(MaterialPageRoute(
      builder: (_) => FirmwareScreen(
        service: _svc,
        device: device,
        usbAttachment: usb,
        isUsbCurrent: () => mounted && _usb?.session == usb?.session,
      ),
    ));
    // 从推送页返回后重新扫，避免板子重启后列表是旧的。
    await _svc.disconnect();
    _opening = false;
    if (mounted) {
      _checkBluetooth();
      _tryUsbOpen();
    }
  }

  @override
  Widget build(BuildContext context) {
    final devices = _sorted;
    return Scaffold(
      appBar: AppBar(
        title: const Text('控制板升级'),
        actions: [
          IconButton(
              tooltip: 'App 版本与更新',
              onPressed: () => AppRelease.show(context),
              icon: const Icon(Icons.info_outline)),
          IconButton(
            tooltip: '重新扫描',
            onPressed: _scanning ? null : _checkBluetooth,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: Column(
        children: [
          if (_usb != null)
            Padding(
              padding: const EdgeInsets.all(12),
              child: Column(children: [
                Text(_usb!.isBound
                    ? '已识别USB控制板，正在连接已配对的板子。共享画面将上传云端，需系统授权。'
                    : '首次连接：请选择当前插入的控制板。只需配对一次，以后插入会自动请求共享整个屏幕。'),
                if (_usb!.isBound && !_opening)
                  TextButton(
                      onPressed: () async {
                        try {
                          await UsbLaunch.channel.invokeMethod<void>(
                              'forget', {'session': _usb!.session});
                          await _readUsb();
                        } catch (e) {
                          if (mounted) setState(() => _error = '重新配对：$e');
                        }
                      },
                      child: const Text('重新选择配对板')),
              ]),
            ),
          _ScanBar(
              scanning: _scanning,
              count: devices.length,
              onToggle: () {
                _scanning ? _stopScan() : _checkBluetooth();
              }),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
              child: InfoBanner(
                icon: Icons.bluetooth_disabled,
                color: AppTheme.danger,
                text: _error!,
              ),
            ),
          Expanded(
            child: devices.isEmpty
                ? _EmptyState(scanning: _scanning, onRetry: _checkBluetooth)
                : ListView.separated(
                    padding: const EdgeInsets.all(16),
                    itemCount: devices.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 10),
                    itemBuilder: (_, i) => _DeviceCard(
                        result: devices[i], onTap: () => _open(devices[i])),
                  ),
          ),
        ],
      ),
    );
  }
}

class _ScanBar extends StatelessWidget {
  final bool scanning;
  final int count;
  final VoidCallback onToggle;

  const _ScanBar({
    required this.scanning,
    required this.count,
    required this.onToggle,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 12),
      child: Row(
        children: [
          if (scanning) const PulsingDot() else const SizedBox(width: 10),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              scanning ? '正在扫描附近设备…' : '扫描已停止 · 发现 $count 个',
              style: TextStyle(
                color: scanning ? AppTheme.accent : AppTheme.textDim,
                fontSize: 14,
              ),
            ),
          ),
          TextButton(
            onPressed: onToggle,
            child: Text(scanning ? '停止' : '扫描',
                style: const TextStyle(color: AppTheme.accent)),
          ),
        ],
      ),
    );
  }
}

class _DeviceCard extends StatelessWidget {
  final ScanResult result;
  final VoidCallback onTap;

  const _DeviceCard({required this.result, required this.onTap});

  /// 广播名形如 PhoneCtl-2026.10.21-ci7，把版本拆出来单独渲染更易读。
  (String, String) _splitName(String name) {
    final i = name.indexOf('-');
    if (i <= 0 || i == name.length - 1) return (name, '');
    return (name.substring(0, i), name.substring(i + 1));
  }

  @override
  Widget build(BuildContext context) {
    final rawName = result.advertisementData.advName.isNotEmpty
        ? result.advertisementData.advName
        : (result.device.platformName.isNotEmpty
            ? result.device.platformName
            : '未命名设备');
    final (title, version) = _splitName(rawName);
    final rssi = result.rssi;
    final (label, color) = rssi > -60
        ? ('强', AppTheme.accent)
        : rssi > -75
            ? ('中', AppTheme.warn)
            : ('弱', AppTheme.textDim);

    return Material(
      color: AppTheme.surface,
      borderRadius: BorderRadius.circular(14),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(14),
        child: Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: AppTheme.border),
          ),
          child: Row(
            children: [
              Container(
                width: 44,
                height: 44,
                decoration: BoxDecoration(
                  color: AppTheme.surfaceHi,
                  borderRadius: BorderRadius.circular(11),
                ),
                child:
                    const Icon(Icons.memory, color: AppTheme.accent, size: 22),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                            color: AppTheme.text,
                            fontSize: 16,
                            fontWeight: FontWeight.w600)),
                    if (version.isNotEmpty) ...[
                      const SizedBox(height: 3),
                      Text(version,
                          style: AppTheme.mono
                              .copyWith(color: AppTheme.textDim, fontSize: 12)),
                    ],
                  ],
                ),
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text('$rssi dBm',
                      style:
                          AppTheme.mono.copyWith(color: color, fontSize: 12)),
                  const SizedBox(height: 3),
                  Text(label, style: TextStyle(color: color, fontSize: 11)),
                ],
              ),
              const SizedBox(width: 6),
              const Icon(Icons.chevron_right,
                  color: AppTheme.textDim, size: 20),
            ],
          ),
        ),
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  final bool scanning;

  final VoidCallback onRetry;
  const _EmptyState({required this.scanning, required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: SingleChildScrollView(
          child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(scanning ? Icons.search : Icons.bluetooth_searching,
                size: 56, color: AppTheme.textDim.withValues(alpha: 0.5)),
            const SizedBox(height: 20),
            Text(
              scanning ? '正在寻找板子…' : '还没发现设备',
              style: const TextStyle(
                  color: AppTheme.text,
                  fontSize: 17,
                  fontWeight: FontWeight.w500),
            ),
            const SizedBox(height: 12),
            if (!scanning)
              TextButton.icon(
                  onPressed: onRetry,
                  icon: const Icon(Icons.refresh),
                  label: const Text('重新寻找控制板')),
            const Text(
              '确认板子已上电，广播名以 PhoneCtl- 开头。\n如果刚刷完固件，等它重启完成再扫。',
              textAlign: TextAlign.center,
              style:
                  TextStyle(color: AppTheme.textDim, fontSize: 13, height: 1.6),
            ),
          ],
        ),
      )),
    );
  }
}
