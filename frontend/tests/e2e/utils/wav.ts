// wav.ts
//
// Purpose
// -------
// Builds a minimal, real, decodable silent WAV file in-memory for the
// microphone/TTS E2E tests -- a mocked `POST /api/v1/voice/speak`
// response needs to be audio a real `<audio>` element can actually
// decode and "play" (so `VoiceContext`'s real `onEnded`/state logic
// exercises real playback, not an error path), without embedding a
// binary fixture file in the repo or making a real ElevenLabs call.
export function buildSilentWav(durationSeconds = 2, sampleRate = 8000): Buffer {
  const numSamples = Math.floor(durationSeconds * sampleRate);
  const bytesPerSample = 2; // 16-bit PCM
  const dataSize = numSamples * bytesPerSample;
  const buffer = Buffer.alloc(44 + dataSize);

  buffer.write("RIFF", 0);
  buffer.writeUInt32LE(36 + dataSize, 4);
  buffer.write("WAVE", 8);
  buffer.write("fmt ", 12);
  buffer.writeUInt32LE(16, 16); // fmt chunk size
  buffer.writeUInt16LE(1, 20); // PCM
  buffer.writeUInt16LE(1, 22); // mono
  buffer.writeUInt32LE(sampleRate, 24);
  buffer.writeUInt32LE(sampleRate * bytesPerSample, 28); // byte rate
  buffer.writeUInt16LE(bytesPerSample, 32); // block align
  buffer.writeUInt16LE(16, 34); // bits per sample
  buffer.write("data", 36);
  buffer.writeUInt32LE(dataSize, 40);
  // Remaining bytes already zero-initialized (silence).

  return buffer;
}
