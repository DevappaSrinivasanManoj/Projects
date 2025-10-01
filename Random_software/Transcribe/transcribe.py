import whisper
import sounddevice as sd
import numpy as np
import wave

# Load the Whisper model
model = whisper.load_model("tiny")  # You can replace 'base' with other models like 'tiny' or 'large'

# Parameters for audio recording
SAMPLE_RATE = 44100  # Standard sampling rate for audio
CHANNELS = 1  # Mono audio
DURATION = 20  # Record duration in seconds (adjust as needed)
OUTPUT_FILE = "output.wav"  # File to save the recorded audio

def record_audio(file_name, duration, sample_rate, channels):
    """Record audio from the default system audio."""
    print("Recording audio...")
    audio_data = sd.rec(
        int(duration * sample_rate), samplerate=sample_rate, channels=channels, dtype="float32"
    )
    sd.wait()  # Wait until recording is complete
    print("Recording complete.")
    
    # Save recorded audio to a .wav file
    with wave.open(file_name, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # 16-bit audio
        wf.setframerate(sample_rate)
        wf.writeframes((audio_data * 32767).astype("int16").tobytes())
    print(f"Audio saved to {file_name}")

def transcribe_audio(file_name):
    """Transcribe the audio file using Whisper."""
    print("Transcribing audio...")
    result = model.transcribe(file_name)
    print("Transcription complete.")
    print("Transcribed Text:")
    print(result["text"])
    return result["text"]

if __name__ == "__main__":
    # Step 1: Record audio
    record_audio(OUTPUT_FILE, DURATION, SAMPLE_RATE, CHANNELS)
    
    # Step 2: Transcribe the recorded audio
    transcription = transcribe_audio(OUTPUT_FILE)

    # Step 3: Save transcription to a file (optional)
    with open("transcription.txt", "w") as f:
        f.write(transcription)
    print("Transcription saved to transcription.txt")
