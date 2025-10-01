import whisper

# Load the Whisper model
model = whisper.load_model("base")  # You can replace "base" with "tiny", "medium", or "large" as needed

def transcribe_audio(audio_path):
    """
    Transcribe the given audio file using Whisper.
    """
    print("Transcribing audio...")
    result = model.transcribe(audio_path)
    print("Transcription complete.")
    print("Transcribed Text:")
    print(result["text"])
    return result["text"]

if __name__ == "__main__":
    # Path to the audio file
    audio_file = "your_audio_file.wav"  # Replace with the path to your audio file

    # Step 1: Transcribe the audio
    transcription = transcribe_audio(audio_file)

    # Step 2: Save the transcription to a text file
    with open("transcription.txt", "w") as f:
        f.write(transcription)
    print("Transcription saved to transcription.txt")
