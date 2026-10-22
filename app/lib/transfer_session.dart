import 'dart:async';

/// One transfer owns one result mailbox. Late notifications cannot finish a new run.
class TransferSession {
  final _result = Completer<List<int>>();
  bool cancelled = false;
  bool verifying = false;
  bool get completed => _result.isCompleted;
  Future<List<int>> get result => _result.future;

  void accept(List<int> value) {
    if (completed || cancelled || value.length < 3) return;
    if (value[0] == 4 || (verifying && value[0] == 3)) {
      _result.complete(List<int>.of(value));
    }
  }

  void cancel() {
    cancelled = true;
    if (!completed) _result.complete([4, 0, 0]);
  }
}

/// Firmware queue accepts at most 512 ATT value bytes (one is the command byte) per ATT write.
int otaChunkSize(int mtu) => (mtu - 4).clamp(19, 511);
