#include "gesture.h"

namespace controller {
namespace {
// 阈值按 200x200 屏 + FT6336 采样率定。像素位移超过这些就算滑动；
// 长按要求期间几乎没动；双击要求两次快速、位置接近的抬起。
constexpr int    kSwipeMinPx   = 60;   // 滑动最小位移（屏宽 200 的 30%）
constexpr int    kTapMaxPx     = 20;   // 点按最大位移
constexpr int    kLongPressMs  = 1800; // 长按时长
constexpr int    kDoubleMs     = 450;  // 双击两抬手间隔
constexpr int    kDoublePx     = 40;   // 双击两次位置接近度
constexpr int    kMaxPressMs   = 5000; // 超长按压丢弃（多半是搁置误触）

inline int dist(int ax, int ay, int bx, int by) {
    int dx = ax - bx, dy = ay - by;
    return dx * dx + dy * dy;
}
} // namespace

Gesture GestureDetector::feed(bool down, int x, int y, int64_t now_ms) {
    if (!down) {
        if (!active_) return Gesture::None;
        active_ = false;
        int64_t held = now_ms - start_.ms;

        // 超长按压是搁置/误触，丢弃。
        if (held > kMaxPressMs) return Gesture::None;

        // 滑动：位移够大且主方向明显。
        if (moved_ && dist(start_.x, start_.y, last_.x, last_.y) >= kSwipeMinPx * kSwipeMinPx) {
            int dx = last_.x - start_.x, dy = last_.y - start_.y;
            if (dx * dx > dy * dy) return dx > 0 ? Gesture::SwipeRight : Gesture::SwipeLeft;
            return dy > 0 ? Gesture::SwipeDown : Gesture::SwipeUp;
        }

        // 长按：没怎么动 + 按压够久。
        if (!moved_ && held >= kLongPressMs) return Gesture::LongPress;

        // 双击：与上次抬手间隔近、位置近、且两次都是点按。
        if (!moved_ && now_ms - release_ms_ <= kDoubleMs &&
            dist(last_.x, last_.y, last_tap_x_, last_tap_y_) <= kDoublePx * kDoublePx) {
            release_ms_ = -100000;  // 消费掉，防三连击当两次双击
            return Gesture::DoubleTap;
        }

        // 普通点按：记录抬手现场供下次双击判定，按钮命中逻辑照旧。
        release_ms_ = moved_ ? -100000 : now_ms;
        last_tap_x_ = last_.x;
        last_tap_y_ = last_.y;
        return Gesture::None;
    }

    if (!active_) {
        active_ = true;
        start_ = {x, y, now_ms};
        moved_ = false;
        last_move_ms_ = now_ms;
    }
    // 跟踪显著移动：超过 tap 阈值即标记（长按从此失格），并刷新末点。
    if (dist(start_.x, start_.y, x, y) > kTapMaxPx * kTapMaxPx) {
        moved_ = true;
        last_move_ms_ = now_ms;
    }
    last_ = {x, y, now_ms};
    return Gesture::None;
}
} // namespace controller
