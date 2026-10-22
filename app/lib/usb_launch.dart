import 'package:flutter/services.dart';

class UsbAttachment {
  final String serial, session;
  final String? remoteId, deviceId;
  const UsbAttachment(this.serial, this.session, this.remoteId, this.deviceId);
  bool get isBound => remoteId != null && deviceId != null;
  void validateBoard(String remote, String device) {
    if (isBound && (remote.toUpperCase() != remoteId || device != deviceId)) {
      throw StateError('蓝牙板身份与USB配对不一致，请返回重新配对');
    }
  }

  factory UsbAttachment.parse(Map<dynamic, dynamic> value) {
    final serial = value['serial'], session = value['session'];
    final remote = value['remoteId'], device = value['deviceId'];
    if (value['error'] is String) throw FormatException(value['error']);
    if (serial is! String ||
        !RegExp(r'^[0-9A-F]{12}$').hasMatch(serial) ||
        session is! String ||
        !RegExp('^$serial:[0-9]+\$').hasMatch(session) ||
        ((remote != null || device != null) &&
            (remote is! String ||
                !RegExp(r'^[0-9A-F]{2}(:[0-9A-F]{2}){5}$').hasMatch(remote) ||
                device is! String ||
                !RegExp(r'^[A-Za-z0-9_-]{1,64}$').hasMatch(device)))) {
      throw const FormatException('USB控制板身份或配对信息无效');
    }
    return UsbAttachment(serial, session, remote as String?, device as String?);
  }
}

class UsbAutoShareGate {
  final _attempted = <String>{};
  bool claim(UsbAttachment? usb,
      {required bool bluetoothOn, required bool opening}) {
    if (usb == null ||
        !usb.isBound ||
        !bluetoothOn ||
        opening ||
        _attempted.contains(usb.session)) {
      return false;
    }
    _attempted.add(usb.session);
    return true;
  }

  void consume(UsbAttachment usb) => _attempted.add(usb.session);
}

class UsbLaunch {
  static const channel = MethodChannel('pcflash/usb');
  static Future<UsbAttachment?> snapshot() async {
    try {
      final value = await channel.invokeMapMethod<dynamic, dynamic>('snapshot');
      return value == null ? null : UsbAttachment.parse(value);
    } on MissingPluginException {
      return null;
    }
  }

  static Future<void> bind(
      UsbAttachment usb, String remote, String device) async {
    await channel.invokeMethod<void>('bind', {
      'session': usb.session,
      'remoteId': remote.toUpperCase(),
      'deviceId': device
    });
  }
}
