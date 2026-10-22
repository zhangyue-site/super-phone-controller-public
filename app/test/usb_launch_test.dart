import 'package:flutter_test/flutter_test.dart';
import 'package:pcflash/usb_launch.dart';

void main() {
  Map<String, dynamic> attachment({bool bound = true}) => {
        'serial': 'AABBCCDDEEFF',
        'session': 'AABBCCDDEEFF:1',
        if (bound) 'remoteId': 'AA:BB:CC:DD:EE:01',
        if (bound) 'deviceId': 'epaper-01',
      };
  test('USB binding requires complete validated identity', () {
    expect(UsbAttachment.parse(attachment()).isBound, isTrue);
    expect(UsbAttachment.parse(attachment(bound: false)).isBound, isFalse);
    expect(() => UsbAttachment.parse({...attachment(), 'serial': ''}),
        throwsFormatException);
    expect(() => UsbAttachment.parse({...attachment(), 'remoteId': 'nearby'}),
        throwsFormatException);
    expect(() => UsbAttachment.parse({...attachment(), 'deviceId': null}),
        throwsFormatException);
    expect(() => UsbAttachment.parse({...attachment(), 'session': 'OTHER:1'}),
        throwsFormatException);
  });
  test(
      'one automatic attempt per attachment; Bluetooth off does not consume it',
      () {
    final gate = UsbAutoShareGate();
    final usb = UsbAttachment.parse(attachment());
    expect(gate.claim(usb, bluetoothOn: false, opening: false), isFalse);
    expect(gate.claim(usb, bluetoothOn: true, opening: true), isFalse);
    expect(gate.claim(usb, bluetoothOn: true, opening: false), isTrue);
    expect(gate.claim(usb, bluetoothOn: true, opening: false), isFalse);
    expect(
        gate.claim(
            UsbAttachment.parse({...attachment(), 'session': 'AABBCCDDEEFF:2'}),
            bluetoothOn: true,
            opening: false),
        isTrue);
  });
  test('first pairing never chooses a nearby BLE board automatically', () {
    expect(
        UsbAutoShareGate().claim(UsbAttachment.parse(attachment(bound: false)),
            bluetoothOn: true, opening: false),
        isFalse);
  });
  test('remembered board must match both BLE address and server identity', () {
    final usb = UsbAttachment.parse(attachment());
    usb.validateBoard('aa:bb:cc:dd:ee:01', 'epaper-01');
    expect(() => usb.validateBoard('AA:BB:CC:DD:EE:02', 'epaper-01'),
        throwsStateError);
    expect(() => usb.validateBoard('AA:BB:CC:DD:EE:01', 'other-board'),
        throwsStateError);
  });
}
