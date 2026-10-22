#pragma once
// Called by the voice worker after upload; network is closed before any ADB input.
bool controller_dialogue_run(unsigned sequence);
void controller_voice_state(int stage);
bool controller_audio_play_pcm(const unsigned char *data,unsigned size);

void controller_dialogue_screen(const unsigned char *frame);

bool controller_dialogue_remote_claim(unsigned sequence);
bool controller_dialogue_remote_run(unsigned sequence);
