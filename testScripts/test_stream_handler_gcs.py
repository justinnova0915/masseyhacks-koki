import requests
import time
import json

# Configuration
STREAM_HANDLER_URL = "http://34.28.171.172"  # Base URL of the stream handler service
SAMPLE_AUDIO_FILE = "sample_audio.raw"      # Path to a sample raw audio file

# --- User Instructions ---
# To run this script:
# 1. Ensure you have the 'requests' library installed (pip install requests).
# 2. Place a small raw audio file named 'sample_audio.raw' in the same directory as this script.
#    - This file should contain raw PCM audio data.
#    - If 'sample_audio.raw' is not found, the script will generate and send dummy audio data.
# 3. Run the script from your terminal: python test_stream_handler_gcs.py
# 4. Monitor the logs of 'kokoro-stream-handler-service' and 'kokoro-ai-agent-service'
#    to observe the GCS upload and Pub/Sub notification pipeline.
#
# How to create a dummy 'sample_audio.raw':
# - For testing, any small file renamed to 'sample_audio.raw' could work just to send some bytes.
# - Alternatively, you can use audio editing software (like Audacity) to export a short recording
#   as raw PCM data (e.g., 16-bit, signed, little-endian, mono, 16000 Hz).
# - If the file is not found, this script generates its own dummy audio bytes.
# -------------------------

def send_wake_word():
    """
    Sends a wake-word detected event to the stream handler service.
    """
    url = f"{STREAM_HANDLER_URL}/event/wake-word-detected"
    payload = {"source_device_id": "test_script_gcs"}
    headers = {"Content-Type": "application/json"}
    print(f"Sending wake word event to {url} with payload: {payload}")
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        print(f"Wake word event response: Status Code {response.status_code}")
        try:
            print(f"Response body: {response.json()}")
        except json.JSONDecodeError:
            print(f"Response body (not JSON): {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"Error sending wake word event: {e}")

def send_audio_chunk(audio_bytes):
    """
    Sends an audio chunk to the stream handler service.
    """
    url = f"{STREAM_HANDLER_URL}/stream/audio/ingress"
    headers = {"Content-Type": "application/octet-stream"}
    print(f"Sending {len(audio_bytes)} bytes of audio data to {url}")
    try:
        response = requests.post(url, data=audio_bytes, headers=headers, timeout=15)
        print(f"Audio chunk response: Status Code {response.status_code}")
        try:
            print(f"Response body: {response.json()}")
        except json.JSONDecodeError:
            print(f"Response body (not JSON): {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"Error sending audio chunk: {e}")

if __name__ == "__main__":
    print("--- Starting GCS Upload Test Script ---")

    # 1. Send Wake Word Event
    send_wake_word()

    # Optional delay
    time.sleep(1)

    # 2. Load or Generate Audio Data
    audio_data = None
    try:
        with open(SAMPLE_AUDIO_FILE, "rb") as f:
            audio_data = f.read()
        print(f"Loaded {len(audio_data)} bytes from {SAMPLE_AUDIO_FILE}")
    except FileNotFoundError:
        print(f"Warning: {SAMPLE_AUDIO_FILE} not found. Generating and sending dummy audio data.")
        # Generate some dummy audio bytes (e.g., 1 second of 16kHz, 16-bit mono PCM = 32000 bytes)
        # A simple sequence of null bytes.
        num_samples = 16000  # 1 second at 16kHz
        bytes_per_sample = 2 # 16-bit
        audio_data = b'\x00\x00' * num_samples
        print(f"Generated {len(audio_data)} bytes of dummy audio data.")
    except Exception as e:
        print(f"Error loading audio file {SAMPLE_AUDIO_FILE}: {e}")
        print("Falling back to dummy audio data.")
        num_samples = 16000
        bytes_per_sample = 2
        audio_data = b'\x00\x00' * num_samples
        print(f"Generated {len(audio_data)} bytes of dummy audio data.")


    # 3. Send Audio Chunk
    if audio_data:
        send_audio_chunk(audio_data)
    else:
        print("No audio data to send. Skipping audio chunk.")

    print("--- GCS Upload Test Script Finished ---")
    print(f"Reminder: Monitor logs of 'kokoro-stream-handler-service' and 'kokoro-ai-agent-service'.")