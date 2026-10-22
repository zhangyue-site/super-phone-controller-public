#include <cassert>
#include <initializer_list>
#include "touch_ui.h"
#include "gesture.h"
#include "audio_policy.h"
using namespace controller;
int main() {
 for(int home : {4,5}) {
  int p=home;
  for(int i=0;i<home+7;++i) {
   assert(previous_page(next_page(p,home),home)==p);
   assert(next_page(previous_page(p,home),home)==p);
   assert(touch_target(p,40,173,home)==TouchTarget::HOME);
   assert(touch_target(p,150,173,home)==TouchTarget::STOP);
   p=next_page(p,home);
  }
  assert(p==home);
  assert(touch_target(home,90,140,home)==TouchTarget::START);
  assert(touch_target(home+6,35,80,home)==TouchTarget::VOLUME_DOWN);
  assert(touch_target(home+6,150,80,home)==TouchTarget::VOLUME_UP);
  assert(touch_target(home+6,35,140,home)==TouchTarget::MUTE);
  assert(touch_target(home+6,150,140,home)==TouchTarget::SOUND_TEST);
 }
 assert(voice_contact(0,0,0,true)==VoiceContact::SEND);
 assert(voice_contact(0,0,0,false)==VoiceContact::CANCEL); // a real page change invalidates capture
 assert(voice_contact(1,80,70,true)==VoiceContact::KEEP);
 assert(voice_contact(1,80,160,true)==VoiceContact::CANCEL);
 assert(voice_contact(-1,80,70,true)==VoiceContact::CANCEL);
 assert(voice_contact(1,80,70,false)==VoiceContact::CANCEL);
 assert(clamp_volume(-20)==0 && clamp_volume(120)==100);
 assert(clamp_volume(60)==60);
 GestureDetector g;
 g.feed(true,50,60,100);
 g.feed(true,50,60,2000);
 assert(g.feed(false,0,0,2100)==Gesture::LongPress);
 // Tap matching must use the last contact, not zero-filled release coordinates.
 g.feed(true,150,80,3000);g.feed(false,0,0,3100);
 g.feed(true,150,80,3200);
 assert(g.feed(false,0,0,3300)==Gesture::DoubleTap);
 g.reset();
 g.feed(true,150,80,3400);
 assert(g.feed(false,0,0,3500)==Gesture::None);
}
