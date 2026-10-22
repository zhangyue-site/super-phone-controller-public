#include <cassert>
#include "button_gesture.h"
using namespace controller;
int main(){
 DebouncedButton debounce;
 assert(!debounce.update(true,0));assert(!debounce.update(false,10));
 assert(!debounce.update(true,20));assert(!debounce.update(true,49));
 assert(debounce.update(true,50));assert(debounce.update(false,60));
 assert(!debounce.update(false,90));
 PowerOffHold power;
 assert(!power.update(false,10000)); // external B never enters physical-power policy
 assert(!power.update(true,11000));assert(!power.update(true,13999));
 assert(power.update(true,14000));assert(!power.update(true,15000));
 assert(!power.update(false,15100));
 StopReleaseGate gate;
 gate.stop();
 assert(gate.blocked(true,true,false));
 assert(gate.blocked(true,false,false)); // B released, A still held must not restart voice
 assert(gate.blocked(false,false,true)); // touch stop also waits for touch release
 assert(!gate.blocked(false,false,false));
 assert(!gate.blocked(true,false,false)); // a fresh A press is allowed
 ControlButton b;
 assert(b.update(true,100)==ControlEvent::NONE);
 assert(b.update(false,180)==ControlEvent::NONE);
 assert(b.update(false,501)==ControlEvent::HOME);
 assert(b.update(true,700)==ControlEvent::NONE);b.update(false,780);
 b.update(true,900);assert(b.update(false,980)==ControlEvent::MUTE);
 assert(b.update(false,1500)==ControlEvent::NONE);
 b.update(true,1600);assert(b.update(true,2200)==ControlEvent::STOP);
 assert(b.update(true,4000)==ControlEvent::NONE);
 assert(b.update(false,4100)==ControlEvent::NONE);
 assert(b.update(false,4500)==ControlEvent::NONE);
 // A short first tap followed by a held second tap must stop, never toggle mute.
 b.update(true,5000);b.update(false,5100);b.update(true,5200);
 assert(b.update(true,5800)==ControlEvent::STOP);
 assert(b.update(false,5900)==ControlEvent::NONE);
}
