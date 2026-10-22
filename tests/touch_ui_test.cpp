#include <cassert>
#include <initializer_list>
#include "touch_ui.h"
using namespace controller;
int main(){
 assert(controller::touch_target(5,100,20)==controller::TouchTarget::SOUND_SETTINGS);
 assert(touch_target(5,50,75)==TouchTarget::START);
 assert(touch_target(5,40,160)==TouchTarget::NONE);
 assert(touch_target(5,150,140)==TouchTarget::START);
 assert(touch_target(4,30,173)==TouchTarget::HOME);
 assert(touch_target(4,90,173)==TouchTarget::HOME);
 assert(touch_target(4,175,173)==TouchTarget::STOP);
 assert(touch_target(2,90,95)==TouchTarget::CONFIRM);
 assert(touch_target(5,250,75)==TouchTarget::NONE);
 assert(touch_target(3,80,90,4)==TouchTarget::START);
 assert(voice_touch_target(50,90,1,true,false)==TouchTarget::FINISH);
 assert(voice_touch_target(50,90,1,false,false)==TouchTarget::FINISH);
 for(int stage:{2,4,7,10,11})assert(voice_touch_target(50,90,stage,true,false)==TouchTarget::STOP);
 assert(voice_touch_target(50,90,0,false,false)==TouchTarget::START);
 assert(voice_touch_target(170,175,1,true,false)==TouchTarget::STOP);
 assert(voice_touch_target(50,175,1,true,false)==TouchTarget::HOME);
 TouchContact contact;
 assert(contact.update(-1)==TouchEdge::NONE);
 assert(contact.update(1)==TouchEdge::NONE); // unknown/multitouch cannot become new down
 assert(contact.update(0)==TouchEdge::UP);
 assert(contact.update(1)==TouchEdge::DOWN);
 assert(contact.update(-1)==TouchEdge::NONE);
 assert(contact.update(1)==TouchEdge::NONE);
 assert(contact.update(0)==TouchEdge::UP);
 TouchGesture g;
 assert(!g.begin(1,2,TouchTarget::START,0)); // screen still refreshing
 assert(!g.release(2,100));
 assert(g.begin(2,2,TouchTarget::START,200));
 assert(!g.release(3,300)); // disconnect/page change invalidates pending tap
 assert(g.begin(3,3,TouchTarget::CONFIRM,400));
 assert(!g.release(3,500)); // short touch cannot enable HID
 assert(g.begin(3,3,TouchTarget::CONFIRM,600));
 assert(g.release(3,2700));
 assert(g.begin(4,4,TouchTarget::START,2800));g.cancel();assert(!g.release(4,2900));
}
