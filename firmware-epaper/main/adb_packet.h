#pragma once
#include <stdint.h>
#include <stddef.h>
namespace controller {
constexpr uint32_t ADB_CNXN=0x4e584e43,ADB_AUTH=0x48545541,ADB_OPEN=0x4e45504f,ADB_OKAY=0x59414b4f,ADB_CLSE=0x45534c43,ADB_WRTE=0x45545257;
struct AdbHeader {uint32_t command,arg0,arg1,length,checksum,magic;};
static_assert(sizeof(AdbHeader)==24);
inline uint32_t adb_sum(const unsigned char *p,size_t n){uint32_t sum=0;for(size_t i=0;i<n;++i)sum+=p[i];return sum;}
inline AdbHeader adb_header(uint32_t cmd,uint32_t a,uint32_t b,const unsigned char *p,size_t n){return {cmd,a,b,(uint32_t)n,adb_sum(p,n),cmd^0xffffffffu};}
inline bool adb_valid(const AdbHeader &h,const unsigned char *p,size_t n){return h.length<=4096 && n==h.length && h.magic==(h.command^0xffffffffu) && h.checksum==adb_sum(p,n);}
}
