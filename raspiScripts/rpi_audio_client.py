# raspiScripts/rpi_audio_client.py (Edited and improved by AI)

import pvporcupine
import pyaudio
import struct
import requests
import time
import json
import os
import threading
import subprocess
import uuid # For conversation_id (though RPi no longer generates it, agent sends it)
import wave
import tempfile
import math # Added for RMS calculation
from google.cloud import pubsub_v1
from google.cloud import storage
from urllib.parse import urlparse # For parsing GCS URI
from datetime import datetime # For unique filenames

# --- Configuration Constants ---
PORCUPINE_ACCESS_KEY = "r7MKNobK55WW30KP5GGVIVw22GfHPB1Pwy+O4FCI9qnNdvAX7JItcQ=="  # IMPORTANT: Replace with your Picovoice Access Key
# Ensure this path is correct for your Raspberry Pi deployment
PORCUPINE_KEYWORD_PATHS = ["hey-koki_en_raspberry-pi_v3_0_0.ppn"] # Adjusted path assuming script is in raspiScripts
PORCUPINE_MODEL_PATH = None  # Use default model

STREAM_HANDLER_URL = "http://34.28.171.172"
WAKE_WORD_EVENT_ENDPOINT = f"{STREAM_HANDLER_URL}/event/wake-word-detected"
AUDIO_INGRESS_ENDPOINT = f"{STREAM_HANDLER_URL}/stream/audio/ingress"

INPUT_AUDIO_DEVICE_INDEX = None  # User to determine on Pi, None for default
OUTPUT_AUDIO_DEVICE_INDEX = None # User to determine on Pi, None for default

# GCP Configuration (User must verify these values)
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "diesel-dominion-452723-h7") # Updated with actual Project ID
TTS_OUTPUT_SUBSCRIPTION_NAME = "kokoro-rpi-tts-sub" # Subscription for kokoro-tts-output-dev topic
PUBSUB_RPI_CONVO_CONTROL_SUBSCRIPTION = os.getenv("PUBSUB_RPI_CONVO_CONTROL_SUBSCRIPTION", "kokoro-rpi-convo-control-sub") # From kokoro_config.py
KOKORO_AUDIO_CHUNKS_GCS_BUCKET = os.getenv("KOKORO_AUDIO_CHUNKS_GCS_BUCKET", "kokoro-audio-chunks-diesel-dominion") # IMPORTANT: Verify GCS bucket name

# Conversation Control Message Types (expected from main agent)
CONVO_CMD_START_LISTENING_SPEECH = "START_LISTENING_SPEECH"
CONVO_CMD_START_LISTENING_WAKE_WORD = "START_LISTENING_WAKE_WORD"
CONVO_CMD_AGENT_SHUTDOWN = "AGENT_SHUTDOWN" # Optional: for graceful Pi shutdown

AUDIO_CHANNELS_INPUT = 1
AUDIO_RATE_INPUT = 16000  # Must match Porcupine's expected sample rate (typically 16000)
AUDIO_FORMAT_INPUT = pyaudio.paInt16
# FRAMES_PER_BUFFER_INPUT will be set by porcupine.frame_length

STREAM_TO_CLOUD_DURATION_SECONDS = 10 # Max duration for STT streaming session
DEVICE_ID = "raspberry_pi_001" # Unique identifier for this device

PLAYBACK_CHANNELS = 1      # Assuming mono TTS output for simplicity
PLAYBACK_RATE = 48000      # Match TTS output rate from real_time_ai_agent.py (kc.PLAYBACK_RATE)
PLAYBACK_FORMAT = pyaudio.paInt16
FRAMES_PER_BUFFER_OUTPUT = 1024 # Typical for playback

# Pi Client States
PI_STATE_LISTENING_WAKE_WORD = "LISTENING_FOR_WAKE_WORD"
PI_STATE_STREAMING_STT = "STREAMING_AUDIO_FOR_STT" # Actively sending user's speech
PI_STATE_WAITING_FOR_COMMAND = "WAITING_FOR_COMMAND" # Waiting for instruction from main agent
PI_STATE_AWAITING_USER_RESPONSE = "AWAITING_USER_RESPONSE" # New state for multi-turn

# Will be initialized after Porcupine
FRAMES_PER_BUFFER_INPUT = None

porcupine = None
pa_input_instance = None # Replaces 'pa'
pa_output_instance = None # New instance for output
pa_input_stream = None
pa_output_stream = None
gcs_client = None
tts_pubsub_subscriber_client = None # Renamed for clarity
convo_control_pubsub_subscriber_client = None # New subscriber for control messages
tts_listener_future = None
convo_control_listener_future = None # Future for the new listener
stop_event = threading.Event() # General stop event for all threads and main loop
playback_lock = threading.Lock() # Global lock for audio playback
state_lock = threading.Lock()    # Lock for current_pi_state
current_pi_state = PI_STATE_LISTENING_WAKE_WORD # Initial state
rpi_current_conversation_id = None # For matching TTS messages to current interaction
last_activity_time = time.time() # For timeouts in certain states
wake_word_audio_buffer = []
turn_initial_audio_buffer = [] # Buffer for the start of a conversational turn
turn_pre_roll_buffer = [] # Buffer for pre-roll audio for a turn
is_buffering_wake_audio = threading.Event()
buffering_start_time = 0  # To track duration of wake word audio buffering
BUFFER_WAKE_AUDIO_DURATION_SECONDS = 1.5 # Buffer this much audio after wake word

# Timeout for WAITING_FOR_COMMAND state before reverting to WAKE_WORD
COMMAND_TIMEOUT_SECONDS = 25 # e.g., STT_TIMEOUT (15s) + some buffer for processing/network
USER_TURN_SILENCE_TIMEOUT_SECONDS = 7 # Timeout for user to speak in a multi-turn convo
TURN_AUDIO_PRE_ROLL_FRAMES = 3 # Number of frames for turn audio pre-roll

# VAD (Voice Activity Detection) Configuration
SILENCE_THRESHOLD_RMS = 350  # RMS value below which audio is considered silent. This needs tuning. Changed from 600.
# VAD constants for PI_STATE_STREAMING_STT
MAX_INITIAL_SILENT_FRAMES_STT = 150 # Approx 4.8s (150 * 32ms). Timeout if no speech starts in STT state.
MIN_SPEECH_FRAMES_FOR_VALID_UTTERANCE_STT = 30 # Min actual speech frames for a valid utterance before ending capture due to silence. Increased from 20.
MAX_CONSECUTIVE_SILENT_FRAMES_STT = 125 # Number of consecutive silent frames after speech to trigger end of speech (e.g., 125 * 32ms approx 4s). Increased from 75.
MIN_FRAMES_TO_CONFIRM_SPEECH_START_STT = 1 # Number of consecutive frames above RMS to confirm speech start. Changed from 5.
WAKE_SOUND_DURATION_SECONDS = 1.5 # Estimated duration of the wake_sound_file. Adjust if your ring.wav is shorter/longer.

# For saving captured audio
LOCAL_AUDIO_SAVE_PATH = "captured_audio" # Subdirectory to save audio
if not os.path.exists(LOCAL_AUDIO_SAVE_PATH):
    os.makedirs(LOCAL_AUDIO_SAVE_PATH)
current_utterance_frames_for_saving = [] # Holds all frames for current STT session


# Batching configuration
FRAMES_PER_BATCH = 15  # Approx 0.5 seconds of audio (15 frames * 0.032s/frame = 0.48s)

# Helper for periodic status (to avoid spamming logs)
last_status_print_time = 0
status_print_interval = 5 # seconds, adjust as needed

def print_periodic_status(message):
    global last_status_print_time, current_pi_state # Added current_pi_state
    current_time = time.time()
    if current_time - last_status_print_time > status_print_interval:
        print(f"[{time.strftime('%H:%M:%S')}] PI_STATE: {current_pi_state} - {message}")
        last_status_print_time = current_time

def save_current_utterance_to_wav(frames_list, filename_prefix="stt_capture"):
    """Saves the collected audio frames to a WAV file."""
    global AUDIO_RATE_INPUT, AUDIO_CHANNELS_INPUT, AUDIO_FORMAT_INPUT, pa_input_instance
    if not frames_list:
        print("[SAVE AUDIO] No frames to save for current utterance.")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Use conversation ID in filename if available, otherwise a short UUID
    convo_id_part = rpi_current_conversation_id.split('-')[0] if rpi_current_conversation_id else str(uuid.uuid4())[:8]
    filename = f"{filename_prefix}_{timestamp}_{convo_id_part}.wav"
    filepath = os.path.join(LOCAL_AUDIO_SAVE_PATH, filename)

    try:
        wf = wave.open(filepath, 'wb')
        wf.setnchannels(AUDIO_CHANNELS_INPUT)
        if pa_input_instance: # Ensure PyAudio instance is available
            wf.setsampwidth(pa_input_instance.get_sample_size(AUDIO_FORMAT_INPUT))
        else: # Fallback if pa_input_instance is somehow None (should not happen if initialized)
            wf.setsampwidth(2) # Assuming 16-bit audio (2 bytes)
            print("[SAVE AUDIO] WARN: pa_input_instance not available for getsampwidth(). Assuming 2 bytes.")
        wf.setframerate(AUDIO_RATE_INPUT)
        wf.writeframes(b''.join(frames_list))
        wf.close()
        print(f"[SAVE AUDIO] Successfully saved utterance to {filepath}")
    except Exception as e:
        print(f"[SAVE AUDIO] Error saving utterance to {filepath}: {e}")


def initialize_audio_services():
    """Initializes Porcupine, PyAudio, and Pub/Sub clients."""
    global porcupine, pa_input_instance, pa_output_instance, pa_input_stream, pa_output_stream, FRAMES_PER_BUFFER_INPUT, AUDIO_RATE_INPUT
    global gcs_client, tts_pubsub_subscriber_client, convo_control_pubsub_subscriber_client

    try:
        # Initialize Google Cloud clients
        credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if credentials_path:
            print(f"Using credentials from GOOGLE_APPLICATION_CREDENTIALS: {credentials_path}")
            try:
                gcs_client = storage.Client.from_service_account_json(credentials_path)
                print("Google Cloud Storage client initialized with explicit credentials.")
            except Exception as e:
                print(f"Failed to initialize Google Cloud Storage client with explicit credentials: {e}")
                return False

            try:
                # TTS Output Subscriber
                tts_pubsub_subscriber_client = pubsub_v1.SubscriberClient.from_service_account_json(credentials_path)
                print("Google Cloud Pub/Sub client for TTS initialized with explicit credentials.")
                # Conversation Control Subscriber
                convo_control_pubsub_subscriber_client = pubsub_v1.SubscriberClient.from_service_account_json(credentials_path)
                print("Google Cloud Pub/Sub client for Convo Control initialized with explicit credentials.")
            except Exception as e:
                print(f"Failed to initialize Google Cloud Pub/Sub clients with explicit credentials: {e}")
                return False
        else:
            print("GOOGLE_APPLICATION_CREDENTIALS not set. Attempting to initialize clients with default credentials.")
            try:
                gcs_client = storage.Client()
                print("Google Cloud Storage client initialized with default credentials.")
            except Exception as e:
                print(f"Failed to initialize Google Cloud Storage client with default credentials: {e}")
                return False

            try:
                # TTS Output Subscriber
                tts_pubsub_subscriber_client = pubsub_v1.SubscriberClient()
                print("Google Cloud Pub/Sub client for TTS initialized with default credentials.")
                # Conversation Control Subscriber
                convo_control_pubsub_subscriber_client = pubsub_v1.SubscriberClient()
                print("Google Cloud Pub/Sub client for Convo Control initialized with default credentials.")
            except Exception as e:
                print(f"Failed to initialize Google Cloud Pub/Sub clients with default credentials: {e}")
                return False

        porcupine = pvporcupine.create(
            access_key=PORCUPINE_ACCESS_KEY,
            keyword_paths=PORCUPINE_KEYWORD_PATHS,
            model_path=PORCUPINE_MODEL_PATH
        )
        FRAMES_PER_BUFFER_INPUT = porcupine.frame_length
        AUDIO_RATE_INPUT = porcupine.sample_rate # Ensure PyAudio uses the same rate as Porcupine
        print(f"Porcupine initialized. Frame length: {FRAMES_PER_BUFFER_INPUT}, Sample rate: {AUDIO_RATE_INPUT}")

        # pa = pyaudio.PyAudio() # Replaced by separate instances below

        # --- Input Stream ---
        print("Initializing PyAudio for INPUT...")
        pa_input_instance = pyaudio.PyAudio() # Instance for input
        print(f"DEBUG: Attempting input pa.open() with:")
        print(f"DEBUG:   rate={AUDIO_RATE_INPUT}")
        print(f"DEBUG:   channels={AUDIO_CHANNELS_INPUT}")
        print(f"DEBUG:   format={AUDIO_FORMAT_INPUT}")
        print(f"DEBUG:   input_device_index={INPUT_AUDIO_DEVICE_INDEX}")
        print(f"DEBUG:   frames_per_buffer={FRAMES_PER_BUFFER_INPUT}")
        pa_input_stream = pa_input_instance.open(
            rate=AUDIO_RATE_INPUT,
            channels=AUDIO_CHANNELS_INPUT,
            format=AUDIO_FORMAT_INPUT,
            input=True,
            frames_per_buffer=FRAMES_PER_BUFFER_INPUT,
            input_device_index=INPUT_AUDIO_DEVICE_INDEX
        )
        print(f"PyAudio input stream opened on device index: {INPUT_AUDIO_DEVICE_INDEX if INPUT_AUDIO_DEVICE_INDEX is not None else 'default'}")

        # --- Output Stream ---
        print("Initializing PyAudio for OUTPUT...")
        pa_output_instance = pyaudio.PyAudio() # Instance for output
        current_output_device_index = OUTPUT_AUDIO_DEVICE_INDEX
        print(f"DEBUG: Attempting output pa.open() with:")
        print(f"DEBUG:   rate={PLAYBACK_RATE}")
        print(f"DEBUG:   channels={PLAYBACK_CHANNELS}")
        print(f"DEBUG:   format={PLAYBACK_FORMAT}")
        print(f"DEBUG:   output_device_index={current_output_device_index}")
        print(f"DEBUG:   frames_per_buffer={FRAMES_PER_BUFFER_OUTPUT}")
        pa_output_stream = pa_output_instance.open(
            rate=PLAYBACK_RATE,
            channels=PLAYBACK_CHANNELS,
            format=PLAYBACK_FORMAT,
            output=True,
            frames_per_buffer=FRAMES_PER_BUFFER_OUTPUT,
            output_device_index=current_output_device_index
        )
        print(f"PyAudio output stream opened on device index: {current_output_device_index if current_output_device_index is not None else 'default'}")

        return True

    except pvporcupine.PorcupineError as e:
        print(f"Porcupine initialization error: {e}")
        print("Please ensure your PORCUPINE_ACCESS_KEY is correct and keyword/model files are accessible.")
    except IOError as e:
        print(f"PyAudio stream error: {e}")
        print("Please check your audio device indices and ensure microphones/speakers are connected.")
    except Exception as e:
        print(f"An unexpected error occurred during initialization: {e}")
    return False

# --- Helper Functions ---
def calculate_rms(frame_data_shorts):
    """Calculates the RMS of a frame of audio data (list of short integers)."""
    if not frame_data_shorts:
        return 0
    sum_squares = sum(sample ** 2 for sample in frame_data_shorts)
    mean_squares = sum_squares / len(frame_data_shorts)
    rms = math.sqrt(mean_squares)
    return rms

def signal_wake_word_detected():
    """Sends a signal to the cloud service when a wake word is detected."""
    payload = {
        "device_id": DEVICE_ID,
        "timestamp": time.time()
    }
    try:
        response = requests.post(WAKE_WORD_EVENT_ENDPOINT, json=payload, timeout=5)
        response.raise_for_status()
        print(f"Successfully signaled wake word detection to {WAKE_WORD_EVENT_ENDPOINT}")
    except requests.exceptions.RequestException as e:
        print(f"Error signaling wake word: {e}")

def stream_audio_chunk_to_cloud(audio_chunk_bytes):
    """Sends a chunk of audio data to the cloud service."""
    headers = {
        "Content-Type": "application/octet-stream",
        "X-Device-ID": DEVICE_ID,
        "X-Timestamp": str(time.time()),
        "X-Audio-Rate": str(AUDIO_RATE_INPUT),
        "X-Audio-Channels": str(AUDIO_CHANNELS_INPUT),
        "X-Audio-Format": "paInt16" # Or derive from AUDIO_FORMAT_INPUT
    }
    try:
        # Increased timeout: 5s for connect, 10s for read
        response = requests.post(AUDIO_INGRESS_ENDPOINT, data=audio_chunk_bytes, headers=headers, timeout=(5, 10))
        response.raise_for_status()
        # print(f"Successfully streamed audio chunk. Server response: {response.status_code}") # Optional: for debugging
    except requests.exceptions.RequestException as e:
        print(f"Error streaming audio chunk: {e}")

def play_audio_chunk_on_pi(audio_bytes):
    """Plays a chunk of audio bytes on the Raspberry Pi's output device."""
    global pa_output_stream
    if pa_output_stream:
        try:
            pa_output_stream.write(audio_bytes)
            # print(f"Played {len(audio_bytes)} bytes of audio.") # Optional: for debugging
        except IOError as e:
            print(f"Error playing audio chunk: {e}")
        except Exception as e:
            print(f"Unexpected error during audio playback: {e}")
    else:
        print("Output audio stream not available for playback.")

def play_wav_file_on_pi(wav_file_path):
    """Plays a WAV audio file on the Raspberry Pi's output device."""
    global pa_output_stream, pa_output_instance, playback_lock # Use pa_output_instance
    
    if not playback_lock.acquire(blocking=False):
        print("[WAV Playback] Could not acquire playback lock, another playback is in progress. Skipping.")
        # Optionally, queue this request or handle it differently
        return False

    try:
        if not pa_output_stream:
            print("[WAV Playback] Output audio stream not available.")
            return False
        if not pa_output_instance: # Check for the correct instance
            print("[WAV Playback] PyAudio instance (pa) not available.")
            return False

        wf = None
        try: # Inner try for wave file operations
            wf = wave.open(wav_file_path, 'rb')
            
            print(f"[WAV Playback] File Info: {wf.getnchannels()}ch, {wf.getframerate()}Hz, {wf.getsampwidth()}bytes/sample")
            print(f"[WAV Playback] Stream Info (Initial): {PLAYBACK_CHANNELS}ch, {PLAYBACK_RATE}Hz, Format: {PLAYBACK_FORMAT}")

            if wf.getframerate() != PLAYBACK_RATE or wf.getnchannels() != PLAYBACK_CHANNELS:
                print(f"[WAV Playback] ERROR: WAV file parameters ({wf.getframerate()} Hz, {wf.getnchannels()} ch) "
                      f"do not match required stream parameters ({PLAYBACK_RATE} Hz, {PLAYBACK_CHANNELS} ch). "
                      "Skipping playback of this file to prevent stream corruption.")
                # wf.close() will be handled by the finally block
                return False

            data = wf.readframes(FRAMES_PER_BUFFER_OUTPUT)
            print(f"[WAV Playback] Playing audio from {wav_file_path}...")
            while data:
                if not pa_output_stream.is_active():
                    print("[WAV Playback] Output stream is not active. Attempting to restart.")
                    try:
                        pa_output_stream.start_stream()
                        print("[WAV Playback] Output stream restarted.")
                    except IOError as e_start:
                        print(f"[WAV Playback] Failed to restart output stream: {e_start}. Aborting playback of this file.")
                        break
                pa_output_stream.write(data)
                data = wf.readframes(FRAMES_PER_BUFFER_OUTPUT)
            
            if pa_output_stream.is_active():
                print("[WAV Playback] Waiting for stream to finish draining...")
            
            print(f"[WAV Playback] Finished playing {wav_file_path}.")
            return True

        except FileNotFoundError:
            print(f"[WAV Playback] WAV file not found: {wav_file_path}")
            return False
        except wave.Error as e:
            print(f"[WAV Playback] Error reading WAV file {wav_file_path}: {e}")
            return False
        except IOError as e: # This can include PyAudio errors during write or start_stream
            print(f"[WAV Playback] PyAudio IOError during WAV playback: {e}")
            return False
        except Exception as e: # Catch any other unexpected error during playback logic
            print(f"[WAV Playback] Unexpected error during WAV playback logic: {e}")
            return False
        finally: # Finally for the inner try (wave file operations)
            if wf:
                wf.close()
                print(f"[WAV Playback] Closed WAV file: {wav_file_path}")
    finally: # Finally for the outer try (lock management)
        playback_lock.release()
        print("[WAV Playback] Playback lock released.")

def tts_message_callback(message: pubsub_v1.subscriber.message.Message) -> None:
    """Callback for Pub/Sub messages containing TTS audio GCS URI."""
    global gcs_client, current_pi_state, last_activity_time, turn_initial_audio_buffer, turn_pre_roll_buffer, rpi_current_conversation_id
    
    print(f"[TTS Callback] ENTERED. Message ID: {message.message_id}, Publish Time: {message.publish_time}")
    print(f"[TTS Callback] Message Attributes: {message.attributes}")
    
    try:
        print(f"[TTS Callback] Raw message data (first 100 bytes): {message.data[:100]}")
    except Exception as e_log_raw:
        print(f"[TTS Callback] Error logging raw message data: {e_log_raw}")

    try:
        data_str = message.data.decode("utf-8")
        print(f"[TTS Callback] Decoded data string: {data_str}")
        message_payload = json.loads(data_str)
        print(f"[TTS Callback] Parsed TTS Message Payload: {message_payload}")

        message_metadata = message_payload.get("metadata", {})
        message_conversation_id = message_metadata.get("conversation_id")
        print(f"[TTS Callback] RPi current_conversation_id: {rpi_current_conversation_id}, Message conversation_id: {message_conversation_id}")

        if rpi_current_conversation_id is None or message_conversation_id != rpi_current_conversation_id:
            log_reason = "RPi not in active conversation" if rpi_current_conversation_id is None else "Conversation ID mismatch"
            print(f"[TTS Callback] {log_reason}. RPi ID: {rpi_current_conversation_id}, Msg ID: {message_conversation_id}. Ignoring and ACKing.")
            message.ack()
            return

        print(f"[TTS Accepted] IDs matched ({rpi_current_conversation_id}). Proceeding with GCS URI: {message_payload.get('data_reference')}")
        data_reference_type = message_payload.get("data_reference_type")
        gcs_uri = message_payload.get("data_reference")

        if data_reference_type == "gcs_uri" and gcs_uri:
            if not gcs_client:
                print("[TTS Callback] ERROR: GCS client not initialized.")
                message.nack() # Nack if GCS client is missing, allowing retry
                return

            parsed_uri = urlparse(gcs_uri)
            if parsed_uri.scheme != "gs":
                print(f"[TTS Callback] ERROR: Invalid GCS URI scheme: {gcs_uri}")
                message.ack() # Invalid URI, ack to prevent reprocessing
                return

            bucket_name = parsed_uri.netloc
            blob_name = parsed_uri.path.lstrip('/')

            if not bucket_name or not blob_name:
                print(f"[TTS Callback] ERROR: Could not parse bucket/blob from GCS URI: {gcs_uri}")
                message.ack() # Malformed URI, ack
                return

            temp_file_path = "" # Initialize to ensure it's defined for finally
            try:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_audio_file:
                    temp_file_path = tmp_audio_file.name
                
                bucket = gcs_client.bucket(bucket_name)
                blob = bucket.blob(blob_name)
                blob.download_to_filename(temp_file_path)
                print(f"[TTS Callback] Downloaded to {temp_file_path}.")

                playback_successful = play_wav_file_on_pi(temp_file_path)

                if playback_successful:
                    with state_lock:
                        if current_pi_state != PI_STATE_LISTENING_WAKE_WORD: # Only transition if not already back to wake word
                            current_pi_state = PI_STATE_AWAITING_USER_RESPONSE
                            last_activity_time = time.time()
                            turn_initial_audio_buffer.clear()
                            turn_pre_roll_buffer.clear()
                            print(f"[TTS Callback] Playback successful. Transitioning to {PI_STATE_AWAITING_USER_RESPONSE}. RPi Convo ID: {rpi_current_conversation_id}")
                        else:
                            print(f"[TTS Callback] Playback successful, but state is already {current_pi_state}. No transition. RPi Convo ID: {rpi_current_conversation_id}")
                    message.ack() # Successfully processed
                else:
                    print(f"[TTS Callback] Playback of {temp_file_path} failed or was skipped. Nacking message to allow retry.")
                    message.nack()
            except Exception as e_download_play:
                print(f"[TTS Callback] ERROR downloading/playing TTS: {e_download_play}")
                message.nack() # Nack to allow retry for transient errors like download issues
            finally:
                if temp_file_path and os.path.exists(temp_file_path):
                    try:
                        os.remove(temp_file_path)
                    except Exception as e_rem:
                        print(f"[TTS Callback] WARN: Error removing temp TTS file {temp_file_path}: {e_rem}")
        else:
            print(f"[TTS Callback] WARN: Unknown TTS message format or missing GCS URI. Payload: {message_payload}")
            message.ack() # Ack unknown formats
        
    except json.JSONDecodeError as e_json:
        print(f"[TTS Callback] ERROR: Failed to decode JSON. Data: '{data_str if 'data_str' in locals() else message.data[:100]}': {e_json}")
        message.ack() # Ack malformed message
    except Exception as e_main:
        print(f"[TTS Callback] CRITICAL error in callback: {e_main}")
        try:
            message.nack() # Nack for other critical errors to allow retry
        except Exception as e_nack_critical:
            print(f"[TTS Callback] Failed to NACK message ID: {message.message_id} during critical error handling: {e_nack_critical}")
    finally:
        # This finally block is now primarily for logging exit, ack/nack should be handled above.
        print(f"[TTS Callback] EXITED. Message ID: {message.message_id}")

# --- Conversation Control Logic ---
def conversation_control_callback(message: pubsub_v1.subscriber.message.Message) -> None:
    """Callback for Pub/Sub messages containing conversation control commands."""
    global current_pi_state, last_activity_time, is_buffering_wake_audio, rpi_current_conversation_id
    
    print(f"[Convo Control Callback] ENTERED. Message ID: {message.message_id}, Publish Time: {message.publish_time}")
    try:
        data_str = message.data.decode("utf-8")
        print(f"[Convo Control Callback] Decoded data string: {data_str}")
        control_message = json.loads(data_str)
        command = control_message.get("command")
        payload = control_message.get("payload", {}) # Get payload, default to empty dict if not present
        new_conversation_id = payload.get("conversation_id") # Extract new conversation_id from payload
        print(f"[Convo Control Callback] Received command: {command}, Full payload: {control_message}")

        if command == CONVO_CMD_START_LISTENING_SPEECH:
            print("[Convo Control Callback] Command: START_LISTENING_SPEECH")
            # Ensure we are not already in this state or streaming
            if current_pi_state != PI_STATE_STREAMING_STT:
                with state_lock: # Protect access to global rpi_current_conversation_id
                    current_pi_state = PI_STATE_STREAMING_STT
                    if new_conversation_id: # If a new ID is provided by the agent
                        rpi_current_conversation_id = new_conversation_id
                        print(f"[Convo Control Callback] RPi Conversation ID SET to: {rpi_current_conversation_id} by agent command.")
                    elif rpi_current_conversation_id is None: # If no ID from agent and RPi doesn't have one
                        rpi_current_conversation_id = str(uuid.uuid4()) # Generate a new one
                        print(f"[Convo Control Callback] RPi Conversation ID GENERATED: {rpi_current_conversation_id} (no ID from agent).")
                    # If RPi already has an ID and agent doesn't send one, keep the existing RPi ID.
                last_activity_time = time.time() # Reset activity timer for this new phase
                print(f"[Convo Control Callback] State changed to: {current_pi_state}. Current RPi Convo ID: {rpi_current_conversation_id}")
                if is_buffering_wake_audio.is_set():
                    is_buffering_wake_audio.clear()
                    print("[Convo Control Callback] Cleared wake audio buffering flag due to START_LISTENING_SPEECH command.")
            else:
                print(f"[Convo Control Callback] Received START_LISTENING_SPEECH but already in {current_pi_state} or similar. Command noted.")
                if new_conversation_id: # Still update conversation ID if provided
                     with state_lock:
                        rpi_current_conversation_id = new_conversation_id
                        print(f"[Convo Control Callback] RPi Conversation ID UPDATED to: {rpi_current_conversation_id} by agent command (already in STT).")
                if is_buffering_wake_audio.is_set(): # Still ensure buffering stops
                    is_buffering_wake_audio.clear()
                    print("[Convo Control Callback] Cleared wake audio buffering flag.")
        elif command == CONVO_CMD_START_LISTENING_WAKE_WORD:
            print("[Convo Control Callback] Command: START_LISTENING_WAKE_WORD")
            with state_lock:
                current_pi_state = PI_STATE_LISTENING_WAKE_WORD
                rpi_current_conversation_id = None # Clear conversation ID when returning to wake word
                print(f"[Convo Control Callback] RPi Conversation ID CLEARED.")
            print(f"[Convo Control Callback] State changed to: {current_pi_state}")
        elif command == CONVO_CMD_AGENT_SHUTDOWN: # Optional: for graceful Pi shutdown
            print("[Convo Control Callback] Command: AGENT_SHUTDOWN. Signaling stop to all listeners.")
            stop_event.set() # Use the global stop_event
        else:
            print(f"[Convo Control Callback] Unknown command received: {command}")
        
        message.ack() # Ack all control messages once processed or identified as unknown
        print(f"[Convo Control Callback] ACKed message ID: {message.message_id}")

    except json.JSONDecodeError as e_json:
        print(f"[Convo Control Callback] Failed to decode JSON: {e_json}. Data: '{data_str if 'data_str' in locals() else message.data[:100]}'")
        message.ack() # Ack malformed message to prevent retry
    except Exception as e_main:
        print(f"[Convo Control Callback] CRITICAL error: {e_main}")
        try:
            message.nack() # Nack other errors to allow retry
        except Exception as e_nack:
            print(f"[Convo Control Callback] Failed to NACK during critical error: {e_nack}")
    print(f"[Convo Control Callback] EXITED. Message ID: {message.message_id}")


def start_listener_thread(subscriber_client, subscription_name, callback_func, listener_name_log_prefix, future_setter_callback):
    global stop_event
    
    print(f"[{listener_name_log_prefix} Listener] Attempting to start...")
    subscription_path = subscriber_client.subscription_path(GCP_PROJECT_ID, subscription_name)
    
    local_listener_future = None # Define here for access in the finally block of listen_loop

    def listen_loop():
        nonlocal local_listener_future # Allow modification of the outer scope's future
        try:
            # Verify subscription exists before trying to pull messages
            try: # Verify subscription exists
                subscriber_client.get_subscription(subscription=subscription_path)
                print(f"[{listener_name_log_prefix} Listener] Subscription {subscription_path} verified.")
            except Exception as e_get_sub:
                print(f"[{listener_name_log_prefix} Listener] Failed to verify subscription {subscription_path}: {e_get_sub}")
                print(f"[{listener_name_log_prefix} Listener] Please ensure the subscription exists and the client has permissions.")
                return # Exit thread if subscription cannot be verified

            # The subscriber is non-blocking, so we wrap it in a loop that respects stop_event
            print(f"[{listener_name_log_prefix} Listener] Starting listener for {subscription_path}...")
            local_listener_future = subscriber_client.subscribe(subscription_path, callback=callback_func)
            future_setter_callback(local_listener_future) # Pass the future back to the main thread
            print(f"[{listener_name_log_prefix} Listener] Subscription to {subscription_path} is active. Future: {local_listener_future}")

            # Keep the thread alive and check stop_event, as .subscribe() is non-blocking
            while not stop_event.is_set():
                time.sleep(1) # Check stop_event periodically
                if not local_listener_future.running():
                    print(f"[{listener_name_log_prefix} Listener] Future {local_listener_future} is no longer running. Attempting to restart.")
                    # Attempt to restart the subscription
                    try:
                        local_listener_future.cancel() # Cancel previous one if it exists and isn't running properly
                        local_listener_future.result(timeout=5) # Wait for cancellation
                    except: pass # Ignore errors during cancel/result if it was already done or failed
                    
                    local_listener_future = subscriber_client.subscribe(subscription_path, callback=callback_func)
                    future_setter_callback(local_listener_future)
                    print(f"[{listener_name_log_prefix} Listener] Re-subscribed. New future: {local_listener_future}")


            print(f"[{listener_name_log_prefix} Listener] Stop event received. Cancelling future {local_listener_future}...")
            if local_listener_future and local_listener_future.running():
                local_listener_future.cancel()
                try:
                    local_listener_future.result(timeout=5) # Wait for cancellation to complete
                    print(f"[{listener_name_log_prefix} Listener] Future {local_listener_future} cancelled successfully.")
                except TimeoutError:
                    print(f"[{listener_name_log_prefix} Listener] Timeout waiting for future {local_listener_future} to cancel.")
                except Exception as e_cancel:
                    print(f"[{listener_name_log_prefix} Listener] Error cancelling future {local_listener_future}: {e_cancel}")
        except Exception as e:
            print(f"[{listener_name_log_prefix} Listener] Thread encountered an error: {e}")
        finally:
            if local_listener_future and local_listener_future.running(): # Ensure it's cancelled if loop exited for other reasons
                print(f"[{listener_name_log_prefix} Listener] Ensuring future {local_listener_future} is cancelled in finally block.")
                local_listener_future.cancel()
                try:
                    local_listener_future.result(timeout=1)
                except: pass # Ignore errors on this final cleanup attempt
            print(f"[{listener_name_log_prefix} Listener] Thread finished.")

    thread = threading.Thread(target=listen_loop, name=f"{listener_name_log_prefix}Thread")
    thread.daemon = True # Allow main program to exit even if this thread is running
    thread.start()
    print(f"[{listener_name_log_prefix} Listener] Thread started.")


def set_tts_future(future):
    global tts_listener_future
    tts_listener_future = future

def set_convo_control_future(future):
    global convo_control_listener_future
    convo_control_listener_future = future

# --- Main Application Logic ---
def main_loop():
    global porcupine, pa_input_stream, current_pi_state, last_activity_time, stop_event, rpi_current_conversation_id, current_utterance_frames_for_saving
    global wake_word_audio_buffer, turn_initial_audio_buffer, is_buffering_wake_audio, buffering_start_time
    global FRAMES_PER_BUFFER_INPUT, AUDIO_RATE_INPUT, AUDIO_FORMAT_INPUT, AUDIO_CHANNELS_INPUT
    global live_audio_batch_buffer # Used in PI_STATE_STREAMING_STT
    live_audio_batch_buffer = [] # Ensure it's initialized

    # Variables for VAD in PI_STATE_STREAMING_STT
    sent_wake_word_buffer = False # Flag to ensure wake word buffer is sent only once
    sent_turn_buffer = False # Flag to ensure turn buffer is sent only once
    
    # For STT streaming loop
    frames_processed_in_vad_loop = 0 # To track frames for VAD logic
    was_streaming_stt = False # To manage post-loop send

    print("Starting main loop. Listening for wake word...")
    try:
        while not stop_event.is_set():
            if current_pi_state == PI_STATE_LISTENING_WAKE_WORD:
                print_periodic_status("Listening for wake word...")
                was_streaming_stt = False # Reset when back to wake word listening
                if rpi_current_conversation_id is not None: # Should have been cleared by convo_control_callback or timeout
                    print(f"WARN: In WAKE_WORD state but rpi_current_conversation_id is {rpi_current_conversation_id}. Clearing.")
                    rpi_current_conversation_id = None
                try:
                    if not pa_input_stream or not pa_input_stream.is_active():
                        print_periodic_status("Input stream inactive/not available. Attempting to reopen...")
                        if pa_input_stream: pa_input_stream.close()
                        pa_input_stream = pa_input_instance.open(
                            rate=AUDIO_RATE_INPUT, channels=AUDIO_CHANNELS_INPUT,
                            format=AUDIO_FORMAT_INPUT, input=True,
                            frames_per_buffer=FRAMES_PER_BUFFER_INPUT,
                            input_device_index=INPUT_AUDIO_DEVICE_INDEX)
                        print("Input stream reopened.")
                        time.sleep(0.1) # Give stream time to stabilize
                        continue # Retry reading in the next loop iteration

                    pcm_bytes = pa_input_stream.read(FRAMES_PER_BUFFER_INPUT, exception_on_overflow=False)
                    pcm_shorts = struct.unpack_from("h" * FRAMES_PER_BUFFER_INPUT, pcm_bytes)
                    keyword_index = porcupine.process(pcm_shorts)

                    if keyword_index >= 0:
                        # Wake word detected
                        print(f"\nWake word '{PORCUPINE_KEYWORD_PATHS[keyword_index]}' detected!")
                        # Play wake word sound using aplay (standalone)
                        print("Attempting to play wake word sound via aplay...")
                        wake_sound_file = "ring.wav"  # Path relative to project root
                        if os.path.exists(wake_sound_file):
                            try:
                                process = subprocess.Popen(
                                    ['aplay', wake_sound_file],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL
                                )
                                print(f"aplay process initiated for {wake_sound_file} (PID: {process.pid}).")
                                print(f"Delaying for {WAKE_SOUND_DURATION_SECONDS}s to allow wake sound to play before VAD processing starts for user speech...")
                                time.sleep(WAKE_SOUND_DURATION_SECONDS) # Allow wake sound to play
                                print("Wake sound delay finished. Proceeding to listen for user speech.")
                            except FileNotFoundError:
                                print("ERROR: 'aplay' command not found. Please ensure 'alsa-utils' is installed and 'aplay' is in your system's PATH.")
                            except Exception as e_aplay:
                                print(f"ERROR: Failed to start aplay for wake sound {wake_sound_file}: {e_aplay}")
                        else:
                            print(f"ERROR: Wake sound file not found: {wake_sound_file}")
                        
                        signal_wake_word_detected() # Inform the cloud
                        
                        with state_lock: # Protect state and conversation ID update
                            current_pi_state = PI_STATE_STREAMING_STT # Transition to streaming
                            rpi_current_conversation_id = str(uuid.uuid4()) # Generate new conversation ID for this interaction
                            print(f"RPi Conversation ID GENERATED on wake word: {rpi_current_conversation_id}")
                        
                        last_activity_time = time.time() # Reset activity timer
                        is_buffering_wake_audio.set() # Start buffering audio immediately after wake word
                        buffering_start_time = time.time()
                        wake_word_audio_buffer = [] # Clear any old buffer
                        turn_initial_audio_buffer = [] # Clear turn buffer as well
                        print(f"[DEBUG SAVE AUDIO] Clearing current_utterance_frames_for_saving (wake word flow). Length before clear: {len(current_utterance_frames_for_saving)}")
                        current_utterance_frames_for_saving.clear() # Clear for new STT session
                        print(f"[DEBUG SAVE AUDIO] Length after clear (wake word flow): {len(current_utterance_frames_for_saving)}")
                        sent_wake_word_buffer = False # Reset for the new session
                        sent_turn_buffer = False # Reset for the new session
                        live_audio_batch_buffer = [] # Clear batch buffer for new STT session
                        print(f"Transitioned to {current_pi_state}. Buffering wake audio...")

                except pvporcupine.PorcupineActivationThrottledError:
                    print_periodic_status("Porcupine activation throttled. Will retry.")
                    time.sleep(0.1) # Brief pause before retrying
                except pvporcupine.PorcupineActivationRefusedError:
                    print_periodic_status("Porcupine activation refused. Check access key or license.")
                    stop_event.set() # Critical error, stop.
                    break
                except pvporcupine.PorcupineError as e_p:
                    print(f"Porcupine error: {e_p}")
                    stop_event.set()
                    break
                except IOError as e_io_wake:
                    print(f"\nIOError during wake word listening: {e_io_wake}. Restarting input stream.")
                    try:
                        if pa_input_stream: pa_input_stream.close()
                        pa_input_stream = pa_input_instance.open(
                            rate=AUDIO_RATE_INPUT, channels=AUDIO_CHANNELS_INPUT,
                            format=AUDIO_FORMAT_INPUT, input=True,
                            frames_per_buffer=FRAMES_PER_BUFFER_INPUT,
                            input_device_index=INPUT_AUDIO_DEVICE_INDEX)
                        print("Input stream restarted.")
                    except Exception as e_restart:
                        print(f"Failed to restart input stream: {e_restart}. Stopping.")
                        stop_event.set()
                        break
                    time.sleep(0.1) # Wait a bit before next read attempt

            elif current_pi_state == PI_STATE_STREAMING_STT:
                frames_processed_in_vad_loop = 0
                was_streaming_stt = True # Indicate we entered this state for potential saving
                has_speech_started_in_stt = False
                initial_silence_frames_count_stt = 0
                speech_frames_count_stt = 0
                consecutive_silent_frames_in_stt = 0
                potential_speech_frames_stt = 0
                
                # Clear frames for saving at the beginning of a new STT session
                # This is also done when transitioning from wake word, but good to have here too
                # if coming from AWAITING_USER_RESPONSE.
                current_utterance_frames_for_saving.clear()
                
                initial_buffer_to_process = None
                initial_buffer_name = ""

                if turn_initial_audio_buffer:
                    initial_buffer_to_process = list(turn_initial_audio_buffer) # Copy
                    print(f"[DEBUG SAVE AUDIO] Processing turn_initial_audio_buffer. Frames to add: {len(initial_buffer_to_process)}. current_utterance_frames_for_saving length before add: {len(current_utterance_frames_for_saving)}")
                    for frame_bytes_init in initial_buffer_to_process: # Add to saving buffer
                        current_utterance_frames_for_saving.append(frame_bytes_init)
                    print(f"[DEBUG SAVE AUDIO] current_utterance_frames_for_saving length after adding turn_initial_audio_buffer: {len(current_utterance_frames_for_saving)}")
                    initial_buffer_name = "turn_initial_audio_buffer"
                    print(f"Processing {len(initial_buffer_to_process)} frames from {initial_buffer_name}.")
                    turn_initial_audio_buffer.clear()
                    wake_word_audio_buffer.clear()
                elif wake_word_audio_buffer:
                    initial_buffer_to_process = list(wake_word_audio_buffer) # Copy
                    print(f"[DEBUG SAVE AUDIO] Processing wake_word_audio_buffer. Frames to add: {len(initial_buffer_to_process)}. current_utterance_frames_for_saving length before add: {len(current_utterance_frames_for_saving)}")
                    for frame_bytes_init in initial_buffer_to_process: # Add to saving buffer
                        current_utterance_frames_for_saving.append(frame_bytes_init)
                    print(f"[DEBUG SAVE AUDIO] current_utterance_frames_for_saving length after adding wake_word_audio_buffer: {len(current_utterance_frames_for_saving)}")
                    initial_buffer_name = "wake_word_audio_buffer"
                    print(f"Processing {len(initial_buffer_to_process)} frames from {initial_buffer_name}.")
                    wake_word_audio_buffer.clear()

                if initial_buffer_to_process:
                    print(f"Sending {len(initial_buffer_to_process)} initial frames from {initial_buffer_name} before live VAD/batching...")
                    for frame_bytes in initial_buffer_to_process:
                        live_audio_batch_buffer.append(frame_bytes)
                        if len(live_audio_batch_buffer) >= FRAMES_PER_BATCH:
                            try:
                                batched_data_to_send = b''.join(live_audio_batch_buffer)
                                stream_audio_chunk_to_cloud(batched_data_to_send)
                            except Exception as e_send_init:
                                print(f"Error sending initial batch from {initial_buffer_name}: {e_send_init}")
                            live_audio_batch_buffer = []
                    if live_audio_batch_buffer: # Send any remaining from initial buffer
                        try:
                            batched_data_to_send = b''.join(live_audio_batch_buffer)
                            stream_audio_chunk_to_cloud(batched_data_to_send)
                        except Exception as e_send_init_rem:
                            print(f"Error sending remaining initial batch from {initial_buffer_name}: {e_send_init_rem}")
                        live_audio_batch_buffer = []
                
                print_periodic_status("Streaming STT: Listening for speech with VAD and batching...")
                last_activity_time = time.time() # Reset for STT session timeout

                while current_pi_state == PI_STATE_STREAMING_STT and not stop_event.is_set():
                    frames_processed_in_vad_loop += 1
                    try:
                        if not pa_input_stream or not pa_input_stream.is_active():
                            print_periodic_status("STT Streaming: Input stream became inactive. Attempting to reopen...")
                            try:
                                if pa_input_stream: pa_input_stream.close()
                            except Exception: pass
                            try:
                                pa_input_stream = pa_input_instance.open(
                                    rate=AUDIO_RATE_INPUT, channels=AUDIO_CHANNELS_INPUT,
                                    format=AUDIO_FORMAT_INPUT, input=True,
                                    frames_per_buffer=FRAMES_PER_BUFFER_INPUT,
                                    input_device_index=INPUT_AUDIO_DEVICE_INDEX
                                )
                                print("STT Streaming: Input stream reopened.")
                            except IOError as e_reopen_stt:
                                print(f"STT Streaming: Failed to reopen input stream: {e_reopen_stt}. Reverting to COMMAND_WAIT.")
                                current_pi_state = PI_STATE_WAITING_FOR_COMMAND
                                last_activity_time = time.time()
                                break # Exit STT VAD loop
                            time.sleep(0.1)
                            continue

                        audio_frame_bytes = pa_input_stream.read(FRAMES_PER_BUFFER_INPUT, exception_on_overflow=False)
                        live_audio_batch_buffer.append(audio_frame_bytes)
                        current_utterance_frames_for_saving.append(audio_frame_bytes) # Save for local WAV
                        if frames_processed_in_vad_loop <= 3: # Log RMS of first few live frames
                            pcm_data_debug = struct.unpack_from("h" * FRAMES_PER_BUFFER_INPUT, audio_frame_bytes)
                            rms_debug = calculate_rms(pcm_data_debug)
                            print(f"[DEBUG SAVE AUDIO] Live frame {frames_processed_in_vad_loop} in STT loop. RMS: {rms_debug:.0f}. current_utterance_frames_for_saving length: {len(current_utterance_frames_for_saving)}")

                        pcm_data = struct.unpack_from("h" * FRAMES_PER_BUFFER_INPUT, audio_frame_bytes)
                        rms = calculate_rms(pcm_data)
                        # print(f"[VAD STT DEBUG] RMS: {rms:.0f} (Threshold: {SILENCE_THRESHOLD_RMS})") # Verbose

                        if not has_speech_started_in_stt:
                            if rms > SILENCE_THRESHOLD_RMS:
                                print(f"[VAD STT DEBUG] Potential speech start: RMS {rms:.0f} > {SILENCE_THRESHOLD_RMS}. Frame count for speech start: {potential_speech_frames_stt + 1}/{MIN_FRAMES_TO_CONFIRM_SPEECH_START_STT}")
                                potential_speech_frames_stt += 1
                                if potential_speech_frames_stt >= MIN_FRAMES_TO_CONFIRM_SPEECH_START_STT:
                                    print(f"[VAD STT DEBUG] Speech confirmed started after {potential_speech_frames_stt} frames.")
                                    has_speech_started_in_stt = True
                                    speech_frames_count_stt = potential_speech_frames_stt
                                    consecutive_silent_frames_in_stt = 0
                                    initial_silence_frames_count_stt = 0 
                                    print_periodic_status("STT VAD: Speech detected, monitoring for end.")
                            else: # Silence before speech is confirmed
                                if potential_speech_frames_stt > 0:
                                    print(f"[VAD STT DEBUG] Silence (RMS {rms:.0f}) after {potential_speech_frames_stt} potential speech frames. Resetting potential speech counter.")
                                potential_speech_frames_stt = 0
                                initial_silence_frames_count_stt += 1
                                if initial_silence_frames_count_stt > MAX_INITIAL_SILENT_FRAMES_STT:
                                    print(f"VAD: No speech detected in STT state after {initial_silence_frames_count_stt} initial silent frames (RMS {rms:.0f} consistently below threshold). Ending capture, waiting for agent command.")
                                    current_pi_state = PI_STATE_WAITING_FOR_COMMAND
                                    last_activity_time = time.time()
                                    break # Exit STT VAD loop
                        else: # has_speech_started_in_stt is True
                            if rms > SILENCE_THRESHOLD_RMS:
                                speech_frames_count_stt +=1
                                consecutive_silent_frames_in_stt = 0
                            else: # Silence after speech has started
                                consecutive_silent_frames_in_stt += 1
                                if consecutive_silent_frames_in_stt >= MAX_CONSECUTIVE_SILENT_FRAMES_STT:
                                    if speech_frames_count_stt >= MIN_SPEECH_FRAMES_FOR_VALID_UTTERANCE_STT:
                                        print(f"VAD: End of utterance detected (RMS {rms:.0f}) after {speech_frames_count_stt} speech frames and {consecutive_silent_frames_in_stt} silent frames. Ending capture, waiting for agent command.")
                                        current_pi_state = PI_STATE_WAITING_FOR_COMMAND
                                        last_activity_time = time.time()
                                        break # Exit STT VAD loop
                                    else:
                                        print(f"VAD: Silence (RMS {rms:.0f}) after very short speech ({speech_frames_count_stt} frames < {MIN_SPEECH_FRAMES_FOR_VALID_UTTERANCE_STT}). Resetting VAD for STT, continuing to listen in this session.")
                                        has_speech_started_in_stt = False
                                        speech_frames_count_stt = 0
                                        potential_speech_frames_stt = 0
                                        initial_silence_frames_count_stt = consecutive_silent_frames_in_stt # Carry over the silence count
                                        consecutive_silent_frames_in_stt = 0
                                        # Continue in STT VAD loop
                        
                        if len(live_audio_batch_buffer) >= FRAMES_PER_BATCH:
                            try:
                                batched_data_to_send = b''.join(live_audio_batch_buffer)
                                stream_audio_chunk_to_cloud(batched_data_to_send)
                            except Exception as e_send:
                                print(f"Error sending STT batch: {e_send}")
                            live_audio_batch_buffer = []
                        
                        if (time.time() - last_activity_time) > STREAM_TO_CLOUD_DURATION_SECONDS: 
                            print(f"STT streaming session timed out after {STREAM_TO_CLOUD_DURATION_SECONDS}s. Ending capture, waiting for agent command.")
                            current_pi_state = PI_STATE_WAITING_FOR_COMMAND
                            last_activity_time = time.time() 
                            break # Exit STT VAD loop

                    except IOError as e_io_stt:
                        print(f"\nIOError during STT streaming: {e_io_stt}. Ending capture, waiting for agent command.")
                        if live_audio_batch_buffer:
                            print(f"IOError: Sending remaining {len(live_audio_batch_buffer)} frames before changing state...")
                            try:
                                batched_data_to_send = b''.join(live_audio_batch_buffer)
                                stream_audio_chunk_to_cloud(batched_data_to_send)
                            except Exception as e_send_err:
                                print(f"Error sending remaining batch during IOError: {e_send_err}")
                            live_audio_batch_buffer.clear()
                        current_pi_state = PI_STATE_WAITING_FOR_COMMAND
                        last_activity_time = time.time()
                        break # Exit STT VAD loop
                    except Exception as e_gen_stt:
                        print(f"\nUnexpected error during STT streaming: {e_gen_stt}. Ending capture, waiting for agent command.")
                        if live_audio_batch_buffer:
                            print(f"Error/Exception: Sending remaining {len(live_audio_batch_buffer)} frames before changing state...")
                            try:
                                batched_data_to_send = b''.join(live_audio_batch_buffer)
                                stream_audio_chunk_to_cloud(batched_data_to_send)
                            except Exception as e_send_err:
                                print(f"Error sending remaining batch during Exception: {e_send_err}")
                            live_audio_batch_buffer.clear()
                        current_pi_state = PI_STATE_WAITING_FOR_COMMAND
                        last_activity_time = time.time()
                        break # Exit STT VAD loop
                # End of STT streaming VAD while loop
                print("[STT Loop] Exited live streaming VAD loop.")
                
                # Save the complete utterance if we were in STT mode
                if was_streaming_stt:
                    save_current_utterance_to_wav(list(current_utterance_frames_for_saving)) # Pass a copy
                    current_utterance_frames_for_saving.clear() # Clear for next time
                
                if live_audio_batch_buffer and not stop_event.is_set() and was_streaming_stt : # Send any final partial batch
                    try:
                        batched_data_to_send = b''.join(live_audio_batch_buffer)
                        stream_audio_chunk_to_cloud(batched_data_to_send)
                        print(f"Post-Loop (Exited STT VAD): Sending final remaining {len(live_audio_batch_buffer)} frames.")
                    except Exception as e_post_send:
                        print(f"Error sending remaining batch post-STT VAD loop: {e_post_send}")
                    live_audio_batch_buffer.clear()
                
                print(f"Finished STT streaming. Total frames processed in VAD loop: {frames_processed_in_vad_loop}.")
                # If the loop exited for reasons other than explicit state change (e.g. stop_event), ensure we are in WAITING_FOR_COMMAND
                if current_pi_state == PI_STATE_STREAMING_STT and not stop_event.is_set():
                    print("STT VAD loop exited but state is still STREAMING_STT (should be rare). Defaulting to WAITING_FOR_COMMAND.")
                    current_pi_state = PI_STATE_WAITING_FOR_COMMAND
                    last_activity_time = time.time()

            elif current_pi_state == PI_STATE_WAITING_FOR_COMMAND:
                time_in_state = time.time() - last_activity_time
                print_periodic_status(f"Waiting for command from agent. Timeout in {COMMAND_TIMEOUT_SECONDS - time_in_state:.1f}s")
                
                if time_in_state > COMMAND_TIMEOUT_SECONDS:
                    print(f"\nTimeout in {PI_STATE_WAITING_FOR_COMMAND} (no command/TTS from agent). Reverting to wake word listening.")
                    current_pi_state = PI_STATE_LISTENING_WAKE_WORD
                    rpi_current_conversation_id = None # Clear conversation ID on timeout
                    print(f"[COMMAND_TIMEOUT] RPi Conversation ID CLEARED.")
                else:
                    time.sleep(0.1) # Check periodically

            elif current_pi_state == PI_STATE_AWAITING_USER_RESPONSE:
                # VAD logic for PI_STATE_AWAITING_USER_RESPONSE
                time_in_user_await_state = time.time() - last_activity_time
                print_periodic_status(f"Listening for user's response (timeout: {USER_TURN_SILENCE_TIMEOUT_SECONDS - time_in_user_await_state:.1f}s)...")
                
                # VAD variables for this state
                # Using a simplified VAD here: any sound above threshold starts STT.
                
                try:
                    if not pa_input_stream or not pa_input_stream.is_active():
                        print_periodic_status("AWAITING USER: Input stream inactive. Attempting to reopen...")
                        try:
                            if pa_input_stream: pa_input_stream.close()
                        except Exception: pass
                        try:
                            pa_input_stream = pa_input_instance.open(
                                rate=AUDIO_RATE_INPUT, channels=AUDIO_CHANNELS_INPUT,
                                format=AUDIO_FORMAT_INPUT, input=True,
                                frames_per_buffer=FRAMES_PER_BUFFER_INPUT,
                                input_device_index=INPUT_AUDIO_DEVICE_INDEX
                            )
                            print("AWAITING USER: Input stream reopened.")
                            turn_pre_roll_buffer.clear() # Clear pre-roll on stream reopen
                        except IOError as e_reopen:
                            print(f"AWAITING USER: Failed to reopen input stream: {e_reopen}. Retrying...")
                            time.sleep(1)
                            continue # Retry in main loop for this state

                    audio_frame_bytes = pa_input_stream.read(FRAMES_PER_BUFFER_INPUT, exception_on_overflow=False)
                    
                    turn_pre_roll_buffer.append(audio_frame_bytes)
                    if len(turn_pre_roll_buffer) > TURN_AUDIO_PRE_ROLL_FRAMES:
                        turn_pre_roll_buffer.pop(0)

                    pcm_data = struct.unpack_from("h" * FRAMES_PER_BUFFER_INPUT, audio_frame_bytes)
                    rms = calculate_rms(pcm_data)

                    if rms > SILENCE_THRESHOLD_RMS:
                        print(f"[AWAITING USER] Speech detected (RMS: {rms:.0f}). Transitioning to STT.")
                        turn_initial_audio_buffer.extend(list(turn_pre_roll_buffer)) # Use the pre-roll
                        print(f"[DEBUG SAVE AUDIO] In AWAITING_USER_RESPONSE, speech detected. turn_initial_audio_buffer length: {len(turn_initial_audio_buffer)}")
                        turn_pre_roll_buffer.clear()
                        print(f"[DEBUG SAVE AUDIO] Clearing current_utterance_frames_for_saving (AWAITING_USER_RESPONSE flow). Length before clear: {len(current_utterance_frames_for_saving)}")
                        current_utterance_frames_for_saving.clear() # Clear for new STT session
                        print(f"[DEBUG SAVE AUDIO] Length after clear (AWAITING_USER_RESPONSE flow): {len(current_utterance_frames_for_saving)}")
                        current_pi_state = PI_STATE_STREAMING_STT
                        live_audio_batch_buffer = []
                        # No break here, main loop will pick up new state in next iteration
                    
                    elif (time.time() - last_activity_time) > USER_TURN_SILENCE_TIMEOUT_SECONDS:
                        print(f"[AWAITING USER] User turn timed out after {USER_TURN_SILENCE_TIMEOUT_SECONDS}s. Reverting to wake word.")
                        current_pi_state = PI_STATE_LISTENING_WAKE_WORD
                        rpi_current_conversation_id = None 
                        print(f"[USER_TURN_TIMEOUT] RPi Conversation ID CLEARED.")
                        turn_initial_audio_buffer.clear()
                        turn_pre_roll_buffer.clear()
                        # No break here, main loop will pick up new state
                    else:
                        time.sleep(0.01) # Yield if silent but not timed out

                except IOError as e_io_await:
                    print(f"IOError during AWAITING_USER_RESPONSE: {e_io_await}. Attempting to recover stream.")
                    if pa_input_stream:
                        try: pa_input_stream.close()
                        except Exception: pass
                    pa_input_stream = None
                    time.sleep(0.5)
                    # Continue in main loop for this state
                except Exception as e_await_vad:
                    print(f"Unexpected error in AWAITING_USER_RESPONSE VAD loop: {e_await_vad}. Reverting to wake word.")
                    current_pi_state = PI_STATE_LISTENING_WAKE_WORD
                    rpi_current_conversation_id = None 
                    print(f"[AWAIT_USER_VAD_ERR] RPi Conversation ID CLEARED.")
                    # No break here, main loop will pick up new state
            else:
                print(f"Unknown PI_STATE: {current_pi_state}. Defaulting to {PI_STATE_LISTENING_WAKE_WORD}")
                current_pi_state = PI_STATE_LISTENING_WAKE_WORD
                rpi_current_conversation_id = None # Clear conversation ID
                time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nKeyboardInterrupt. Shutting down Pi client...")
    except Exception as e_main_loop:
        print(f"\nMain loop encountered an unhandled error: {e_main_loop}")
    finally:
        print("\nMain loop ending. Initiating cleanup...")
        if not stop_event.is_set():
            stop_event.set()
        cleanup_resources()

def cleanup_resources():
    """Cleans up Porcupine, PyAudio, and Pub/Sub resources."""
    global porcupine, pa_input_instance, pa_output_instance, pa_input_stream, pa_output_stream, gcs_client
    global tts_pubsub_subscriber_client, convo_control_pubsub_subscriber_client
    global tts_listener_future, convo_control_listener_future, stop_event 

    print("Cleaning up resources...")
    if not stop_event.is_set(): 
        stop_event.set()

    futures_to_clean = {
        "TTS Listener": tts_listener_future,
        "Convo Control Listener": convo_control_listener_future
    }
    for name, future_obj in futures_to_clean.items():
        if future_obj:
            print(f"Cancelling {name} future...")
            if future_obj.running(): 
                future_obj.cancel()
            try:
                future_obj.result(timeout=5)
                print(f"{name} future cancelled/completed.")
            except TimeoutError:
                print(f"Timeout waiting for {name} future to cancel/complete.")
            except pubsub_v1.exceptions.Cancelled: 
                print(f"{name} future was already cancelled.")
            except Exception as e:
                print(f"Error during {name} future cleanup: {e}")

    clients_to_close = [
        ("TTS PubSub Client", tts_pubsub_subscriber_client),
        ("Convo Control PubSub Client", convo_control_pubsub_subscriber_client)
    ]
    for name, client in clients_to_close:
        if client:
            print(f"Closing {name}...")
            try:
                client.close()
                print(f"{name} closed.")
            except Exception as e:
                print(f"Error closing {name}: {e}")
    
    if pa_input_stream:
        print("Closing PyAudio input stream...")
        try:
            if pa_input_stream.is_active():
                pa_input_stream.stop_stream()
            pa_input_stream.close()
            print("PyAudio input stream closed.")
        except Exception as e:
            print(f"Error closing PyAudio input stream: {e}")
    
    if pa_output_stream:
        print("Closing PyAudio output stream...")
        try:
            if pa_output_stream.is_active():
                pa_output_stream.stop_stream()
            pa_output_stream.close()
            print("PyAudio output stream closed.")
        except Exception as e:
            print(f"Error closing PyAudio output stream: {e}")
    
    if pa_input_instance:
        try:
            print("Terminating PyAudio input instance...")
            pa_input_instance.terminate()
            print("PyAudio input instance terminated.")
        except Exception as e:
            print(f"Error terminating PyAudio input instance: {e}")
    
    if pa_output_instance:
        try:
            print("Terminating PyAudio output instance...")
            pa_output_instance.terminate()
            print("PyAudio output instance terminated.")
        except Exception as e:
            print(f"Error terminating PyAudio output instance: {e}")

    if porcupine:
        print("Deleting Porcupine instance...")
        try:
            porcupine.delete()
            print("Porcupine instance deleted.")
        except Exception as e:
            print(f"Error deleting Porcupine instance: {e}")
    
    print("Cleanup finished.")

if __name__ == "__main__":
    if initialize_audio_services():
        # Start Pub/Sub listener threads
        if tts_pubsub_subscriber_client:
            start_listener_thread(
                tts_pubsub_subscriber_client,
                TTS_OUTPUT_SUBSCRIPTION_NAME,
                tts_message_callback,
                "TTS",
                set_tts_future
            )
        else:
            print("TTS Pub/Sub client not initialized. TTS listener thread not started.")

        if convo_control_pubsub_subscriber_client:
            start_listener_thread(
                convo_control_pubsub_subscriber_client,
                PUBSUB_RPI_CONVO_CONTROL_SUBSCRIPTION,
                conversation_control_callback,
                "ConvoControl",
                set_convo_control_future
            )
        else:
            print("Conversation Control Pub/Sub client not initialized. Listener thread not started.")
        
        main_loop() # This will block until stop_event is set or an error occurs
    else:
        print("Failed to initialize audio services. Exiting.")
        cleanup_resources() # Attempt cleanup even if initialization failed partially
    
    print("Application finished.")