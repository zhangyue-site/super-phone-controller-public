#include "adb_command.h"
#include <cassert>
#include <cstring>
int main(){
 using namespace controller;char large[4096];AdbCommand t{};strcpy(t.text_b64,"5p2O5rSL");
 assert(adb_command(t,large,sizeof(large)));assert(strstr(large,"ADB_INPUT_B64"));assert(strstr(large,"trap"));
 assert(!strstr(large,"screencap"));assert(!strstr(large,"input tap"));assert(!strstr(large,"input swipe"));assert(!strstr(large,"am start"));
 strcpy(t.text_b64,"a';reboot");assert(!adb_command(t,large,sizeof(large)));t.text_b64[0]=0;assert(!adb_command(t,large,sizeof(large)));
 AdbReply reply;assert(reply.feed("part",4));assert(reply.feed("__PC_EXIT_0__",13));assert(reply.success());AdbReply failed;failed.feed("__PC_EXIT_1__",13);assert(!failed.success());AdbReply incomplete;incomplete.feed("ok",2);assert(!incomplete.success());
}
