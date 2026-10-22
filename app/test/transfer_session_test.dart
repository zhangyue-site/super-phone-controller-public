import 'package:flutter_test/flutter_test.dart';
import 'package:pcflash/transfer_session.dart';

void main() {
  test('MTU payload respects firmware queue capacity', () {
    expect(otaChunkSize(23), 19);
    expect(otaChunkSize(517), 511);
    expect(otaChunkSize(185), 181);
  });
  test('READY during END is retained until waiter attaches', () async {
    final s = TransferSession();
    s.accept([3, 100, 0]);
    expect(s.completed, false);
    s.verifying = true;
    s.accept([3, 100, 0]);
    expect((await s.result)[0], 3);
  });
  test('cancel wins over a late ready packet', () async {
    final s = TransferSession()..verifying = true;
    s.cancel();
    s.accept([3, 100, 0]);
    expect(s.cancelled, true);
    expect((await s.result)[0], 4);
    final next = TransferSession();
    expect(next.completed, false);
  });
  test('device error during upload is retained', () async {
    final s = TransferSession();
    s.accept([4, 20, 5]);
    expect((await s.result)[2], 5);
  });
}
