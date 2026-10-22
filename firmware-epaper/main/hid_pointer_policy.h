#pragma once
#include <stdint.h>
namespace controller {
enum class PointerKind {move,click,drag};
struct PointerCommand {PointerKind kind;int x,y,x2,y2,duration_ms;};
inline bool valid_pointer(const PointerCommand& c,bool x2,bool y2,bool duration){
 auto coordinate=[](int n){return n>=0&&n<=32767;};
 if(!coordinate(c.x)||!coordinate(c.y))return false;
 if(c.kind==PointerKind::drag)return x2&&y2&&duration&&coordinate(c.x2)&&coordinate(c.y2)&&c.duration_ms>=100&&c.duration_ms<=1200;
 return (c.kind==PointerKind::move||c.kind==PointerKind::click)&&!x2&&!y2&&!duration;
}
struct PointerReport {uint8_t buttons;uint16_t x,y;};
// USB service owns advancement. A report advances only after TinyUSB accepts it.
class PointerSequence {
 enum Stage {idle,move,press,held,release,done,failed};
 Stage stage=idle;PointerCommand cmd{};bool cancelled=false,down=false;
 uint32_t pressed_at=0,last_at=0;uint16_t current_x=0,current_y=0;
 public:
 bool active()const{return stage==move||stage==press||stage==held||stage==release;}
 bool success()const{return stage==done&&!cancelled;}
 bool begin(const PointerCommand& c){if(active()||!valid_pointer(c,c.kind==PointerKind::drag,c.kind==PointerKind::drag,c.kind==PointerKind::drag))return false;cmd=c;stage=move;cancelled=false;down=false;current_x=c.x;current_y=c.y;return true;}
 void cancel(){cancelled=true;stage=down?release:failed;}
 // A detached USB host cannot retain this device's button state.
 void detached(){cancelled=true;down=false;stage=failed;}
 bool next(uint32_t now,PointerReport& report){
  if(!active())return false;
  if(stage==held){
   if(cmd.kind==PointerKind::click){if(now-pressed_at<40)return false;stage=release;}
   else {if(now-last_at<20)return false;uint32_t elapsed=now-pressed_at;
    if(elapsed>(uint32_t)cmd.duration_ms)elapsed=cmd.duration_ms;
    current_x=cmd.x+((int64_t)(cmd.x2-cmd.x)*elapsed)/cmd.duration_ms;
    current_y=cmd.y+((int64_t)(cmd.y2-cmd.y)*elapsed)/cmd.duration_ms;
   }
  }
  report={uint8_t(stage==press||stage==held?1:0),current_x,current_y};return true;
 }
 void submitted(uint32_t now){
  if(stage==move){stage=cmd.kind==PointerKind::move?done:press;}
  else if(stage==press){down=true;pressed_at=last_at=now;stage=held;}
  else if(stage==held){last_at=now;if(now-pressed_at>=(uint32_t)cmd.duration_ms)stage=release;}
  else if(stage==release){down=false;stage=cancelled?failed:done;}
 }
};
}
