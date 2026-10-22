#pragma once
#include <cmath>
#include <cstdint>
#include <initializer_list>
namespace controller {
struct PressFeedback {
 bool held=false;
 bool update(bool down){bool pressed=down&&!held;held=down;return pressed;}
};
enum class Feedback { CLICK, LISTEN, SUCCESS, FAILURE, STOP };
inline bool feedback_allowed(int volume,bool muted,bool recording){return volume>0&&!muted&&!recording;}
inline int feedback_samples(Feedback cue){return cue==Feedback::CLICK?960:cue==Feedback::STOP?1440:3840;}
// 16 kHz mono; 5 ms ramps avoid amplifier clicks. Two notes have a silent gap.
inline int16_t feedback_sample(Feedback cue,int index){
 int total=feedback_samples(cue);if(index<0||index>=total)return 0;
 bool pair=total==3840;int local=pair?index%1920:index;
 int length=pair?1440:total;if(local>=length)return 0;
 double hz=cue==Feedback::CLICK?1000:cue==Feedback::STOP?440:
   cue==Feedback::LISTEN?(index<1920?700:1100):
   cue==Feedback::SUCCESS?(index<1920?900:1300):(index<1920?600:350);
 double ramp=std::fmin(1.0,std::fmin(local/80.0,(length-1-local)/80.0));
 return (int16_t)(24000*ramp*std::sin(6.283185307179586*hz*local/16000));
}
}
