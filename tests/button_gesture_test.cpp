#include <cassert>
#include "button_gesture.h"
using namespace controller;
int main(){
 ButtonGesture b;
 assert(b.update(true,100)==ButtonEvent::NONE);
 assert(b.update(false,180)==ButtonEvent::NONE);
 assert(b.update(false,400)==ButtonEvent::NONE);
 assert(b.update(false,501)==ButtonEvent::NEXT);
 assert(b.update(false,600)==ButtonEvent::NONE);
 assert(b.update(true,700)==ButtonEvent::NONE);
 assert(b.update(false,780)==ButtonEvent::NONE);
 assert(b.update(true,900)==ButtonEvent::NONE);
 assert(b.update(false,980)==ButtonEvent::HOME);
 assert(b.update(false,1500)==ButtonEvent::NONE);
 assert(b.update(true,1600)==ButtonEvent::NONE);
 assert(b.update(true,2201)==ButtonEvent::VOICE_DOWN);
 assert(b.update(true,2500)==ButtonEvent::NONE);
 assert(b.update(false,2600)==ButtonEvent::VOICE_UP);
 assert(b.update(false,3000)==ButtonEvent::NONE);
 // A long second press must record rather than emit a delayed page turn.
 b.update(true,3100);b.update(false,3180);b.update(true,3300);
 assert(b.update(true,3901)==ButtonEvent::VOICE_DOWN);
 assert(b.update(false,4000)==ButtonEvent::VOICE_UP);
 assert(b.update(false,4500)==ButtonEvent::NONE);
}
