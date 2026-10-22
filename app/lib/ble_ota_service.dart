import 'dart:async';
import 'dart:io';
import 'dart:typed_data';
import 'transfer_session.dart';
import 'firmware_image.dart';
import 'board_info.dart';

import 'package:crypto/crypto.dart';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';

/// 固件侧 ble_ota.h 里定义的状态码
class OtaState {
  static const idle = 0;
  static const receiving = 1;
  static const verifying = 2;
  static const ready = 3;
  static const error = 4;
}

class OtaError {
  static String text(int e) => switch (e) {
        1 => '状态不允许该操作',
        2 => '参数不合法',
        3 => '写 flash 失败',
        4 => '固件超过槽位大小',
        5 => 'sha256 校验不符，数据在传输中损坏',
        6 => '镜像头部不合法',
        _ => '未知错误 $e',
      };
}

/// 固件信息，来自扫描到的广播名或本地文件
class FirmwareInfo {
  final String name;
  final int size;
  final String sha256;
  final String version;

  const FirmwareInfo({
    required this.name,
    required this.size,
    required this.sha256,
    required this.version,
  });

  String get sizeText => size >= 1048576
      ? '${(size / 1048576).toStringAsFixed(2)} MB'
      : '${(size / 1024).toStringAsFixed(0)} KB';
}

class PushProgress {
  final int percent;
  final int sent;
  final int total;
  final String step;
  final String? log;
  final bool done;
  final bool success;

  const PushProgress({
    this.percent = 0,
    this.sent = 0,
    this.total = 0,
    this.step = '',
    this.log,
    this.done = false,
    this.success = false,
  });
}

/// BLE 固件推送服务。
///
/// 协议与固件 ble_ota.cpp 对应：BEGIN(1B 命令 + 4B 小端长度 + 32B sha256)
/// → 若干 DATA(1B 命令 + 正文) → END(1B 命令)。
///
/// 两个平台的差异都收敛到这里：
///  * Android 支持 MTU 协商，iOS 的 CoreBluetooth 固定不给谈；
///  * iOS 的分片上限由 maximumWriteValueLength 给出，通常 182 字节。
class BleOtaService {
  static const svcUuid = '6f6f7461-2d6f-7461-0000-000000000001';
  static const ctrlUuid = '6f6f7461-2d6f-7461-0000-000000000002';
  static const statUuid = '6f6f7461-2d6f-7461-0000-000000000003';

  /// 4MB 槽位的上限（固件 ota 分区 0x340000）
  static const maxImageSize = 0x340000;

  BluetoothDevice? _device;
  BluetoothCharacteristic? _ctrl;
  BluetoothCharacteristic? _stat;
  BluetoothCharacteristic? _info;
  BluetoothCharacteristic? _auth;
  bool _busy = false;
  TransferSession? _transfer;
  int _connectionEpoch = 0;

  bool get busy => _busy;
  BluetoothDevice? get device => _device;

  /// 扫描广播里带 OTA 服务的设备。
  Future<void> startScan() => FlutterBluePlus.startScan(
        withServices: [Guid(svcUuid)],
        timeout: const Duration(seconds: 12),
        androidUsesFineLocation: false,
      );
  Stream<List<ScanResult>> get scanResults => FlutterBluePlus.scanResults;

  Future<void> stopScan() => FlutterBluePlus.stopScan();

  /// 连接并发现服务，返回设备的 MTU 与每帧正文大小。
  Future<int> connect(BluetoothDevice device) async {
    final epoch = ++_connectionEpoch;
    _device = device;
    try {
      // 插件要求显式声明许可，否则拒绝连接——这是防止商业滥用的一道门。
      await device.connect(
        license: License.nonprofit,
        timeout: const Duration(seconds: 15),
        // Android 上会协商到 517；iOS 的 CoreBluetooth 忽略这个值，
        // 实际分片长度由 maximumWriteValueLength 决定，插件内部已处理。
        mtu: Platform.isAndroid ? 517 : null,
      );

      if (epoch != _connectionEpoch) throw StateError('连接已取消');
      final services = await device.discoverServices();
      if (epoch != _connectionEpoch) throw StateError('连接已取消');
      final svc = services.where((s) => s.uuid == Guid(svcUuid)).firstOrNull;
      if (svc == null) {
        await device.disconnect();
        throw Exception('设备上没有 OTA 服务，确认选的是 PhoneCtl 板子');
      }

      _ctrl = svc.characteristics
          .where((c) => c.uuid == Guid(ctrlUuid))
          .firstOrNull;
      _stat = svc.characteristics
          .where((c) => c.uuid == Guid(statUuid))
          .firstOrNull;
      if (_ctrl == null || _stat == null) {
        await device.disconnect();
        throw Exception('OTA 特征值缺失');
      }

      _device = device;
      _info = svc.characteristics
          .where((c) => c.uuid == Guid('6f6f7461-2d6f-7461-0000-000000000004'))
          .firstOrNull;
      _auth = svc.characteristics
          .where((c) => c.uuid == Guid('6f6f7461-2d6f-7461-0000-000000000005'))
          .firstOrNull;

      // 协商失败时 mtu 仍是 23，减去 3 字节 ATT 头和 1 字节命令码 = 19。
      final mtu = device.mtuNow;
      if (mtu < 40) {
        await device.disconnect();
        throw StateError('蓝牙连接的传输容量太小，请返回并重新连接控制板');
      }
      final chunk = otaChunkSize(mtu);

      // Enable status notifications before creating any transfer session.
      await _stat!.setNotifyValue(true);
      if (epoch != _connectionEpoch) throw StateError('连接已取消');
      return chunk;
    } catch (_) {
      try {
        await device.disconnect();
      } catch (_) {}
      if (epoch == _connectionEpoch) {
        _device = null;
        _ctrl = null;
        _stat = null;
      }
      rethrow;
    }
  }

  Future<BoardInfo?> readInfo() async {
    final info = _info;
    if (info == null) return null;
    return BoardInfo.parse(
        await info.read().timeout(const Duration(seconds: 5)));
  }

  Future<List<int>> signDownloadChallenge(List<int> nonce) async {
    final auth = _auth;
    if (auth == null || nonce.length != 32 || _busy) {
      throw StateError('控制板暂不支持下载授权或正在升级');
    }
    await auth
        .write(nonce, withoutResponse: false)
        .timeout(const Duration(seconds: 5));
    return auth.read().timeout(const Duration(seconds: 5));
  }

  Future<void> _confirmReboot(BluetoothDevice device, BoardInfo before,
      FirmwareImage target, TransferSession session) async {
    if (device.isConnected) {
      await device.connectionState
          .firstWhere((s) => s == BluetoothConnectionState.disconnected)
          .timeout(const Duration(seconds: 15));
    }
    final elapsed = Stopwatch()..start();
    while (elapsed.elapsed < const Duration(seconds: 75)) {
      if (session.cancelled) throw StateError('已停止等待启动确认');
      try {
        await connect(device);
        final current = await readInfo();
        if (session.cancelled) throw StateError('已停止等待启动确认');
        if (current != null &&
            current.confirms(before, target.version, target.elfSha256)) {
          return;
        }
        if (current != null && current.device != before.device) {
          throw StateError('重连设备身份不符');
        }
      } catch (_) {
        if (session.cancelled) rethrow;
      }
      try {
        await device.disconnect();
      } catch (_) {}
      await Future<void>.delayed(const Duration(seconds: 2));
    }
    throw StateError('未确认新版本启动，可能发生回滚或连接中断；请保持供电后重新检查版本');
  }

  /// 订阅状态通知，返回原始 4 字节状态流。
  Stream<List<int>> statusStream() =>
      _stat?.onValueReceived ?? const Stream.empty();

  /// 推送固件。[chunkSize] 由 connect 返回。
  Stream<PushProgress> push(Uint8List data, {required int chunkSize}) async* {
    if (_busy) {
      yield const PushProgress(done: true, success: false, log: '已有推送在进行');
      return;
    }
    late final FirmwareImage target;
    try {
      target = FirmwareImage.parse(data);
    } on FormatException catch (error) {
      yield PushProgress(done: true, success: false, log: error.message);
      return;
    }

    final ctrl = _ctrl, stat = _stat;
    if (ctrl == null || stat == null) {
      yield const PushProgress(done: true, success: false, log: '未连接');
      return;
    }

    if (chunkSize < 1 || chunkSize > 511) {
      yield const PushProgress(done: true, log: '传输分片大小无效');
      return;
    }
    _busy = true;
    final session = TransferSession();
    _transfer = session;
    final statusSub = stat.onValueReceived.listen(session.accept);
    void checkActive() {
      if (session.cancelled) throw StateError('已中断推送');
    }

    final total = data.length;
    var verified = false;
    final device = _device;

    try {
      final before = await readInfo();
      if (before == null || device == null) {
        throw StateError('请先更新控制板基础固件以支持重启确认');
      }
      checkActive();
      yield const PushProgress(step: '连接设备', log: '设备连接就绪');

      final digest = sha256.convert(data).bytes;
      final begin = Uint8List(1 + 4 + 32);
      begin[0] = 0x01;
      begin[1] = total & 0xFF;
      begin[2] = (total >> 8) & 0xFF;
      begin[3] = (total >> 16) & 0xFF;
      begin[4] = (total >> 24) & 0xFF;
      begin.setRange(5, 37, digest);
      await ctrl.write(begin, withoutResponse: false);

      // iOS 必须用 withResponse，否则 CoreBluetooth 会限流丢包。
      // Acknowledged writes provide backpressure on both platforms.
      const withoutResponse = false;
      final chunk = chunkSize;

      yield PushProgress(
        step: '传输固件',
        log: '每帧正文 $chunk 字节，共 ${(total / chunk).ceil()} 帧',
      );

      var sent = 0;
      var lastPct = -1;
      final frame = Uint8List(1 + chunk);
      while (sent < total) {
        checkActive();
        if (session.completed) {
          final error = await session.result;
          throw StateError(OtaError.text(error[2]));
        }
        final n = (total - sent) > chunk ? chunk : (total - sent);
        frame[0] = 0x02;
        frame.setRange(1, 1 + n, data, sent);
        final payload =
            n == chunk ? frame : Uint8List.sublistView(frame, 0, 1 + n);
        await ctrl.write(payload, withoutResponse: withoutResponse);
        checkActive();
        sent += n;

        final pct = (sent * 100) ~/ total;
        if (pct != lastPct) {
          lastPct = pct;
          yield PushProgress(
            percent: pct,
            sent: sent,
            total: total,
            step: '传输固件',
          );
        }
      }

      yield PushProgress(
        percent: 100,
        sent: total,
        total: total,
        step: '校验 sha256',
        log: '数据发完，等待板子校验',
      );

      checkActive();
      // Arm the already-subscribed mailbox before END: READY may arrive in write().
      session.verifying = true;
      await ctrl.write(Uint8List.fromList([0x03]), withoutResponse: false);
      final result = await session.result.timeout(const Duration(seconds: 20));
      checkActive();

      if (result[0] == OtaState.ready) {
        verified = true;
        yield const PushProgress(
          percent: 100,
          step: '等待重启确认',
          log: '写入校验通过，等待同一控制板重启并完成自检',
        );
        await _confirmReboot(device, before, target, session);
        yield PushProgress(
          percent: 100,
          step: '升级完成',
          done: true,
          success: true,
          log: '已确认新版本 ${target.version} 启动、自检通过',
        );
      } else {
        yield PushProgress(
          done: true,
          success: false,
          log: '板子报错：${OtaError.text(result[2])}',
        );
      }
    } on TimeoutException {
      yield PushProgress(
          done: true,
          success: false,
          log: verified ? '固件已写入，但重启确认超时，请检查控制板版本' : '等待板子校验超时，请重试');
    } catch (e) {
      yield PushProgress(done: true, success: false, log: '传输失败：$e');
    } finally {
      if (!verified) {
        try {
          await ctrl.write([0x04],
              withoutResponse: false).timeout(const Duration(seconds: 2));
        } catch (_) {
          // A disconnected device also aborts the pending image.
        }
      }
      await statusSub.cancel();
      if (identical(_transfer, session)) _transfer = null;
      _busy = false;
    }
  }

  Future<void> cancelPush() async {
    final session = _transfer;
    if (session == null) return;
    session.cancel();
    ++_connectionEpoch;
    try {
      await _ctrl?.write([0x04],
          withoutResponse: false).timeout(const Duration(seconds: 2));
    } catch (_) {
      // Disconnection also makes the firmware discard the pending image.
    }
    await _device?.disconnect();
  }

  Future<void> disconnect() async {
    ++_connectionEpoch;
    final device = _device;
    _device = null;
    await cancelPush();
    _ctrl = null;
    _stat = null;
    _info = null;
    _auth = null;
    try {
      await device?.disconnect();
    } catch (_) {}
  }
}
