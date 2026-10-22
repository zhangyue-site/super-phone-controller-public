#include <cassert>
#include <cstring>
#include "log_ring.h"
int main(){
 controller::LogRing<8> ring;char out[20];
 assert(ring.snapshot(out,sizeof(out))==0);
 ring.append("abc",3);assert(ring.snapshot(out,sizeof(out))==3);assert(!strcmp(out,"abc"));
 ring.append("defghijk",8);assert(ring.snapshot(out,sizeof(out))==8);assert(!strcmp(out,"defghijk"));
 char small[4];assert(ring.snapshot(small,sizeof(small))==3);assert(!strcmp(small,"ijk"));
 ring.append("L",1);ring.snapshot(out,sizeof(out));assert(!strcmp(out,"efghijkL"));
 assert(ring.snapshot(out,0)==0);
}
