import whisper
import sounddevice as sd
import numpy as np
import wave
import time
import os  # for file deletion

# Load Whisper model
model = whisper.load_model("tiny")

# Audio settings
SAMPLE_RATE = 44100
CHANNELS = 1
CHUNK_DURATION = 0.5  # in seconds
SILENCE_THRESHOLD = 0.005  # adjust based on mic sensitivity
MAX_SILENCE_DURATION = 3  # seconds of silence before stopping
OUTPUT_FILE = "output.wav"

def is_silent(audio_chunk, threshold):
    """Determine if the audio chunk is silent based on RMS."""
    return np.sqrt(np.mean(audio_chunk ** 2)) < threshold

def record_until_silence(file_name, sample_rate, channels):
    """Record audio until silence is detected."""
    print("Recording... Speak into the mic.")
    chunk_samples = int(CHUNK_DURATION * sample_rate)
    max_silent_chunks = int(MAX_SILENCE_DURATION / CHUNK_DURATION)
    
    recording = []
    silent_chunk_count = 0

    while True:
        audio_chunk = sd.rec(chunk_samples, samplerate=sample_rate, channels=channels, dtype='float32')
        sd.wait()
        audio_chunk = audio_chunk.flatten()
        recording.append(audio_chunk)

        if is_silent(audio_chunk, SILENCE_THRESHOLD):
            silent_chunk_count += 1
        else:
            silent_chunk_count = 0

        if silent_chunk_count >= max_silent_chunks:
            print("Silence detected. Stopping recording.")
            break

    full_audio = np.concatenate(recording)

    # Save to WAV
    with wave.open(file_name, 'wb') as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # 16-bit audio
        wf.setframerate(sample_rate)
        wf.writeframes((full_audio * 32767).astype(np.int16).tobytes())
    
    print(f"Audio saved to {file_name}")

def transcribe_audio(file_name):
    print("Transcribing...")
    result = model.transcribe(file_name)
    print("Done.")
    print("Text:")
    print(result["text"])
    return result["text"]

if __name__ == "__main__":
    record_until_silence(OUTPUT_FILE, SAMPLE_RATE, CHANNELS)
    transcription = transcribe_audio(OUTPUT_FILE)

    with open("transcription.txt", "w") as f:
        f.write(transcription)
    print("Transcription saved.")

    # Delete audio file
    try:
        os.remove(OUTPUT_FILE)
        print(f"Deleted temporary audio file: {OUTPUT_FILE}")
    except Exception as e:
        print(f"Could not delete file: {e}")
