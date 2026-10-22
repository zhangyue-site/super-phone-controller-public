import 'package:flutter/material.dart';

/// 设计语言：深色为底，因为刷固件多在桌面/工位环境，且墨水屏设备本身偏冷色。
/// 单一强调色（青绿）用于"可以进行下一步"的操作，红色只留给错误。
class AppTheme {
  static const bg = Color(0xFF0E1116);
  static const surface = Color(0xFF161B22);
  static const surfaceHi = Color(0xFF1E252E);
  static const accent = Color(0xFF3DDC97);
  static const accentDim = Color(0xFF2A9D6E);
  static const danger = Color(0xFFE5534B);
  static const warn = Color(0xFFE3B341);
  static const text = Color(0xFFE6EDF3);
  static const textDim = Color(0xFF8B949E);
  static const border = Color(0xFF283039);

  static ThemeData build() {
    final base = ThemeData.dark(useMaterial3: true);
    return base.copyWith(
      scaffoldBackgroundColor: bg,
      colorScheme: const ColorScheme.dark(
        primary: accent,
        secondary: accentDim,
        surface: surface,
        error: danger,
        onPrimary: Color(0xFF06281B),
        onSurface: text,
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: bg,
        elevation: 0,
        centerTitle: false,
        titleTextStyle: TextStyle(
          color: text,
          fontSize: 20,
          fontWeight: FontWeight.w600,
          letterSpacing: -0.2,
        ),
      ),
      cardTheme: CardThemeData(
        color: surface,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(14),
          side: const BorderSide(color: border),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: accent,
          foregroundColor: const Color(0xFF06281B),
          minimumSize: const Size.fromHeight(52),
          textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          minimumSize: const Size.fromHeight(52),
          side: const BorderSide(color: border),
          foregroundColor: text,
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        ),
      ),
      dividerTheme:
          const DividerThemeData(color: border, thickness: 1, space: 1),
    );
  }

  /// 等宽字体样式，用于版本号、sha256、字节数这类"要看清"的内容。
  static const mono = TextStyle(
    fontFamily: 'monospace',
    fontFeatures: [FontFeature.tabularFigures()],
  );
}
