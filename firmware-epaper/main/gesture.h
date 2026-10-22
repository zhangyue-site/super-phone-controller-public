#pragma once
#include <cstdint>

// 轨迹手势识别：按下→跟踪→抬起，抬手时给出一次判定结果。
// 墨水屏刷新慢（2-4s），一切反馈都在抬手后发生，所以这里只做
// "抬手时是什么手势"这一个判定，不做拖动跟随。
namespace controller {
enum class Gesture : uint8_t {
    None = 0,   // 普通点击/没形成手势——交给按钮命中逻辑
    SwipeUp,
    SwipeDown,
    SwipeLeft,
    SwipeRight,
    DoubleTap,
    LongPress,
};

struct GesturePoint { int x; int y; int64_t ms; };

class GestureDetector {
public:
    // 每个采样周期调用一次：down=当前按压状态，x/y=坐标（无触摸时忽略坐标）。
    // 返回值仅在"抬手判定出结果"的那一次调用里非 None，其余时刻恒为 None。
    Gesture feed(bool down, int x, int y, int64_t now_ms);

    // 供外部复位（切页/屏幕刷新世代变化时调用，防跨世代误判）。
    void reset() { active_ = false; release_ms_ = -100000; }

private:
    bool active_ = false;
    GesturePoint start_{0, 0, 0};
    GesturePoint last_{0, 0, 0};
    int64_t last_move_ms_ = 0;     // 上次显著移动时间，用于长按判定
    int down_count_ = 0;           // 本次按压收到的采样数（双击去抖用）
    int64_t release_ms_ = -100000; // 上次抬手时间
    int last_tap_x_ = 0, last_tap_y_ = 0;
    bool moved_ = false;           // 位移是否超过 tap 阈值
};
} // namespace controller
