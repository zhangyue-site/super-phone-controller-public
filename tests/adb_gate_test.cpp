#include <cassert>
#include "adb_gate.h"
int main(){
 controller::AdbGate g;unsigned old=g.ticket(),token,newtoken;
 assert(!g.active(old));g.revoke();assert(!g.activate(old,token));
 assert(g.activate(g.ticket(),token));assert(g.active(token));
 g.revoke();assert(!g.active(token));
 assert(g.activate(g.ticket(),newtoken));
 assert(!g.finish(token));assert(g.active(newtoken));
 assert(g.finish(newtoken));assert(!g.active(newtoken));
}
