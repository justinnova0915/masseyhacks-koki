"""
Central configuration file for Kokoro AI Assistant
"""

import os

# Network configuration
RASPI_IP = os.getenv("KOKORO_RASPI_IP", "192.168.2.125")  # Raspberry Pi's IP address
COMPUTER_IP = os.getenv("KOKORO_COMPUTER_IP", "192.168.2.160")  # Your computer's IP address
COMPUTER_LISTEN_IP = os.getenv("KOKORO_COMPUTER_LISTEN_IP", "0.0.0.0")  # Listen on all interfaces (on computer)

# UDP ports
WAKE_WORD_PORT = int(os.getenv("KOKORO_WAKE_WORD_PORT", "12347"))  # Port for wake word audio (Pi → Computer)
STT_PORT = int(os.getenv("KOKORO_STT_PORT", "12346"))  # Port for speech recognition audio (Pi → Computer)
TTS_PORT = int(os.getenv("KOKORO_TTS_PORT", "12345"))  # Port for text-to-speech audio (Computer → Pi)

# GCP Configuration
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID")
GCP_REGION = os.getenv("GCP_REGION", "us-central1")
PUBSUB_WAKE_WORD_TOPIC = os.getenv("PUBSUB_WAKE_WORD_TOPIC", "kokoro-wake-word-dev")
API_GATEWAY_URL = os.getenv("API_GATEWAY_URL")
PUBSUB_RAW_AUDIO_TOPIC = os.getenv("PUBSUB_RAW_AUDIO_TOPIC", "kokoro-raw-audio-dev")
PUBSUB_WAKE_WORD_SUBSCRIPTION = os.getenv("PUBSUB_WAKE_WORD_SUBSCRIPTION", "kokoro-ai-agent-wake-word-sub")
PUBSUB_RAW_AUDIO_SUBSCRIPTION = os.getenv("PUBSUB_RAW_AUDIO_SUBSCRIPTION", "kokoro-ai-agent-raw-audio-sub-dev")
KOKORO_AUDIO_CHUNKS_GCS_BUCKET = os.getenv("KOKORO_AUDIO_CHUNKS_GCS_BUCKET", "kokoro-audio-chunks-diesel-dominion")

# Blender Control Pub/Sub Topics
PUBSUB_BLENDER_LIP_SYNC_TOPIC = os.getenv("PUBSUB_BLENDER_LIP_SYNC_TOPIC", "kokoro-blender-lip-sync-commands-dev")
PUBSUB_BLENDER_ANIMATION_TOPIC = os.getenv("PUBSUB_BLENDER_ANIMATION_TOPIC", "kokoro-blender-animation-control-dev")

PUBSUB_FACE_TRACKING_TOPIC = os.getenv("PUBSUB_FACE_TRACKING_TOPIC", "kokoro-face-tracking-coordinates")
PUBSUB_FACE_TRACKING_SUBSCRIPTION = os.getenv("PUBSUB_FACE_TRACKING_SUBSCRIPTION", "kokoro-face-tracking-coordinates-sub")
# Conversation Control Pub/Sub
PUBSUB_CONVO_CONTROL_TOPIC = os.getenv("PUBSUB_CONVO_CONTROL_TOPIC", "kokoro-conversation-control-dev")
PUBSUB_RPI_CONVO_CONTROL_SUBSCRIPTION = os.getenv("PUBSUB_RPI_CONVO_CONTROL_SUBSCRIPTION", "kokoro-rpi-convo-control-sub")

# Secret Management Placeholder
# def get_gcp_secret(secret_name_env_var, project_id_env_var="GCP_PROJECT_ID"):
#     secret_id = os.getenv(secret_name_env_var)
#     project_id = os.getenv(project_id_env_var)
#     if not secret_id or not project_id:
#         print(f"Warning: Config for secret '{secret_id}' or project_id '{project_id}' not set.")
#         return None
#     # Actual GCP Secret Manager client call would go here
#     # from google.cloud import secretmanager
#     # client = secretmanager.SecretManagerServiceClient()
#     # name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
#     # response = client.access_secret_version(request={"name": name})
#     # return response.payload.data.decode("UTF-8")
#     return f"MOCK_SECRET_FOR_{secret_id}"
#
# SOME_API_KEY = get_gcp_secret("SOME_API_KEY_SECRET_NAME")
# Audio settings - Capture (Raspberry Pi microphone)
CAPTURE_FORMAT = os.getenv("KOKORO_CAPTURE_FORMAT", "int16")  # 16-bit PCM
CAPTURE_CHANNELS = int(os.getenv("KOKORO_CAPTURE_CHANNELS", "1"))  # Mono for wake word & STT
CAPTURE_RATE = int(os.getenv("KOKORO_CAPTURE_RATE", "16000"))  # Sample rate in Hz
CAPTURE_CHUNK_SIZE = int(os.getenv("KOKORO_CAPTURE_CHUNK_SIZE", "512"))  # Samples per packet

# Audio settings - Playback (Raspberry Pi speakers)
PLAYBACK_FORMAT = os.getenv("KOKORO_PLAYBACK_FORMAT", "int16")  # 16-bit PCM
PLAYBACK_CHANNELS = int(os.getenv("KOKORO_PLAYBACK_CHANNELS", "2"))  # Stereo for playback
PLAYBACK_RATE = int(os.getenv("KOKORO_PLAYBACK_RATE", "48000"))  # Sample rate in Hz
PLAYBACK_CHUNK_SIZE = int(os.getenv("KOKORO_PLAYBACK_CHUNK_SIZE", "2048"))  # Samples per chunk

# BASE_DIR is retained for other uses like VENV_PYTHON, AGENT_SCRIPT, etc.
BASE_DIR = os.getenv("KOKORO_BASE_DIR", r"C:\Users\justi\PycharmProjects\Kokoro")
# Paths (on computer)
VENV_PYTHON = os.path.join(BASE_DIR, os.getenv("KOKORO_VENV_SUBPATH", ".venv"), "Scripts", "python.exe")
AGENT_SCRIPT = os.path.join(BASE_DIR, os.getenv("KOKORO_AGENT_SCRIPT_FILENAME", "real_time_ai_agent.py"))
CUSTOM_KEYWORD_PATH = os.getenv("KOKORO_CUSTOM_KEYWORD_PATH", r"C:\Users\justi\Downloads\hey-koki_en_windows_v3_0_0\hey-koki_en_windows_v3_0_0.ppn")

# Tool and Command File Paths
# For Rhubarb executable
KOKORO_RHUBARB_EXECUTABLE_PATH = os.getenv("KOKORO_RHUBARB_EXECUTABLE_PATH", "/app/rhubarb")

# For Blender command files
KOKORO_LIP_COMMAND_FILE_PATH = os.getenv("KOKORO_LIP_COMMAND_FILE_PATH", "/tmp/lip_command.txt")
KOKORO_BLINK_COMMAND_FILE_PATH = os.getenv("KOKORO_BLINK_COMMAND_FILE_PATH", "/tmp/blink_command.txt")
KOKORO_PLAY_COMMAND_FILE_PATH = os.getenv("KOKORO_PLAY_COMMAND_FILE_PATH", "/tmp/play_command.txt")

# For Rhubarb input and output files
KOKORO_RHUBARB_DIALOGUE_FILE_PATH = os.getenv("KOKORO_RHUBARB_DIALOGUE_FILE_PATH", "/tmp/dialogue.txt")
RHUBARB_OUTPUT_FILE_PATH = os.getenv("KOKORO_RHUBARB_OUTPUT_FILE_PATH", "/tmp/output.txt") # Existing, good default

# Wake word settings
WAKE_WORD_ACCESS_KEY = os.getenv("KOKORO_WAKE_WORD_ACCESS_KEY", "R9JpPtNjUCi3TM+sDhFDwHju2ukhq5mdhOse7YNQ/cLH+5g+TAQrSA==")
WAKE_WORD_SENSITIVITY = float(os.getenv("KOKORO_WAKE_WORD_SENSITIVITY", "0.5"))

# LLM settings
LLM_MODEL = os.getenv("KOKORO_LLM_MODEL", "llama3.1:8b")

# Real-time AI Agent specific STT settings
STT_MIN_TURN_DURATION_BEFORE_EMPTY_ACCEPT_SECONDS = float(os.getenv("KOKORO_STT_MIN_TURN_DURATION_EMPTY_ACCEPT", "5.5")) # Min duration into STT turn before an empty transcript is accepted by agent. Increased from 2.5

# Synchronization settings
KOKORO_PI_PLAYBACK_DELAY_SECONDS = float(os.getenv("KOKORO_PI_PLAYBACK_DELAY_SECONDS", "0")) # Delay before telling Pi to play preloaded audio
