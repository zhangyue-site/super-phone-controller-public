import 'dart:convert';

class BoardInfo {
  final String device, version, elfSha256, boot;
  final int imageState;
  const BoardInfo(
      this.device, this.version, this.elfSha256, this.boot, this.imageState);
  static BoardInfo parse(List<int> bytes) {
    final dynamic obj = jsonDecode(utf8.decode(bytes));
    if (obj is! Map ||
        obj['protocol'] != 1 ||
        obj['device'] is! String ||
        !RegExp(r'^[A-Za-z0-9_-]{1,64}$').hasMatch(obj['device']) ||
        obj['version'] is! String ||
        !RegExp(r'^[A-Za-z0-9._-]{1,31}$').hasMatch(obj['version']) ||
        obj['elfSha256'] is! String ||
        !RegExp(r'^[0-9a-f]{64}$').hasMatch(obj['elfSha256']) ||
        obj['boot'] is! String ||
        !RegExp(r'^[0-9a-f]{32}$').hasMatch(obj['boot']) ||
        obj['imageState'] is! int) {
      throw const FormatException('控制板启动信息无效');
    }
    return BoardInfo(obj['device'], obj['version'], obj['elfSha256'],
        obj['boot'], obj['imageState']);
  }

  bool confirms(BoardInfo before, String targetVersion, String targetElf) =>
      device == before.device &&
      boot != before.boot &&
      version == targetVersion &&
      elfSha256 == targetElf &&
      imageState == 2;
}
