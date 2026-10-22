#include <cassert>
#include "adb_stream.h"
using namespace controller;
int main(){
 AdbStream s(2);
 assert(!s.can_send);
 assert(s.receive(ADB_OKAY,8,1)==StreamEvent::IGNORE);
 assert(s.receive(ADB_OKAY,9,2)==StreamEvent::OPENED);
 assert(s.can_send && s.sent() && !s.can_send && !s.sent());
 assert(s.receive(ADB_WRTE,9,2)==StreamEvent::DATA);
 assert(s.receive(ADB_OKAY,9,2)==StreamEvent::ACK && s.can_send);
 assert(s.receive(ADB_WRTE,10,2)==StreamEvent::ERROR);
 assert(s.receive(ADB_CLSE,9,2)==StreamEvent::CLOSED);
 AdbStream rejected(3);
 assert(rejected.receive(ADB_CLSE,0,3)==StreamEvent::CLOSED);
}
