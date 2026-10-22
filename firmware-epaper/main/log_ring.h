#pragma once
#include <stddef.h>
#include <stdint.h>

namespace controller {
// Caller serializes access; retains the newest Capacity bytes without allocation.
template<size_t Capacity> class LogRing {
    char bytes[Capacity] = {};
    size_t next = 0, count = 0;
public:
    void append(const char *data, size_t size) {
        for(size_t i=0;i<size;++i){
            bytes[next]=data[i];next=(next+1)%Capacity;
            if(count<Capacity)++count;
        }
    }
    size_t snapshot(char *out, size_t size) const {
        if(!size)return 0;
        const size_t take=count<size-1?count:size-1;
        const size_t start=(next+Capacity-take)%Capacity;
        for(size_t i=0;i<take;++i)out[i]=bytes[(start+i)%Capacity];
        out[take]=0;return take;
    }
};
}
