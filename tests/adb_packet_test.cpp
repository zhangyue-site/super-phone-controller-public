#include <cassert>
#include "adb_packet.h"
int main(){
 using namespace controller;
 unsigned char token[20]={1,2,3};
 auto h=adb_header(ADB_AUTH,1,0,token,20);
 assert(adb_valid(h,token,20));
 h.magic^=1;assert(!adb_valid(h,token,20));h.magic^=1;
 h.length=4097;assert(!adb_valid(h,token,20));h.length=20;
 token[0]^=1;assert(!adb_valid(h,token,20));
 assert(!adb_valid(h,token,19));
}
