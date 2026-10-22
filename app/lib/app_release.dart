import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

class AppRelease {
  static const channel = MethodChannel('pcflash/app');
  static Future<void> show(BuildContext context) async {
    String version;
    try {
      final value = await channel.invokeMapMethod<String, dynamic>('info');
      version =
          '${value?["versionName"] ?? "未知"}（${value?["versionCode"] ?? "未知"}）';
    } catch (_) {
      version = '暂时无法读取';
    }
    if (!context.mounted) return;
    await showDialog<void>(
        context: context,
        builder: (dialogContext) => AlertDialog(
              title: const Text('App 版本与更新'),
              content: Text(
                  '本机已安装：$version\n\nApp 更新：从官方下载页安装新版，保留原应用。\n控制板固件：连接板子后，在固件页下载并升级。两者分别更新。'),
              actions: [
                TextButton(
                    onPressed: () => Navigator.pop(dialogContext),
                    child: const Text('关闭')),
                FilledButton(
                    onPressed: () async {
                      try {
                        await channel.invokeMethod<void>('openDownload');
                      } catch (_) {
                        if (context.mounted) {
                          ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(
                                  content: Text(
                                      '无法打开浏览器，请访问 d.zhangyue.site 的控制板升级助手页面')));
                        }
                      }
                    },
                    child: const Text('官方下载与更新')),
              ],
            ));
  }
}
