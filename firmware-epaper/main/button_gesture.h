#pragma once
#include <cstdint>
namespace controller {
enum class ButtonEvent {NONE,NEXT,HOME,VOICE_DOWN,VOICE_UP};
struct ButtonGesture {
 bool down=false,voicing=false,pending=false,second=false;
 int64_t pressed=0,released=0;
 ButtonEvent update(bool value,int64_t now){
  if(value&&!down){down=true;pressed=now;voicing=false;second=pending&&now-released<=320;if(second)pending=false;}
  if(down&&value&&!voicing&&now-pressed>=600){voicing=true;pending=false;return ButtonEvent::VOICE_DOWN;}
  if(down&&!value){
   down=false;
   if(voicing){voicing=false;return ButtonEvent::VOICE_UP;}
   if(now-pressed<40)return ButtonEvent::NONE;
   if(second){second=false;pending=false;return ButtonEvent::HOME;}
   released=now;pending=true;
  }
  if(!down&&pending&&now-released>320){pending=false;return ButtonEvent::NEXT;}
  return ButtonEvent::NONE;
 }
};
// Active-low dry contacts and small onboard keys share a 30ms debounce.
struct DebouncedButton {
 bool candidate=false,stable=false;int64_t changed=0;
 bool update(bool raw,int64_t now){
  if(raw!=candidate){candidate=raw;changed=now;}
  if(now-changed>=30)stable=candidate;
  return stable;
 }
};
enum class ControlEvent {NONE,HOME,MUTE,STOP};
struct ControlButton {
 ButtonGesture gesture;
 ControlEvent update(bool value,int64_t now){
  switch(gesture.update(value,now)){
  case ButtonEvent::NEXT:return ControlEvent::HOME;
  case ButtonEvent::HOME:return ControlEvent::MUTE;
  case ButtonEvent::VOICE_DOWN:return ControlEvent::STOP;
  default:return ControlEvent::NONE;
  }
 }
};
struct PowerOffHold {
 bool held=false,fired=false;int64_t began=0;
 bool update(bool physical_power_down,int64_t now){
  if(!physical_power_down){held=false;fired=false;return false;}
  if(!held){held=true;began=now;}
  if(!fired&&now-began>=3000){fired=true;return true;}
  return false;
 }
};
// Stop wins over overlapping keys. Re-arm only after every contact releases.
struct StopReleaseGate {
 bool latched=false;
 void stop(){latched=true;}
 bool blocked(bool a,bool b,bool touch){
  if(latched&&!a&&!b&&!touch)latched=false;
  return latched;
 }
};
}
