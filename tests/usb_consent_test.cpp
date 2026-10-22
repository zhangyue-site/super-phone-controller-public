#include <cassert>
#include "mode_consent.h"
int main(){
 using controller::can_confirm;
 assert(!can_confirm(0,100,2200)); // never rendered
 assert(!can_confirm(1000,900,3000)); // held before visible
 assert(!can_confirm(1000,1100,3099)); // less than two seconds
 assert(can_confirm(1000,1100,3100));
 assert(!can_confirm(1000,15000,17000)); // expired
 assert(!can_confirm(1000,17000,16000)); // invalid clock ordering
 assert(!can_confirm(1000,1100,3100,false)); // left screen/stale UI
 assert(!controller::hid_on_boot());
 assert(!controller::wifi_on_boot());
}
