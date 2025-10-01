import whisper
import subprocess
import os

# Load the Whisper model
model = whisper.load_model("base")  # Replace "base" with "tiny", "medium", or "large" as needed

def extract_audio(video_path, audio_path):
    """
    Extract audio from a video file using ffmpeg.
    """
    print("Extracting audio from video...")
    command = [
        "ffmpeg", "-i", video_path,  # Input file
        "-ab", "160k",  # Audio bitrate
        "-ac", "1",  # Mono audio
        "-ar", "44100",  # Audio sample rate
        "-vn",  # No video
        audio_path  # Output audio file
    ]
    subprocess.run(command, check=True)
    print(f"Audio extracted to: {audio_path}")

def transcribe_audio(audio_path):
    """
    Transcribe audio using Whisper.
    """
    print("Transcribing audio...")
    result = model.transcribe(audio_path)
    print("Transcription complete.")
    print("Transcribed Text:")
    print(result["text"])
    return result["text"]

if __name__ == "__main__":
    # Path to the video file
    video_file = "your_video.mp4"  # Replace with your video file path

    # Path to save the extracted audio
    audio_file = "extracted_audio.wav"

    # Step 1: Extract audio from the video
    extract_audio(video_file, audio_file)

    # Step 2: Transcribe the audio
    transcription = transcribe_audio(audio_file)

    # Step 3: Save the transcription to a text file
    with open("transcription.txt", "w") as f:
        f.write(transcription)
    print("Transcription saved to transcription.txt")

    # Clean up the extracted audio file (optional)
    os.remove(audio_file)
    print(f"Temporary audio file {audio_file} removed.")
