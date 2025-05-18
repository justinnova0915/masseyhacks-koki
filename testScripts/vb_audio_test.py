import pyaudio
import time
import wave
import numpy as np
import resampy
from RealtimeTTS import TextToAudioStream, KokoroEngine

CHUNK_SIZE = 2048  # Increased to 2048 to reduce buffer switching frequency
CHANNELS = 2
FORMAT = pyaudio.paInt16
SAMPLE_RATES = [48000, 44100, 96000, 32000, 16000, 8000]

p = pyaudio.PyAudio()
vb_index = None
vb_channels = None
for i in range(p.get_device_count()):
    dev = p.get_device_info_by_index(i)
    if "VB-Audio" in dev['name'] and dev['maxInputChannels'] > 0:
        if dev['maxInputChannels'] == 2:
            vb_index = i
            vb_channels = 2
            print(f"Found VB-Audio device at index {i}: {dev['name']}")
            break
        else:
            vb_index = i
            vb_channels = dev['maxInputChannels']
            print(f"Found VB-Audio device at index {i}: {dev['name']}, using {vb_channels} channels")

if vb_index is None:
    print("VB-Audio Cable input device not found. Available devices:")
    for i in range(p.get_device_count()):
        dev = p.get_device_info_by_index(i)
        print(f"Device {i}: {dev['name']}, Input Channels: {dev['maxInputChannels']}, Output Channels: {dev['maxOutputChannels']}")
    p.terminate()
    exit(1)

# Get TTS sample rate from KokoroEngine
tts_engine = KokoroEngine()
_, _, tts_rate = tts_engine.get_stream_info()
print(f"TTS sample rate: {tts_rate} Hz")

# Try opening the stream with supported sample rates
stream = None
for rate in SAMPLE_RATES:
    try:
        print(f"Trying sample rate {rate} Hz with {vb_channels} channels...")
        stream = p.open(
            format=FORMAT,
            channels=vb_channels,
            rate=rate,
            input=True,
            input_device_index=vb_index,
            frames_per_buffer=CHUNK_SIZE
        )
        print(f"Success with sample rate {rate} Hz and {vb_channels} channels!")
        break
    except Exception as e:
        print(f"Failed with sample rate {rate} Hz: {e}")
        continue

if stream is None:
    print("Could not open stream with any sample rate.")
    p.terminate()
    exit(1)

# Initialize TTS
tts = TextToAudioStream(engine=tts_engine, muted=False)

# Capture audio to WAV
wav_file = wave.open("vb_audio_test.wav", "wb")
wav_file.setnchannels(CHANNELS)
wav_file.setsampwidth(p.get_sample_size(FORMAT))
wav_file.setframerate(tts_rate)  # Use TTS rate for WAV file

try:
    print("Starting capture for 20 seconds...")
    stream.start_stream()
    time.sleep(1.0)  # Ensure capture is active before playing

    # Start capturing in a loop
    total_captured = 0
    non_zero_chunks = 0
    capture_duration = 20  # seconds
    num_chunks = int(rate / CHUNK_SIZE * capture_duration)
    print("Starting capture loop...")

    # Start TTS playback asynchronously
    tts.feed("This is a test of VB-Audio capture. Let's make sure we can hear this loud and clear. Testing one two three.")
    tts.play_async()  # Non-blocking playback

    # Capture audio while TTS is playing
    for i in range(num_chunks):
        try:
            # Handle the return value of stream.read() correctly
            audio_data = stream.read(CHUNK_SIZE * vb_channels // CHANNELS, exception_on_overflow=False)
            total_captured += len(audio_data)  # Use len of audio_data (bytes)
            # Downmix if necessary with simple averaging
            if vb_channels > CHANNELS:
                audio_np = np.frombuffer(audio_data, dtype=np.int16)
                audio_np = audio_np.reshape(-1, vb_channels)
                # Simple average to avoid interpolation issues
                audio_np = audio_np[:, :2].mean(axis=1).astype(np.int16)
                audio_data = audio_np.tobytes()
            # Resample if capture rate differs from TTS rate
            if rate != tts_rate:
                audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32767.0
                audio_np = resampy.resample(audio_np, rate, tts_rate)
                audio_np = (audio_np * 32767).astype(np.int16)
                audio_data = audio_np.tobytes()
            # Check if chunk has non-zero data
            if any(byte != 0 and byte != 255 for byte in audio_data):
                non_zero_chunks += 1
            print(f"Chunk {i}: length: {len(audio_data)}, sample: {audio_data[:10]}, non-zero chunks: {non_zero_chunks}")
            wav_file.writeframes(audio_data)
        except IOError as e:
            print(f"IOError: {e}, continuing...")
        except Exception as e:
            print(f"Unexpected error: {e}, continuing...")
finally:
    stream.stop_stream()
    stream.close()
    wav_file.close()
    p.terminate()
    print(f"Saved captured audio to vb_audio_test.wav, total captured: {total_captured} bytes, non-zero chunks: {non_zero_chunks}")