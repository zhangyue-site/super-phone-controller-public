#pragma once
namespace controller {
constexpr float audio_pa_gain_db=6.0f;
constexpr float audio_volume_floor_db=-44.0f;
constexpr float audio_volume_ceiling_db=6.0f; // Minus PA compensation: DAC unity at UI 100.
constexpr unsigned audio_dma_descriptors=4;
constexpr unsigned audio_dma_frames=128;
constexpr unsigned audio_warmup_frames=1600; // 100 ms at 16 kHz.
// Push real audio beyond both the queued DMA ring and the active descriptor.
constexpr unsigned audio_tail_frames=(audio_dma_descriptors+2)*audio_dma_frames;
}
