#include "audio_output_policy.h"
#include <cassert>
int main(){
 using namespace controller;
 assert(audio_volume_ceiling_db-audio_pa_gain_db<=0.0f);
 // A write can return with an entire DMA ring still queued. Closing then loses
 // a short clip or its ending. Silent tail must push every real sample out.
 int queued=audio_dma_descriptors*audio_dma_frames;
 int audible_frames=960; // 60 ms click, shorter than codec startup plus buffering.
 int last_real=audio_warmup_frames+audible_frames-1;
 int played_at_close=audio_warmup_frames+audible_frames+audio_tail_frames-queued;
 assert(played_at_close>last_real);
 assert(audio_warmup_frames>=1600); // 100 ms of clocked silence for PA/codec.
 assert(audio_tail_frames>=queued+audio_dma_frames);
}
