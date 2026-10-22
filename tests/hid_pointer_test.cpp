#include "../firmware-epaper/main/hid_pointer_policy.h"
#include <cassert>
using namespace controller;
int main(){
 PointerCommand c{PointerKind::click,123,456,0,0,0};
 assert(valid_pointer(c,false,false,false));
 c.x=-1;assert(!valid_pointer(c,false,false,false));c.x=123;
 assert(!valid_pointer(c,true,false,false));
 PointerSequence s;assert(s.begin(c));PointerReport r;
 assert(s.next(0,r)&&r.buttons==0&&r.x==123);s.submitted(0);
 assert(s.next(10,r)&&r.buttons==1);s.submitted(10);
 assert(!s.next(20,r));assert(s.next(50,r)&&r.buttons==0);s.submitted(50);
 assert(s.success()&&!s.active());
 assert(s.begin(c));assert(s.next(60,r));s.submitted(60);s.cancel();
 assert(!s.active()&&!s.success());assert(!s.next(70,r));
 assert(s.begin(c));s.submitted(80);s.submitted(90);s.cancel();
 assert(s.active()&&s.next(91,r)&&r.buttons==0);s.submitted(91);assert(!s.success()&&!s.active());
 PointerCommand d{PointerKind::drag,0,0,32767,32767,100};
 assert(valid_pointer(d,true,true,true));d.duration_ms=99;assert(!valid_pointer(d,true,true,true));d.duration_ms=100;
 assert(s.begin(d));s.submitted(100);s.submitted(110);
 assert(s.next(160,r)&&r.buttons==1&&r.x>0&&r.x<32767);s.submitted(160);
 assert(s.next(210,r)&&r.x==32767&&r.buttons==1);s.submitted(210);
 assert(s.next(220,r)&&r.buttons==0&&r.x==32767);s.submitted(220);assert(s.success());
 PointerCommand m{PointerKind::move,32767,0,0,0,0};assert(s.begin(m));s.submitted(300);assert(s.success());
 s.cancel();assert(!s.success());
}
