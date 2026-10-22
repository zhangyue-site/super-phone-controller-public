import 'package:flutter/material.dart';
import 'theme.dart';

/// 呼吸的圆点，表示"正在进行的动作"。比转圈更轻，不抢视线。
class PulsingDot extends StatefulWidget {
  final Color color;
  final double size;

  const PulsingDot({super.key, this.color = AppTheme.accent, this.size = 10});

  @override
  State<PulsingDot> createState() => _PulsingDotState();
}

class _PulsingDotState extends State<PulsingDot>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1100),
  )..repeat(reverse: true);

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _c,
      builder: (_, __) => Container(
        width: widget.size,
        height: widget.size,
        decoration: BoxDecoration(
          color: widget.color.withValues(alpha: 0.35 + 0.65 * _c.value),
          shape: BoxShape.circle,
        ),
      ),
    );
  }
}

class InfoBanner extends StatelessWidget {
  final IconData icon;
  final String text;
  final Color color;

  const InfoBanner({
    super.key,
    required this.icon,
    required this.text,
    this.color = AppTheme.warn,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(11),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: color, size: 18),
          const SizedBox(width: 10),
          Expanded(
            child: Text(text,
                style: TextStyle(color: color, fontSize: 13, height: 1.45)),
          ),
        ],
      ),
    );
  }
}

/// 推送步骤清单：把固件状态机的几个阶段可视化，用户随时知道卡在哪一步。
class StepList extends StatelessWidget {
  /// 每步状态：0 未开始，1 进行中，2 完成
  final List<(String, int)> steps;

  const StepList({super.key, required this.steps});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        for (var i = 0; i < steps.length; i++)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 7),
            child: Row(
              children: [
                _marker(steps[i].$2),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    steps[i].$1,
                    style: TextStyle(
                      color:
                          steps[i].$2 == 0 ? AppTheme.textDim : AppTheme.text,
                      fontSize: 14,
                      fontWeight:
                          steps[i].$2 == 1 ? FontWeight.w600 : FontWeight.w400,
                    ),
                  ),
                ),
                if (steps[i].$2 == 1) const PulsingDot(size: 8),
              ],
            ),
          ),
      ],
    );
  }

  Widget _marker(int st) {
    if (st == 2) {
      return Container(
        width: 18,
        height: 18,
        decoration:
            const BoxDecoration(color: AppTheme.accent, shape: BoxShape.circle),
        child: const Icon(Icons.check, size: 12, color: Color(0xFF06281B)),
      );
    }
    if (st == 1) {
      return Container(
        width: 18,
        height: 18,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          border: Border.all(color: AppTheme.accent, width: 2),
        ),
      );
    }
    return Container(
      width: 18,
      height: 18,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        border: Border.all(color: AppTheme.border, width: 1.5),
      ),
    );
  }
}

/// 环形进度：比线性条在窄屏上更醒目，中间能放百分比大字。
class RingProgress extends StatelessWidget {
  final double value; // 0..1
  final String center;
  final String? subtitle;
  final Color color;

  const RingProgress({
    super.key,
    required this.value,
    required this.center,
    this.subtitle,
    this.color = AppTheme.accent,
  });

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 176,
      height: 176,
      child: Stack(
        alignment: Alignment.center,
        children: [
          SizedBox(
            width: 176,
            height: 176,
            child: TweenAnimationBuilder<double>(
              tween: Tween(begin: 0, end: value.clamp(0, 1)),
              duration: const Duration(milliseconds: 220),
              builder: (_, v, __) => CircularProgressIndicator(
                value: v,
                strokeWidth: 9,
                backgroundColor: AppTheme.surfaceHi,
                valueColor: AlwaysStoppedAnimation(color),
                strokeCap: StrokeCap.round,
              ),
            ),
          ),
          Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(center,
                  style: TextStyle(
                      color: color,
                      fontSize: 40,
                      fontWeight: FontWeight.w300,
                      fontFeatures: const [FontFeature.tabularFigures()])),
              if (subtitle != null)
                Padding(
                  padding: const EdgeInsets.only(top: 2),
                  child: Text(subtitle!,
                      style: const TextStyle(
                          color: AppTheme.textDim, fontSize: 12)),
                ),
            ],
          ),
        ],
      ),
    );
  }
}
