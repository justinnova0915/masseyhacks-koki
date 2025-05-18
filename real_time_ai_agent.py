# real_time_ai_agent.py (Edited and improved by AI)
import logging
import sys
import time # Ensure time is imported for time.time() and time.sleep()
import os
import socket
import json # Added for Pub/Sub message parsing
from urllib.parse import urlparse # Added for GCS URI parsing
import numpy as np
# import pyaudio # Removed
import resampy
from colorama import init, Fore, Style
import uuid # Added for unique IDs
from datetime import datetime # Added for timestamps
import warnings
from google.cloud import speech
from google.cloud import texttospeech
from google.cloud import pubsub_v1 # Added for Pub/Sub
from google.cloud import storage # Added for GCS interaction
import google.api_core.exceptions # Added for Pub/Sub exceptions
from concurrent.futures import TimeoutError # Added for Pub/Sub subscriber management
import queue
from threading import Thread, Event # Modified for Pub/Sub
from enum import Enum # Added for agent visual states
from dotenv import load_dotenv
import kokoro_config as kc
from kokoro_config import GCP_PROJECT_ID, PUBSUB_WAKE_WORD_TOPIC, PUBSUB_WAKE_WORD_SUBSCRIPTION, PUBSUB_CONVO_CONTROL_TOPIC, PUBSUB_BLENDER_LIP_SYNC_TOPIC, PUBSUB_BLENDER_ANIMATION_TOPIC # Added
# from RealtimeTTS import TextToAudioStream, KokoroEngine # Removed
import infer
import subprocess
# import wave # Removed
# import threading # Already imported via 'from threading import Thread, Event'
import soundfile as sf

# Suppress warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

# Load environment variables from .env file
load_dotenv()

# Configuration variables are now primarily sourced from kokoro_config.
# Local definitions below are for values not present in kokoro_config,
# or for values specific to this agent's internal logic.

# Audio settings for raw UDP input (before STT-specific resampling)
SAMPLE_RATE = 48000  # Expected sample rate of incoming UDP audio from Pi for STT.
                     # This stream will be resampled to kc.CAPTURE_RATE for Google STT.

# Paths for external tools and specific operational directories not in central config
RHUBARB_PATH = kc.KOKORO_RHUBARB_EXECUTABLE_PATH
BLENDER_PATH = "C:\\Program Files\\Blender Foundation\\Blender 4.4\\blender.exe"
BLEND_FILE = "C:\\Users\\justi\\Koki-Texture\\Untitled.blend"

# Command file paths are now sourced from kokoro_config
LIP_COMMAND_FILE = kc.KOKORO_LIP_COMMAND_FILE_PATH
BLINK_COMMAND_FILE = kc.KOKORO_BLINK_COMMAND_FILE_PATH
PLAY_COMMAND_FILE = kc.KOKORO_PLAY_COMMAND_FILE_PATH

# Derived paths using kc.BASE_DIR from kokoro_config for files expected in the project root
# RHUBARB_OUTPUT_FILE is now sourced from kc.RHUBARB_OUTPUT_FILE_PATH
# For clarity, we can remove the old global definition or comment it out.
# RHUBARB_OUTPUT_FILE = os.path.join(kc.BASE_DIR, "output.txt") # For Rhubarb output
LIP_SCRIPT = os.path.join(kc.BASE_DIR, "Lip.py") # Assumed to be in BASE_DIR with agent script
BLINK_SCRIPT = os.path.join(kc.BASE_DIR, "blink.py") # Assumed to be in BASE_DIR with agent script

# Note:
# COMPUTER_IP (use kc.COMPUTER_LISTEN_IP for server binding)
# COMPUTER_PORT (use kc.STT_PORT)
# kc.RASPI_IP and kc.TTS_PORT for direct TTS UDP output by this agent are no longer used.
# TARGET_RATE (use kc.CAPTURE_RATE for STT)
# RHUBARB_OUTPUT_DIR (use kc.BASE_DIR for output.txt)
# BLENDER_SCRIPT_DIR (use kc.BASE_DIR for Lip.py, blink.py)
# are now sourced from kc (kokoro_config) where applicable, or their roles are covered by kc variables.
# WAKE_WORD_PORT is available in kc but not directly used in this script's current logic.
# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

logging.info("Starting imports...")
init()
logging.info("All imports complete!")

class AgentVisualState(Enum):
    LISTENING = "listening"
    THINKING = "thinking"
    TALKING = "talking"
    IDLE = "idle"

class ColoredFormatter(logging.Formatter):
    COLORS = {
        'INFO': Fore.WHITE,
        'DEBUG': Fore.CYAN,
        'WARNING': Fore.YELLOW,
        'ERROR': Fore.RED,
        'CRITICAL': Fore.RED + Style.BRIGHT
    }
    def format(self, record):
        levelname = record.levelname
        msg = super().format(record)
        return f"{self.COLORS.get(levelname, Fore.WHITE)}{msg}{Style.RESET_ALL}"

for handler in logging.getLogger().handlers:
    if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
        handler.setFormatter(ColoredFormatter('%(asctime)s - %(levelname)s - %(message)s'))

# UDP_PORT, CHUNK_SIZE, CHANNELS, RATE for TTS audio streaming are now sourced from kc:
# kc.TTS_PORT, kc.PLAYBACK_CHUNK_SIZE, kc.PLAYBACK_CHANNELS, kc.PLAYBACK_RATE
# FORMAT = pyaudio.paInt16 # Removed (PyAudio specific)
# SAMPLE_RATES = [48000, 44100, 96000, 32000, 16000, 8000] # Removed (PyAudio specific)

# Google TTS Settings
TTS_VOICE_NAME = 'en-US-Chirp3-HD-Autonoe'
TTS_LANGUAGE_CODE = 'en-US'
TTS_SAMPLE_RATE_HZ = kc.PLAYBACK_RATE # Target sample rate for generated audio (aligns with Pi playback)

# Goodbye phrases for conversation control
GOODBYE_PHRASES = ["goodbye", "bye", "cya", "see ya", "sounds good", "that's all", "thank you that's all", "later"]
STT_TURN_TIMEOUT = 15 # seconds

class RealTimeAIAgent:
    def __init__(self):
        # Verify Google credentials
        # credential_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        # if not credential_path or not os.path.exists(credential_path):
        #     raise Exception(f"Google credentials not found or invalid at: {credential_path}")
        # logging.info(f"Google credentials loaded from: {credential_path}")

        # Initialize Google TTS Client
        try:
            self.tts_client = texttospeech.TextToSpeechClient()
            logging.info("Google Cloud Text-to-Speech client initialized.")
        except Exception as e:
            logging.error(f"Failed to initialize Google Cloud Text-to-Speech client: {e}")
            raise

        # Initialize Google Cloud Storage Client
        try:
            self.storage_client = storage.Client()
            logging.info("Google Cloud Storage client initialized.")
        except Exception as e:
            logging.error(f"Failed to initialize Google Cloud Storage client: {e}")
            raise

        # Initialize Google Cloud Pub/Sub Publisher Client
        try:
            self.publisher_client = pubsub_v1.PublisherClient()
            logging.info("Google Cloud Pub/Sub Publisher client initialized.")
        except Exception as e:
            logging.error(f"Failed to initialize Google Cloud Pub/Sub Publisher client: {e}")
            raise

        # Configuration for TTS output Pub/Sub topic
        self.tts_output_topic_name = "kokoro-tts-output-dev"
        try:
            self.tts_output_topic_path = self.publisher_client.topic_path(kc.GCP_PROJECT_ID, self.tts_output_topic_name)
            logging.info(f"TTS output Pub/Sub topic path configured: {self.tts_output_topic_path}")
        except Exception as e:
            logging.error(f"Failed to configure TTS output Pub/Sub topic path: {e}")
            # Decide if this is critical enough to raise. For now, logging error.
            # raise # Uncomment if this setup is absolutely critical for startup
        
        # Configuration for Conversation Control Pub/Sub topic
        self.convo_control_topic_path = None
        if hasattr(kc, 'PUBSUB_CONVO_CONTROL_TOPIC') and kc.PUBSUB_CONVO_CONTROL_TOPIC:
            try:
                self.convo_control_topic_path = self.publisher_client.topic_path(kc.GCP_PROJECT_ID, kc.PUBSUB_CONVO_CONTROL_TOPIC)
                logging.info(f"Conversation control Pub/Sub topic path configured: {self.convo_control_topic_path}")
            except Exception as e:
                logging.error(f"Failed to configure Conversation Control Pub/Sub topic path: {e}")
                # Decide if this is critical. For now, logging error.
        else:
            logging.warning("PUBSUB_CONVO_CONTROL_TOPIC not found in kokoro_config.py. Conversation control messages will not be sent.")

        # Configuration for Blender Control Pub/Sub topics
        self.blender_lip_sync_topic_path = None
        if hasattr(kc, 'PUBSUB_BLENDER_LIP_SYNC_TOPIC') and kc.PUBSUB_BLENDER_LIP_SYNC_TOPIC:
            try:
                self.blender_lip_sync_topic_path = self.publisher_client.topic_path(kc.GCP_PROJECT_ID, kc.PUBSUB_BLENDER_LIP_SYNC_TOPIC)
                logging.info(f"Blender lip sync Pub/Sub topic path configured: {self.blender_lip_sync_topic_path}")
            except Exception as e:
                logging.error(f"Failed to configure Blender lip sync Pub/Sub topic path: {e}")
        else:
            logging.warning("PUBSUB_BLENDER_LIP_SYNC_TOPIC not found in kokoro_config.py. Blender lip sync commands will not be sent.")

        self.blender_animation_topic_path = None
        if hasattr(kc, 'PUBSUB_BLENDER_ANIMATION_TOPIC') and kc.PUBSUB_BLENDER_ANIMATION_TOPIC:
            try:
                self.blender_animation_topic_path = self.publisher_client.topic_path(kc.GCP_PROJECT_ID, kc.PUBSUB_BLENDER_ANIMATION_TOPIC)
                logging.info(f"Blender animation Pub/Sub topic path configured: {self.blender_animation_topic_path}")
            except Exception as e:
                logging.error(f"Failed to configure Blender animation Pub/Sub topic path: {e}")
        else:
            logging.warning("PUBSUB_BLENDER_ANIMATION_TOPIC not found in kokoro_config.py. Blender animation commands will not be sent.")

        # TTS UDP socket (self.sock) and its initialization (initialize_sock) are removed.
        # TTS audio will be sent to an abstracted stream via _send_tts_audio_chunk_to_stream.

        # Flag to indicate if the agent is currently speaking (streaming audio)
        self.is_speaking = False
        self.in_conversation = False # Added for multi-turn conversation state
        self.conversation_id = None # To store current conversation ID
        
        # Event to signal wake word detection from Pub/Sub
        self.wake_word_detected = Event()
        self.logged_first_audio_chunk_for_convo = False # Added for one-time audio logging
        self.subscriber_client = None
        self.streaming_pull_future = None
        self.subscription_path = None # Store for cleanup for wake word
        self.stop_event = Event() # Event to signal threads to stop

        # Attributes for raw audio Pub/Sub
        self.raw_audio_subscriber_client = None
        self.raw_audio_streaming_pull_future = None
        self.raw_audio_subscription_path = None # For raw audio notifications

        # Infer.py handles model loading upon import
        logging.info("Infer.py imported, model should be loaded.")
        # Removed INIT_COMPLETE_FILE logic:
        # try:
        #     with open(kc.INIT_COMPLETE_FILE, "w") as f:
        #         f.write("Initialization complete")
        # except Exception as e:
        #     logging.warning(f"Could not write init_complete.txt: {e}")

        self._initialize_pubsub_subscriber()
        self._initialize_raw_audio_subscriber() # Added for STT audio notifications
        self._send_visual_state_to_blender(AgentVisualState.LISTENING.value) # Initial state

    def _initialize_raw_audio_subscriber(self):
        """Initializes the Pub/Sub subscriber for raw audio notifications."""
        try:
            self.raw_audio_subscriber_client = pubsub_v1.SubscriberClient()
            
            if not kc.GCP_PROJECT_ID:
                logging.error("GCP_PROJECT_ID not configured in kokoro_config.py!")
                raise ValueError("GCP_PROJECT_ID not configured.")
            # Ensure PUBSUB_RAW_AUDIO_SUBSCRIPTION is defined in kokoro_config.py
            if not hasattr(kc, 'PUBSUB_RAW_AUDIO_SUBSCRIPTION') or not kc.PUBSUB_RAW_AUDIO_SUBSCRIPTION:
                logging.error("PUBSUB_RAW_AUDIO_SUBSCRIPTION not configured in kokoro_config.py!")
                raise ValueError("Pub/Sub raw audio subscription name not configured.")
            # Ensure PUBSUB_RAW_AUDIO_TOPIC is defined in kokoro_config.py for logging message
            if not hasattr(kc, 'PUBSUB_RAW_AUDIO_TOPIC') or not kc.PUBSUB_RAW_AUDIO_TOPIC:
                logging.warning("PUBSUB_RAW_AUDIO_TOPIC not configured in kokoro_config.py! Verification message might be incomplete.")
                # Not raising an error here as it's for a log message, but it's important for manual setup.

            self.raw_audio_subscription_path = self.raw_audio_subscriber_client.subscription_path(
                kc.GCP_PROJECT_ID,
                kc.PUBSUB_RAW_AUDIO_SUBSCRIPTION
            )
            logging.info(f"Will use existing Pub/Sub subscription for raw audio: {self.raw_audio_subscription_path}")

            # Verify the subscription exists
            try:
                self.raw_audio_subscriber_client.get_subscription(subscription=self.raw_audio_subscription_path)
                logging.info(f"Successfully verified raw audio subscription: {self.raw_audio_subscription_path}")
            except google.api_core.exceptions.NotFound:
                raw_audio_topic_name = getattr(kc, 'PUBSUB_RAW_AUDIO_TOPIC', 'UNKNOWN_RAW_AUDIO_TOPIC')
                logging.error(f"Pre-configured Pub/Sub raw audio subscription '{self.raw_audio_subscription_path}' not found on GCP.")
                logging.error(f"Please ensure the subscription '{kc.PUBSUB_RAW_AUDIO_SUBSCRIPTION}' exists in project '{kc.GCP_PROJECT_ID}' and is linked to topic '{raw_audio_topic_name}'.")
                raise
            except Exception as e:
                logging.error(f"Error verifying raw audio subscription {self.raw_audio_subscription_path}: {e}")
                raise

        except Exception as e:
            logging.error(f"Failed to initialize Pub/Sub subscriber for raw audio: {e}")
            self.raw_audio_subscriber_client = None
            self.raw_audio_subscription_path = None
            raise

    def _raw_audio_notification_callback(self, message: pubsub_v1.subscriber.message.Message) -> None:
        """Callback function for processing raw audio Pub/Sub messages."""
        try:
            data_str = message.data.decode("utf-8")
            logging.debug(f"Received raw audio Pub/Sub message ID: {message.message_id}, Data: {data_str[:150]}...")

            try:
                notification_data = json.loads(data_str)
                # Removed: logging.info(f"Parsed raw audio notification: {notification_data}")

                data_reference_type = notification_data.get("data_reference_type")
                gcs_uri = notification_data.get("data_reference")

                if data_reference_type == "gcs_uri" and gcs_uri:
                    # Removed: logging.info(f"Processing GCS URI: {gcs_uri}")
                    # logging.debug(f"Received GCS URI for audio chunk: {gcs_uri}") # Keep as debug for troubleshooting
                    
                    if not hasattr(self, 'storage_client') or self.storage_client is None:
                        logging.error("Storage client not initialized. Cannot download from GCS.")
                        message.nack() # Nack if we can't process
                        return

                    try:
                        parsed_uri = urlparse(gcs_uri)
                        if parsed_uri.scheme != "gs":
                            logging.error(f"Invalid GCS URI scheme: {gcs_uri}")
                            message.ack() # Ack to prevent reprocessing invalid URI
                            return

                        bucket_name = parsed_uri.netloc
                        blob_name = parsed_uri.path.lstrip('/')
                        
                        if not bucket_name or not blob_name:
                            logging.error(f"Could not parse bucket or blob name from GCS URI: {gcs_uri}")
                            message.ack() # Ack to prevent reprocessing malformed URI
                            return

                        # logging.info(f"Attempting to download from GCS: bucket='{bucket_name}', blob='{blob_name}'") # Reduced
                        bucket = self.storage_client.bucket(bucket_name)
                        blob = bucket.blob(blob_name)
                        audio_chunk_bytes = blob.download_as_bytes()
                        # Removed: logging.info(f"Successfully downloaded {len(audio_chunk_bytes)} bytes from GCS.")

                        # Removed: logging.info(f"[RAW_AUDIO_CB] Current self.in_conversation: {self.in_conversation}. Audio queue available: {hasattr(self, 'audio_queue')}")
                        if self.in_conversation and hasattr(self, 'audio_queue'):
                            self.audio_queue.put(audio_chunk_bytes)
                            if not self.logged_first_audio_chunk_for_convo:
                                logging.info(f"Receiving audio data for STT (conversation: {self.conversation_id}). First chunk: {blob_name} ({len(audio_chunk_bytes)} bytes).")
                                self.logged_first_audio_chunk_for_convo = True
                            # No per-chunk log here unless DEBUG is enabled for the earlier GCS URI log
                        else:
                            logging.warning(f"[RAW_AUDIO_CB] NOT QUEUING audio {blob_name}. Convo: {self.in_conversation}, Q_exists: {hasattr(self, 'audio_queue')}")
                        
                        message.ack() # Acknowledge after successful processing

                    except google.api_core.exceptions.GoogleAPIError as e:
                        logging.error(f"GCS API error downloading {gcs_uri}: {e}")
                        message.nack() # Nack to allow for potential retry
                    except Exception as e:
                        logging.error(f"Unexpected error downloading/processing {gcs_uri}: {e}")
                        message.nack() # Nack for unexpected errors

                elif data_reference_type == "base64_encoded_audio":
                    # This part remains as a potential future or alternative handling path
                    logging.info("Received base64 encoded audio data (handling not implemented here for GCS focus).")
                    # audio_data_base64 = notification_data.get("audio_data")
                    # if self.in_conversation and hasattr(self, 'audio_queue') and audio_data_base64:
                    #     audio_chunk_bytes = base64.b64decode(audio_data_base64)
                    #     self.audio_queue.put(audio_chunk_bytes)
                    #     logging.info("Base64 audio chunk placed in STT queue.")
                    message.ack() # Ack if we understand the type but choose not to process further here
                else:
                    logging.warning(f"Unknown or unhandled data_reference_type: '{data_reference_type}'. Message data: {notification_data}")
                    message.ack() # Ack to prevent reprocessing unknown types

            except json.JSONDecodeError as e:
                logging.error(f"Failed to decode JSON from raw audio Pub/Sub message: {e}. Data: '{data_str}'")
                message.ack() # Ack because the message is malformed and cannot be retried
            except Exception as e:
                logging.error(f"Error processing raw audio Pub/Sub message data: {e}")
                message.nack() # Nack for other processing errors

        except Exception as e:
            logging.error(f"Critical error in _raw_audio_notification_callback: {e}")
            # It's often safer not to nack here if the error is in the callback's own logic
            # rather than message content, to avoid infinite redelivery loops.
            # However, if the message itself might be causing the issue, nack might be appropriate.
            # For now, let's assume the error is in our logic and avoid nack.
            # If message.ack() hasn't been called, it will eventually redeliver.
            # If an ack/nack is needed here, it depends on the nature of 'e'.
            # For simplicity, we'll rely on prior ack/nack calls or Pub/Sub redelivery.

    def _initialize_pubsub_subscriber(self):
        """Initializes the Pub/Sub subscriber for wake word events using a pre-defined subscription."""
        try:
            self.subscriber_client = pubsub_v1.SubscriberClient()
            
            if not kc.PUBSUB_WAKE_WORD_SUBSCRIPTION:
                logging.error("PUBSUB_WAKE_WORD_SUBSCRIPTION not configured in kokoro_config.py!")
                raise ValueError("Pub/Sub wake word subscription name not configured.")

            self.subscription_path = self.subscriber_client.subscription_path(
                kc.GCP_PROJECT_ID,
                kc.PUBSUB_WAKE_WORD_SUBSCRIPTION
            )
            logging.info(f"Will use existing Pub/Sub subscription: {self.subscription_path}")

            # Verify the subscription exists (optional, but good practice)
            try:
                self.subscriber_client.get_subscription(subscription=self.subscription_path)
                logging.info(f"Successfully verified subscription: {self.subscription_path}")
            except google.api_core.exceptions.NotFound:
                logging.error(f"Pre-configured Pub/Sub subscription '{self.subscription_path}' not found on GCP.")
                logging.error(f"Please ensure the subscription '{kc.PUBSUB_WAKE_WORD_SUBSCRIPTION}' exists in project '{kc.GCP_PROJECT_ID}' and is linked to topic '{kc.PUBSUB_WAKE_WORD_TOPIC}'.")
                raise
            except Exception as e:
                logging.error(f"Error verifying subscription {self.subscription_path}: {e}")
                raise

        except Exception as e:
            logging.error(f"Failed to initialize Pub/Sub subscriber with pre-defined subscription: {e}")
            self.subscriber_client = None
            raise

    def _wake_word_callback(self, message: pubsub_v1.subscriber.message.Message) -> None:
        """Callback function for processing Pub/Sub messages."""
        try:
            message.ack()
            data_str = message.data.decode("utf-8")
            logging.info(f"Received Pub/Sub message: {message.message_id}, data: {data_str}")
            
            try:
                event_data = json.loads(data_str)
                logging.info(f"Parsed wake word event data: {event_data}")
                # For now, any message on this topic is considered a wake word signal.
                # Add more specific checks on event_data if needed.
                if not self.is_speaking: # Only set wake word if not currently speaking
                    self.conversation_id = str(uuid.uuid4()) # Generate new conversation ID
                    logging.info(f"[WAKE_WORD_CB] New conversation started. ID: {self.conversation_id}")
                    self.in_conversation = True # Set conversation state
                    self.logged_first_audio_chunk_for_convo = False # Reset for new convo
                    self.wake_word_detected.set()
                    self._send_visual_state_to_blender(AgentVisualState.LISTENING.value)
                    # Tell Pi to start listening for speech, AND SEND THE CONVERSATION ID
                    control_payload = {"conversation_id": self.conversation_id}
                    self._publish_convo_control_message("START_LISTENING_SPEECH", payload=control_payload) # Pass payload
                else:
                    logging.info("Wake word received while speaking, ignoring for now.")
            except json.JSONDecodeError as e:
                logging.error(f"Failed to decode JSON from Pub/Sub message: {e}. Data: '{data_str}'")
            except Exception as e:
                logging.error(f"Error processing Pub/Sub message data: {e}")
        except Exception as e:
            logging.error(f"Error in _wake_word_callback: {e}")

    def _publish_convo_control_message(self, command: str, payload: dict = None):
        """Publishes a message to the conversation control topic."""
        if not self.publisher_client or not self.convo_control_topic_path:
            logging.warning(f"Cannot publish convo control message. Publisher or topic path not initialized. Command: {command}")
            return

        message_data = {
            "message_id": str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "command": command,
        }
        if payload:
            message_data["payload"] = payload
        
        message_bytes = json.dumps(message_data).encode("utf-8")
        
        try:
            # logging.info(f"Publishing convo control message: {command} with payload: {payload} to {self.convo_control_topic_path}")
            future = self.publisher_client.publish(self.convo_control_topic_path, data=message_bytes)
            # Making it non-blocking, add callback for logging
            def _callback(future_obj):
                try:
                    message_id_result = future_obj.result(timeout=5)
                    logging.debug(f"[PubSubAck] Convo control '{command}' published. Msg ID: {message_id_result}")
                except TimeoutError:
                    logging.warning(f"[PubSubAck] Timeout publishing convo control '{command}'.")
                except Exception as e_cb:
                    logging.error(f"[PubSubAck] Error on convo control publish for '{command}': {e_cb}")
            future.add_done_callback(_callback)
            logging.info(f"Initiated publish of convo control message: {command} with payload: {payload}")

        except Exception as e:
            logging.error(f"Error initiating convo control publish for '{command}': {e}", exc_info=True)

    def _send_visual_state_to_blender(self, state: str):
        """Publishes the agent's visual state to Blender."""
        if not self.publisher_client or not self.blender_animation_topic_path:
            logging.warning(f"Cannot send visual state. Publisher or Blender animation topic path not initialized. State: {state}")
            return

        message_data = {
            "message_id": str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "command_type": "set_visual_state",
            "state": state,
            "conversation_id": self.conversation_id
        }
        message_bytes = json.dumps(message_data).encode("utf-8")

        try:
            future = self.publisher_client.publish(self.blender_animation_topic_path, data=message_bytes)
            
            def _callback(future_obj):
                try:
                    message_id_result = future_obj.result(timeout=5)
                    logging.info(f"Visual state '{state}' published to Blender. Msg ID: {message_id_result}")
                except TimeoutError:
                    logging.warning(f"Timeout publishing visual state '{state}' to Blender.")
                except Exception as e_cb:
                    logging.error(f"Error on visual state publish for '{state}' to Blender: {e_cb}")
            future.add_done_callback(_callback)
            # logging.debug(f"Initiated publish of visual state: {state} with payload: {message_data}")
        except Exception as e:
            logging.error(f"Error initiating visual state publish for '{state}' to Blender: {e}", exc_info=True)

    def start_transcription(self):
        """Start Google Cloud Speech-to-Text streaming"""
        if hasattr(self, 'transcription_thread') and self.transcription_thread.is_alive():
            logging.warning("Transcription thread already running. Not starting a new one.")
            return

        self.audio_queue = queue.Queue()
        self.transcription_complete = False # Reset before starting
        self.latest_transcription = ""    # Reset before starting
        self.transcription_thread = Thread(target=self.process_audio_stream, args=(self.audio_queue,))
        self.transcription_thread.daemon = True
        self.transcription_thread.start()
        logging.info("Google Cloud Speech-to-Text streaming started")

    def stop_transcription(self):
        """Stop Google Cloud Speech-to-Text streaming"""
        if hasattr(self, 'transcription_thread') and self.transcription_thread.is_alive():
            logging.info("Stopping Google Cloud Speech-to-Text streaming...")
            if hasattr(self, 'audio_queue'):
                 try:
                     self.audio_queue.put(None, block=False, timeout=1.0)  # Signal thread to stop
                 except queue.Full:
                     logging.warning("Audio queue full while trying to signal stop to transcription thread.")
                 except Exception as e: # Catch any other exception during put
                     logging.warning(f"Error putting None in audio queue to stop transcription: {e}")

            self.transcription_thread.join(timeout=3.0) # Increased timeout slightly
            if self.transcription_thread.is_alive():
                logging.warning("Transcription thread did not stop gracefully after signal and join.")
            else:
                logging.info("Google Cloud Speech-to-Text streaming stopped.")
        else:
            logging.info("Transcription thread already stopped or not started.")
        
        # Reset transcription state flags regardless of thread state
        self.transcription_complete = False
        # self.latest_transcription = "" # DO NOT CLEAR HERE - let it hold the last value until a new transcription starts
        # Clean up queue if it exists
        if hasattr(self, 'audio_queue'):
            # Ensure the queue is empty before deleting, or just let it be GC'd
            # Forcing queue to empty:
            if self.audio_queue:
                while not self.audio_queue.empty():
                    try:
                        self.audio_queue.get_nowait()
                    except queue.Empty:
                        break
            # del self.audio_queue # Or let it be handled by start_transcription re-init


    def process_audio_stream(self, audio_queue):
        """Process audio stream with Google Cloud Speech-to-Text"""
        client = None
        responses = None
        try:
            client = speech.SpeechClient()
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=kc.CAPTURE_RATE, 
                language_code="en-US",
                enable_automatic_punctuation=True
            )
            streaming_config = speech.StreamingRecognitionConfig(
                config=config,
                interim_results=True,
                single_utterance=False # Changed to False to allow continuous streaming until explicitly stopped
            )

            def request_stream():
                while not self.stop_event.is_set(): # Check stop_event
                    try:
                        # Timeout helps prevent blocking indefinitely if queue remains empty
                        # and allows the loop to check self.stop_event periodically.
                        content = audio_queue.get(timeout=0.5)
                        if content is None: # Sentinel value to stop
                            logging.info("[STT RequestStream] Received None, stopping.")
                            break
                        logging.debug(f"[STT RequestStream] Yielding audio chunk of size {len(content)}")
                        yield speech.StreamingRecognizeRequest(audio_content=content)
                    except queue.Empty:
                        logging.debug("[STT RequestStream] Queue empty, continuing...")
                        # This is expected if no audio is being pushed.
                        # Loop continues to check self.stop_event or wait for new audio.
                        continue
                    except Exception as e:
                        logging.error(f"[STT RequestStream] Error getting audio from queue: {e}")
                        break # Exit loop on other errors
                logging.debug("Request stream generator finished.")


            requests = request_stream()
            responses = client.streaming_recognize(streaming_config, requests)

            logging.info("Waiting for STT responses...")
            for response in responses:
                if self.stop_event.is_set(): # Check if stop was signaled externally
                    logging.info("Stop event set, breaking STT response loop.")
                    break
                if not response.results:
                    continue
                result = response.results[0]
                if not result.alternatives:
                    continue
                transcript = result.alternatives[0].transcript
                if result.is_final:
                    self.latest_transcription = transcript
                    self.transcription_complete = True # Signal completion
                    logging.info(f"Final transcription: '{transcript}'")
                    # Do not break here, let the stream close naturally or by sentinel
                else:
                    logging.debug(f"Interim transcription: '{transcript}'")
            logging.info("STT response loop finished.")
        except google.api_core.exceptions.OutOfRange:
            logging.info("STT stream closed by Google (OutOfRange), likely due to silence or end of audio.")
            # This is a normal way for the stream to end if single_utterance=True or if Google detects end.
            # If single_utterance=False, this might mean Google's internal VAD decided the utterance ended.
            # We should ensure our own logic handles this gracefully.
            if not self.transcription_complete: # If we haven't already set it from a final result
                self.transcription_complete = True # Mark as complete so the main loop can process any partial transcript
                logging.info("Marking transcription_complete=True due to OutOfRange with no prior final result.")
        except Exception as e:
            logging.error(f"Transcription thread error: {e}")
            import traceback
            logging.error(traceback.format_exc())
            if not self.transcription_complete: # Ensure main loop can proceed on error
                self.transcription_complete = True
                logging.info("Marking transcription_complete=True due to an exception in STT processing.")
        finally:
            # Ensure transcription_complete is True if the loop exits, so the main agent loop doesn't hang.
            # This is especially important if the audio_queue.get() loop in request_stream() breaks.
            if not self.transcription_complete:
                self.transcription_complete = True
                logging.info("Ensuring transcription_complete is True in finally block of process_audio_stream.")
            logging.info("Transcription processing in process_audio_stream finished.")


    def reset_audio_state(self):
        """Reset transcription state for a new turn or wake word."""
        logging.info("Resetting transcription state...")
        # Store the last transcription before stopping, in case stop_transcription clears it (though we changed it not to)
        # temp_last_transcription = self.latest_transcription
        self.stop_transcription() # This will set transcription_complete to False

        # latest_transcription should be reset by start_transcription
        # self.latest_transcription = "" # Ensure it's cleared before a new attempt if not done by start_transcription

        # A short delay can be helpful for resources to release, if necessary.
        time.sleep(0.2) # Slightly increased delay
        self.start_transcription() # This will re-initialize queue, flags, and self.latest_transcription
        logging.info("Transcription state reset complete.")

    def _calculate_rms(self, audio_data_segment):
        """Helper to calculate RMS for an audio segment."""
        if not audio_data_segment.any(): # Check if array is not empty
            return 0.0
        return np.sqrt(np.mean(audio_data_segment**2))

    def generate_amplitude_data_and_publish(self, audio_file_path, chunk_duration_ms=50):
        """
        Analyzes a WAV audio file for its amplitude (RMS) over time and publishes this data.
        No longer uses Rhubarb or dialogue_text.
        """
        perf_overall_start_time = time.perf_counter()
        logging.info(f"[PERF] generate_amplitude_data started for audio: {audio_file_path}")

        if not os.path.exists(audio_file_path):
            logging.error(f"Audio file {audio_file_path} not found for amplitude analysis.")
            return False

        amplitude_data_points = []
        analysis_success = False
        try:
            audio_signal, samplerate = sf.read(audio_file_path, dtype='float32')
            if len(audio_signal.shape) > 1: # If stereo, take the first channel
                audio_signal = audio_signal[:, 0]
            
            frames_per_chunk = int(samplerate * (chunk_duration_ms / 1000.0))
            num_chunks = int(np.ceil(len(audio_signal) / frames_per_chunk))
            
            logging.debug(f"Audio Signal Length: {len(audio_signal)}, Samplerate: {samplerate}, Frames per chunk: {frames_per_chunk}, Num Chunks: {num_chunks}")

            for i in range(num_chunks):
                start_frame = i * frames_per_chunk
                end_frame = start_frame + frames_per_chunk
                chunk = audio_signal[start_frame:end_frame]
                
                if len(chunk) == 0: continue # Skip empty trailing chunk

                rms_amplitude = self._calculate_rms(chunk)
                # Normalize RMS, assuming float32 audio is typically in [-1.0, 1.0]. Max RMS is ~0.707 for sine.
                # This normalization might need tuning based on typical audio levels.
                normalized_amplitude = min(rms_amplitude * 4.0, 1.0) # Amplified by 2.0 (original 2.0 * user factor 2.0 = 4.0)
                
                timestamp = (start_frame + frames_per_chunk / 2) / samplerate # Midpoint of chunk
                # Ensure conversion to standard Python float for JSON serialization
                amplitude_data_points.append({"time": round(float(timestamp), 3), "amplitude": round(float(normalized_amplitude), 3)})
            
            logging.info(f"Amplitude analysis completed. Generated {len(amplitude_data_points)} data points.")
            analysis_success = True

        except Exception as e:
            logging.error(f"Error during amplitude analysis for {audio_file_path}: {e}", exc_info=True)
        
        analysis_duration = time.perf_counter() - perf_overall_start_time # Includes file read
        logging.info(f"[PERF] Amplitude analysis took: {analysis_duration:.4f}s. Success: {analysis_success}")

        if not analysis_success or not amplitude_data_points:
            logging.error("Amplitude analysis failed or produced no data points.")
            return False

        # Publish amplitude data
        publish_initiated_success = False
        if self.publisher_client and self.blender_lip_sync_topic_path: # Reusing lip_sync topic for amplitude
            message_payload = {
                "message_id": str(uuid.uuid4()),
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "type": "amplitude_data", # New message type
                "data_points": amplitude_data_points, # List of {"time": t, "amplitude": amp}
                "audio_ref": os.path.basename(audio_file_path),
                "conversation_id": self.conversation_id
            }
            message_bytes = json.dumps(message_payload).encode("utf-8")
            
            pub_init_start_time = time.perf_counter()
            try:
                future = self.publisher_client.publish(self.blender_lip_sync_topic_path, data=message_bytes)
                def _pubsub_callback(future_obj):
                    try:
                        message_id_result = future_obj.result(timeout=5)
                        logging.debug(f"[PubSubAck] Amplitude data published to {self.blender_lip_sync_topic_path}. Msg ID: {message_id_result}")
                    except TimeoutError:
                        logging.warning(f"[PubSubAck] Timeout confirming amplitude data publish to {self.blender_lip_sync_topic_path}.")
                    except Exception as e_callback:
                        logging.error(f"[PubSubAck] Error on amplitude data publish confirmation for {self.blender_lip_sync_topic_path}: {e_callback}", exc_info=True)
                future.add_done_callback(_pubsub_callback)
                pub_init_duration = time.perf_counter() - pub_init_start_time
                logging.info(f"[PERF] Amplitude data publish initiated (took {pub_init_duration:.4f}s). Topic: {self.blender_lip_sync_topic_path}")
                publish_initiated_success = True
            except Exception as e_pub:
                logging.error(f"Error initiating amplitude data publish to {self.blender_lip_sync_topic_path}: {e_pub}", exc_info=True)
        else:
            logging.warning("Publisher client or Blender lip sync topic path not initialized. Cannot publish amplitude data.")

        perf_overall_duration_total = time.perf_counter() - perf_overall_start_time
        logging.info(f"[PERF] generate_amplitude_data_and_publish finished. Analysis success: {analysis_success}, Publish initiated: {publish_initiated_success}. Total time: {perf_overall_duration_total:.4f}s")
        return publish_initiated_success

    def run_blender_scripts(self): # This method will now primarily handle blinking.
        """Publishes a blink command to Blender (non-blocking)."""
        perf_start_time = time.perf_counter()
        if not self.publisher_client or not self.blender_animation_topic_path:
            logging.warning("Publisher client or Blender animation topic path not initialized. Cannot send blink command.")
            return

        command_payload = {
            "message_id": str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "command_type": "blink",
            "conversation_id": self.conversation_id
        }
        message_bytes = json.dumps(command_payload).encode("utf-8")

        try:
            future = self.publisher_client.publish(self.blender_animation_topic_path, data=message_bytes)
            def _callback(future_obj):
                try:
                    message_id_result = future_obj.result(timeout=5)
                    logging.debug(f"[PubSubAck] Blink command published. Msg ID: {message_id_result}")
                except TimeoutError:
                    logging.warning(f"[PubSubAck] Timeout publishing blink command.")
                except Exception as e_cb:
                    logging.error(f"[PubSubAck] Error on blink command publish: {e_cb}")
            future.add_done_callback(_callback)
            perf_duration = time.perf_counter() - perf_start_time
            logging.info(f"[PERF] Blink command publish initiated (took {perf_duration:.4f}s).")
        except Exception as e:
            perf_duration = time.perf_counter() - perf_start_time
            logging.error(f"[PERF] Error initiating blink command publish (took {perf_duration:.4f}s): {e}", exc_info=True)

    def play_blender_animation(self, animation_name="idle_01"):
        """Publishes a play_animation command to Blender (non-blocking)."""
        perf_start_time = time.perf_counter()
        if not self.publisher_client or not self.blender_animation_topic_path:
            logging.warning(f"Publisher client or Blender animation topic path not initialized. Cannot send play_animation '{animation_name}'.")
            return

        command_payload = {
            "message_id": str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "command_type": "play_animation",
            "animation_name": animation_name,
            "conversation_id": self.conversation_id
        }
        message_bytes = json.dumps(command_payload).encode("utf-8")

        try:
            future = self.publisher_client.publish(self.blender_animation_topic_path, data=message_bytes)
            def _callback(future_obj):
                try:
                    message_id_result = future_obj.result(timeout=5)
                    logging.debug(f"[PubSubAck] Play_animation '{animation_name}' published. Msg ID: {message_id_result}")
                except TimeoutError:
                    logging.warning(f"[PubSubAck] Timeout publishing play_animation '{animation_name}'.")
                except Exception as e_cb:
                    logging.error(f"[PubSubAck] Error on play_animation '{animation_name}' publish: {e_cb}")
            future.add_done_callback(_callback)
            perf_duration = time.perf_counter() - perf_start_time
            logging.info(f"[PERF] Play_animation '{animation_name}' publish initiated (took {perf_duration:.4f}s).")
        except Exception as e:
            perf_duration = time.perf_counter() - perf_start_time
            logging.error(f"[PERF] Error initiating play_animation '{animation_name}' publish (took {perf_duration:.4f}s): {e}", exc_info=True)

    def pre_generate_tts_audio(self, text, audio_file_path):
        """Generate TTS audio using Google Cloud Text-to-Speech and save it to a file."""
        logging.info(f"Generating TTS audio for text: '{text}' using Google Cloud TTS ({TTS_VOICE_NAME})")
        start_time = time.time()

        if not self.tts_client:
            logging.error("TTS client is not initialized.")
            raise RuntimeError("TTS client not initialized.")

        synthesis_input = texttospeech.SynthesisInput(text=text)
        voice = texttospeech.VoiceSelectionParams(
            language_code=TTS_LANGUAGE_CODE, name=TTS_VOICE_NAME
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16, 
            sample_rate_hertz=TTS_SAMPLE_RATE_HZ 
        )

        try:
            response = self.tts_client.synthesize_speech(
                input=synthesis_input, voice=voice, audio_config=audio_config
            )
            api_call_duration = time.time() - start_time
            logging.info(f"Google TTS API call successful ({api_call_duration:.2f}s). Received {len(response.audio_content)} bytes.")

            # Save the audio content to the specified file
            try:
                with open(audio_file_path, "wb") as out:
                    out.write(response.audio_content)
                logging.info(f"Audio content written to file: {audio_file_path}")
                
                # Get playback duration
                try:
                    data, samplerate = sf.read(audio_file_path)
                    duration = len(data) / samplerate
                    logging.info(f"Generated audio duration: {duration:.2f} seconds.")
                    return duration
                except Exception as e:
                    logging.error(f"Could not read duration from generated audio file {audio_file_path}: {e}")
                    return None # Or a default duration, or re-raise

            except Exception as e:
                logging.error(f"Failed to write TTS audio to file {audio_file_path}: {e}")
                raise
        except Exception as e:
            logging.error(f"Google Cloud TTS API call failed: {e}")
            raise
        return None # Should not be reached if successful and duration is returned

    def stream_audio_to_raspberry_pi(self, audio_file_path, playback_duration):
        """Stream pre-generated audio to an abstracted audio stream."""
        # This method now primarily signals that speaking has started and finished.
        # The actual sending of audio chunks is abstracted via _send_tts_audio_chunk_to_stream
        # which is currently a placeholder.
        # For the purpose of this refactor, we'll simulate the streaming duration.
        
        if not os.path.exists(audio_file_path):
            logging.error(f"Audio file not found for streaming: {audio_file_path}")
            return

        logging.info(f"Starting to 'stream' audio from {audio_file_path} (simulated duration: {playback_duration:.2f}s)")
        self.is_speaking = True
        
        # Simulate reading and sending chunks
        # In a real scenario, this loop would read chunks from the file and send them.
        # For now, we just sleep for the duration.
        # The _send_tts_audio_chunk_to_stream would be called within such a loop.
        
        # Example of how it might look with actual chunking (conceptual)
        # try:
        #     with sf.SoundFile(audio_file_path, 'r') as f:
        #         target_rate = kc.PLAYBACK_RATE 
        #         if f.samplerate != target_rate:
        #             # Resampling logic would be here if needed, or ensure pre_generate_tts_audio produces correct rate
        #             logging.warning(f"Audio sample rate ({f.samplerate} Hz) differs from target streaming rate ({target_rate} Hz). Ensure pre-generation matches.")
        # 
        #         while not self.stop_event.is_set():
        #             audio_chunk = f.read(kc.PLAYBACK_CHUNK_SIZE, dtype='int16')
        #             if not len(audio_chunk): # End of file
        #                 break
        #             # Convert numpy array to bytes if necessary for the stream
        #             audio_chunk_bytes = audio_chunk.tobytes()
        #             self._send_tts_audio_chunk_to_stream(audio_chunk_bytes) 
        #             # Add a small sleep to simulate network latency or processing, if needed
        #             # time.sleep(float(kc.PLAYBACK_CHUNK_SIZE) / target_rate) # Theoretical time for chunk
        # except Exception as e:
        #     logging.error(f"Error during simulated audio streaming from file: {e}")
        # finally:
        #     self.is_speaking = False
        #     logging.info(f"Finished 'streaming' audio from {audio_file_path}")

        # Simplified simulation for now:
        start_time = time.time()
        while (time.time() - start_time) < playback_duration and not self.stop_event.is_set():
            # In a real implementation, chunks would be sent here.
            # self._send_tts_audio_chunk_to_stream(some_chunk_bytes)
            time.sleep(0.05) # Small sleep to allow stop_event check

        self.is_speaking = False
        if self.stop_event.is_set():
            logging.info(f"Audio streaming from {audio_file_path} interrupted by stop event.")
        else:
            logging.info(f"Finished 'streaming' audio from {audio_file_path}")


    def _send_tts_audio_chunk_to_stream(self, audio_chunk_bytes):
        """Placeholder method to send TTS audio chunks to an abstracted stream."""
        # In a real implementation, this would send `audio_chunk_bytes` to the
        # configured output stream (e.g., Pub/Sub topic for TTS audio, UDP, gRPC stream).
        # For now, it just logs.
        try:
            # logging.debug(f"Simulating send of {len(audio_chunk_bytes)} audio bytes to stream.")
            pass # Replace with actual stream sending logic
        except Exception as e:
            logging.error(f"Error in _send_tts_audio_chunk_to_stream: {e}")
            # Potentially set a flag or re-raise if critical

    def _get_stt_audio_frame_from_stream(self):
        """
        Placeholder method to get an audio frame for STT from an abstracted input stream.
        This method is NOT USED in the current Pub/Sub based raw_audio_notification model.
        The `_raw_audio_notification_callback` is responsible for initiating audio fetching
        and queuing it into `self.audio_queue` for `process_audio_stream`.
        """
        # In a direct streaming scenario (e.g., continuous UDP listening for STT),
        # this method would fetch a chunk of audio data.
        # logging.debug("Attempting to get STT audio frame from stream (placeholder).")
        # For example, if listening on a UDP socket for STT audio:
        # try:
        #     data, _ = self.stt_socket.recvfrom(kc.STT_CHUNK_SIZE * 2) # Assuming 16-bit audio
        #     return data
        # except socket.timeout:
        #     return None
        # except Exception as e:
        #     logging.error(f"Error receiving STT audio frame: {e}")
        #     return None
        logging.warning("_get_stt_audio_frame_from_stream is a placeholder and should not be actively used with Pub/Sub audio notifications.")
        return None # Placeholder

    def process_text(self, text):
        """Process transcribed text: get AI response, generate TTS, and manage command publishing."""
        overall_perf_start_time = time.perf_counter()
        logging.info(f"[PROCESS_TEXT] START. Text: '{text}'. Convo ID: {self.conversation_id}")

        if self.stop_event.is_set():
            logging.info("[PROCESS_TEXT] Stop event detected at beginning, skipping processing.")
            return

        logging.info(f"{Fore.GREEN}STT Result: '{text}'{Style.RESET_ALL}")

        # If text is empty, the decision to go to wake word is now handled in the run() loop
        # This function will only proceed if there's text.
        if not text or text.isspace():
            logging.warning("[PROCESS_TEXT] Transcribed text is empty. No LLM/TTS processing will occur.")
            # The run() loop will handle sending START_LISTENING_WAKE_WORD to Pi.
            # Ensure self.in_conversation is set to False by the caller (run() loop) if this path is taken.
            return

        # 1. Get AI Response
        self._send_visual_state_to_blender(AgentVisualState.THINKING.value)
        llm_perf_start_time = time.perf_counter()
        ai_response_text = ""
        try:
            raw_llm_response = infer.generate_response(text)
            logging.info(f"{Fore.BLUE}LLM Raw Response: '{raw_llm_response}'{Style.RESET_ALL}")
            ai_response_text = infer.replace_placeholders(raw_llm_response)
            logging.info(f"{Fore.CYAN}AI Processed Response: '{ai_response_text}'{Style.RESET_ALL}")
        except Exception as e:
            logging.error(f"Error getting AI response or processing placeholders: {e}", exc_info=True)
            ai_response_text = "I had a little trouble thinking of a response."
        llm_perf_duration = time.perf_counter() - llm_perf_start_time
        logging.info(f"[PERF] LLM Response & Placeholder Processing took: {llm_perf_duration:.4f}s")

        if self.stop_event.is_set():
            logging.info("[PROCESS_TEXT] Stop event after LLM. Ending turn.")
            if self.in_conversation: # Check if still in conversation before sending wake word command
                self._send_visual_state_to_blender(AgentVisualState.LISTENING.value)
                logging.info("[PROCESS_TEXT DEBUG] Sending START_LISTENING_WAKE_WORD due to stop_event after LLM.")
                self._publish_convo_control_message("START_LISTENING_WAKE_WORD")
                self.in_conversation = False # Explicitly end conversation here
            return

        # 2. Generate TTS audio locally
        self._send_visual_state_to_blender(AgentVisualState.TALKING.value)
        tts_gen_perf_start_time = time.perf_counter()
        timestamp_str = str(time.time()).replace('.', '_')
        temp_audio_file = f"/tmp/response_{timestamp_str}.wav"
        playback_duration_from_tts = None
        tts_success = False
        try:
            playback_duration_from_tts = self.pre_generate_tts_audio(ai_response_text, temp_audio_file)
            if playback_duration_from_tts is not None and os.path.exists(temp_audio_file):
                logging.debug(f"TTS audio generated for: '{ai_response_text}', File: {temp_audio_file}, Duration: {playback_duration_from_tts:.2f}s")
                tts_success = True
            else:
                logging.error("[PROCESS_TEXT] Failed to generate TTS audio or get its duration (or file not found).")
        except Exception as e:
            logging.error(f"Exception during TTS pre-generation: {e}", exc_info=True)
        
        tts_gen_perf_duration = time.perf_counter() - tts_gen_perf_start_time
        logging.info(f"[PERF] TTS Generation (pre_generate_tts_audio) took: {tts_gen_perf_duration:.4f}s. Success: {tts_success}")

        if not tts_success:
            logging.error("[PROCESS_TEXT] TTS generation failed. Ending turn.")
            if os.path.exists(temp_audio_file):
                try: os.remove(temp_audio_file)
                except Exception as e_rem: logging.warning(f"Could not remove temp audio file {temp_audio_file} after TTS failure: {e_rem}")
            if self.in_conversation:
                self.in_conversation = False
                self._send_visual_state_to_blender(AgentVisualState.LISTENING.value)
                logging.info("[PROCESS_TEXT DEBUG] Sending START_LISTENING_WAKE_WORD due to TTS generation failure.")
                self._publish_convo_control_message("START_LISTENING_WAKE_WORD")
            return

        if self.stop_event.is_set():
            logging.info("[PROCESS_TEXT] Stop event after TTS generation. Ending turn.")
            if self.in_conversation:
                self._send_visual_state_to_blender(AgentVisualState.LISTENING.value)
                logging.info("[PROCESS_TEXT DEBUG] Sending START_LISTENING_WAKE_WORD due to stop_event after TTS generation.")
                self._publish_convo_control_message("START_LISTENING_WAKE_WORD")
                self.in_conversation = False # Explicitly end conversation here
            if os.path.exists(temp_audio_file):
                try: os.remove(temp_audio_file)
                except Exception: pass
            return

        # 3. Generate Amplitude Data and Initiate Blender Commands (Amplitude, Blink)
        if os.path.exists(temp_audio_file):
            amplitude_data_published = self.generate_amplitude_data_and_publish(temp_audio_file)
            if amplitude_data_published:
                logging.debug("[PROCESS_TEXT] Amplitude data generation and Pub/Sub dispatch initiated.")
            else:
                logging.warning("[PROCESS_TEXT] Amplitude data generation or Pub/Sub dispatch failed/skipped.")
            self.run_blender_scripts()
        else:
            logging.error(f"[PROCESS_TEXT] Temp audio file {temp_audio_file} missing before phoneme/blink stage. Skipping these.")

        # 4. Upload TTS to GCS (blocking)
        gcs_upload_perf_start_time = time.perf_counter()
        gcs_uri = None
        gcs_upload_success = False
        if os.path.exists(temp_audio_file):
            try:
                logging.debug(f"Attempting GCS upload for: {temp_audio_file}")
                tts_audio_gcs_object_name = f"tts_output_audio/{datetime.utcnow().strftime('%Y/%m/%d/%H')}/{uuid.uuid4()}.wav"
                if not kc.KOKORO_AUDIO_CHUNKS_GCS_BUCKET:
                    logging.error("KOKORO_AUDIO_CHUNKS_GCS_BUCKET not configured. Cannot upload to GCS.")
                else:
                    bucket = self.storage_client.bucket(kc.KOKORO_AUDIO_CHUNKS_GCS_BUCKET)
                    blob = bucket.blob(tts_audio_gcs_object_name)
                    blob.upload_from_filename(temp_audio_file)
                    gcs_uri = f"gs://{kc.KOKORO_AUDIO_CHUNKS_GCS_BUCKET}/{tts_audio_gcs_object_name}"
                    logging.info(f"Successfully uploaded TTS audio to GCS: {gcs_uri}")
                    gcs_upload_success = True
            except Exception as e_gcs:
                logging.error(f"Error during TTS GCS upload: {e_gcs}", exc_info=True)
        else:
            logging.error(f"[PROCESS_TEXT] Temp audio file {temp_audio_file} missing before GCS upload. Cannot upload.")
            
        gcs_upload_perf_duration = time.perf_counter() - gcs_upload_perf_start_time
        logging.info(f"[PERF] GCS Upload of TTS took: {gcs_upload_perf_duration:.4f}s. Success: {gcs_upload_success}")

        # 5. Notify Pi about the TTS audio (non-blocking Pub/Sub)
        if gcs_upload_success and gcs_uri:
            pi_notify_perf_start_time = time.perf_counter()
            pi_message_data = {
                "message_id": str(uuid.uuid4()), "timestamp": datetime.utcnow().isoformat() + "Z",
                "type": "tts_audio_ready", "data_reference_type": "gcs_uri", "data_reference": gcs_uri,
                "metadata": {
                    "conversation_id": self.conversation_id, "text_synthesized": ai_response_text,
                    "playback_duration_seconds": playback_duration_from_tts
                }
            }
            pi_message_bytes = json.dumps(pi_message_data).encode("utf-8")
            
            if self.publisher_client and self.tts_output_topic_path:
                future = self.publisher_client.publish(self.tts_output_topic_path, data=pi_message_bytes)
                def _pi_pub_callback(future_obj):
                    try:
                        msg_id = future_obj.result(timeout=5)
                        logging.debug(f"[PubSubAck] TTS GCS URI for Pi published. Msg ID: {msg_id}")
                    except TimeoutError: logging.warning(f"[PubSubAck] Timeout publishing TTS GCS URI for Pi.")
                    except Exception as e_cb: logging.error(f"[PubSubAck] Error on TTS GCS URI for Pi publish: {e_cb}", exc_info=True)
                future.add_done_callback(_pi_pub_callback)
                pi_notify_perf_duration = time.perf_counter() - pi_notify_perf_start_time
                logging.info(f"[PERF] TTS GCS URI for Pi publish initiated (took {pi_notify_perf_duration:.4f}s).")
            else:
                logging.error("Pub/Sub client or tts_output_topic_path not initialized for Pi notification.")
        elif not gcs_upload_success and os.path.exists(temp_audio_file):
            logging.error("GCS upload failed, cannot notify Pi about TTS audio.")
        elif not os.path.exists(temp_audio_file) and tts_success:
             logging.error("TTS audio file was missing before GCS upload, cannot notify Pi.")

        # 6. Clean up local TTS file
        if os.path.exists(temp_audio_file):
            try:
                os.remove(temp_audio_file)
                logging.debug(f"Removed temporary TTS audio file: {temp_audio_file}")
            except Exception as e_clean:
                logging.warning(f"Could not remove temporary TTS audio file {temp_audio_file}: {e_clean}")
        
        # After successful turn processing (or if stop_event is not set before this point),
        # agent is now listening for next input or wake word.
        if not self.stop_event.is_set():
            self._send_visual_state_to_blender(AgentVisualState.LISTENING.value)
            logging.info("[PROCESS_TEXT MODIFIED] Successfully processed text. Setting in_conversation to False to return to wake word listening.")
            self.in_conversation = False

        if self.stop_event.is_set():
            logging.info("[PROCESS_TEXT] Stop event set at/near end of processing. Ensuring Pi resets if convo was active.")
            if self.in_conversation: # Check if still in conversation before sending wake word command
                 self._send_visual_state_to_blender(AgentVisualState.LISTENING.value)
                 logging.info("[PROCESS_TEXT DEBUG] Sending START_LISTENING_WAKE_WORD due to stop_event at end of process_text.")
                 self._publish_convo_control_message("START_LISTENING_WAKE_WORD")
                 self.in_conversation = False # Explicitly end conversation here
        
        overall_perf_duration = time.perf_counter() - overall_perf_start_time
        logging.info(f"[PERF] process_text finished. Total time: {overall_perf_duration:.4f}s")

        if self.stop_event.is_set(): # Final check, ensures return if stop_event was set during final stages
            logging.info("Stop event was set during process_text. Final check before return.")
            # temp_audio_file should be cleaned up.
            # If self.in_conversation was true and stop_event is set, START_LISTENING_WAKE_WORD was already sent.
            return

        logging.debug("Finished processing text and audio response within process_text.")
        logging.debug("Agent will remain ready for next user utterance if RPi client sends it and conversation is active.")


    def run(self):
        logging.info("Main script activated. Initializing Pub/Sub listener for wake word...")
        if not self.subscriber_client or not self.subscription_path:
            logging.error("Pub/Sub subscriber for wake word not initialized. Cannot start listening.")
            return
        if not self.raw_audio_subscriber_client or not self.raw_audio_subscription_path:
            logging.error("Pub/Sub subscriber for raw audio not initialized. Cannot start listening for audio notifications.")
            return

        try:
            self.streaming_pull_future = self.subscriber_client.subscribe(
                self.subscription_path, callback=self._wake_word_callback
            )
            logging.info(f"Listening for wake word messages on {self.subscription_path}...")
        except Exception as e:
            logging.error(f"Failed to subscribe to wake word Pub/Sub topic: {e}")
            return 

        try:
            self.raw_audio_streaming_pull_future = self.raw_audio_subscriber_client.subscribe(
                self.raw_audio_subscription_path, callback=self._raw_audio_notification_callback
            )
            logging.info(f"Listening for raw audio notifications on {self.raw_audio_subscription_path}...")
        except Exception as e:
            logging.error(f"Failed to subscribe to raw audio notification Pub/Sub topic: {e}")
            if self.streaming_pull_future:
                self.streaming_pull_future.cancel()
                try: self.streaming_pull_future.result(timeout=10)
                except: pass
            return

        # Removed initial command to RPi: START_LISTENING_WAKE_WORD
        logging.info("AI Agent started. RPi client should be started separately and will initiate conversation via wake word.")

        try:
            while not self.stop_event.is_set():
                logging.info("[RUN] Top of main loop. Waiting for wake word event...")
                
                while not self.wake_word_detected.is_set() and not self.stop_event.is_set():
                    time.sleep(0.1) 

                if self.stop_event.is_set():
                    logging.info("[RUN] Stop event detected while waiting for wake word. Exiting run loop.")
                    break

                # self.in_conversation and self.conversation_id are set by _wake_word_callback
                if self.wake_word_detected.is_set() and self.in_conversation:
                    logging.info(f"[RUN] Wake word processed. Starting conversation ID: {self.conversation_id}")
                    self.wake_word_detected.clear() 
                    
                    # --- Start of a multi-turn conversation loop ---
                    while self.in_conversation and not self.stop_event.is_set():
                        logging.info(f"[RUN] Starting/Continuing conversation turn. Conversation ID: {self.conversation_id}")
                        self.reset_audio_state() 
                        logging.info("[RUN] Agent listening for user input via Pub/Sub raw audio notifications...")
                        
                        stt_turn_start_time = time.time()
                        
                        logging.info(f"[RUN] Starting STT wait loop. self.transcription_complete: {self.transcription_complete}")
                        # Inner STT Wait Loop for current turn
                        while not self.stop_event.is_set(): 
                            if self.transcription_complete:
                                logging.info(f"[RUN] Transcription complete flag is True. Text: '{self.latest_transcription}'.")
                                # Check if the transcript is empty and if we are too early in the turn
                                if not self.latest_transcription.strip() and \
                                   (time.time() - stt_turn_start_time < kc.STT_MIN_TURN_DURATION_BEFORE_EMPTY_ACCEPT_SECONDS):
                                    logging.warning(f"[RUN] Received initial empty transcript quickly ({time.time() - stt_turn_start_time:.2f}s). Waiting longer for user speech.")
                                    self.transcription_complete = False  # Reset to continue waiting
                                    self.latest_transcription = ""       # Clear it
                                    # Continue this inner STT wait loop
                                else:
                                    # Either transcript is not empty, or it's empty but enough time has passed.
                                    logging.info(f"[RUN] Processing STT result. Elapsed time: {time.time() - stt_turn_start_time:.2f}s")
                                    break # Exit STT wait loop to process the transcription
                            
                            if (time.time() - stt_turn_start_time >= STT_TURN_TIMEOUT):
                                logging.warning(f"[RUN] STT turn timed out ({STT_TURN_TIMEOUT}s).")
                                self.stop_transcription() # Ensure STT is stopped
                                self.latest_transcription = "" # Ensure it's empty on timeout
                                self.transcription_complete = True # Mark as complete to proceed
                                break # Exit STT wait loop
                            time.sleep(0.1) # Main STT wait loop polling interval
                        # End of Inner STT Wait Loop
                        
                        if self.stop_event.is_set():
                            logging.info("[RUN] Stop event detected during STT wait. Breaking conversation loop.")
                            self.in_conversation = False # Ensure outer loop terminates
                            break # Break from outer conversation loop
                        
                        logging.info(f"[RUN] Before decision. self.in_conversation: {self.in_conversation}, transcription_complete: {self.transcription_complete}, latest_transcription: '{self.latest_transcription.strip()}'")
                        
                        # *** NEW LOGIC: Decide action based on STT result ***
                        if not self.latest_transcription.strip(): # If STT result is empty or only whitespace
                            logging.info("[RUN DEBUG] STT result is empty. Sending START_LISTENING_WAKE_WORD to Pi.")
                            self._publish_convo_control_message("START_LISTENING_WAKE_WORD", payload={"conversation_id": self.conversation_id})
                            self.in_conversation = False # End this conversation attempt
                            # No call to process_text needed
                        else:
                            # STT has valid text, proceed with LLM and TTS
                            logging.info(f"[RUN] STT has text: '{self.latest_transcription}'. Proceeding with process_text.")
                            self.process_text(self.latest_transcription) 
                        
                        logging.info(f"[RUN] After STT decision/process_text. self.in_conversation is now: {self.in_conversation}")

                        # Check for goodbye phrases to explicitly end the conversation from agent side
                        # This check is now more relevant if process_text was called
                        if self.in_conversation and self.latest_transcription and any(phrase in self.latest_transcription.lower() for phrase in GOODBYE_PHRASES):
                            logging.info(f"[RUN DEBUG] Goodbye phrase detected in '{self.latest_transcription}'. Ending conversation and sending START_LISTENING_WAKE_WORD.")
                            self.in_conversation = False
                            # This will be caught by the next 'if not self.in_conversation'
                        
                        if not self.in_conversation:
                            logging.info(f"[RUN DEBUG] self.in_conversation is False. Ending current conversation turn. latest_transcription was: '{self.latest_transcription.strip()}'. Sending START_LISTENING_WAKE_WORD.")
                            # Ensure Pi is told to go to wake word if not already handled by empty STT result
                            # The previous block for empty STT already sends it. This handles cases like goodbye phrases.
                            self._publish_convo_control_message("START_LISTENING_WAKE_WORD", payload={"conversation_id": self.conversation_id})
                            self._send_visual_state_to_blender(AgentVisualState.LISTENING.value)
                            break # Break from outer conversation loop, go back to waiting for wake word
                        else:
                            logging.info("[RUN] Multi-turn: Conversation active. Ready for next user utterance in same conversation.")
                            # Loop continues in this outer conversation loop for the next turn's STT
                    # --- End of a multi-turn conversation loop ---
                    logging.info(f"[RUN] Exited conversation loop for ID: {self.conversation_id}. Resetting self.in_conversation.")
                    self.in_conversation = False # Ensure it's false before waiting for new wake word
                    self.conversation_id = None
                else: # if not self.wake_word_detected.is_set() (can happen if stop_event breaks the inner wait)
                    logging.info("[RUN] Wake word not detected or cleared before processing. Looping back.")


                time.sleep(0.1) # Brief pause before next iteration of main_loop while

        except KeyboardInterrupt:
            logging.info("KeyboardInterrupt received. Shutting down...")
        except TimeoutError: 
            logging.warning("Pub/Sub subscription timed out (should not happen with streaming pull).")
        except Exception as e:
            logging.error(f"An unexpected error occurred in the main run loop: {e}")
            import traceback
            logging.error(traceback.format_exc())
        finally:
            logging.info("Exiting main run loop. Initiating cleanup...")
            self.stop_event.set() 
            logging.info("[RUN DEBUG] In finally block. Sending AGENT_SHUTDOWN.")
            self._publish_convo_control_message("AGENT_SHUTDOWN") # Inform Pi agent is shutting down
            self.cleanup()


    def cleanup(self):
        """Clean up resources."""
        self._send_visual_state_to_blender(AgentVisualState.IDLE.value)
        logging.info("Starting cleanup process...")
        self.stop_event.set() # Ensure stop event is set for all components

        # Stop transcription if it's running
        if hasattr(self, 'transcription_thread') and self.transcription_thread.is_alive():
            logging.info("Cleaning up transcription resources...")
            self.stop_transcription()

        # Cancel Pub/Sub futures
        if self.streaming_pull_future:
            logging.info("Cancelling wake word Pub/Sub streaming pull future...")
            try:
                self.streaming_pull_future.cancel()
                self.streaming_pull_future.result(timeout=10) # Wait for cancellation
                logging.info("Wake word Pub/Sub future cancelled.")
            except TimeoutError:
                logging.warning("Timeout waiting for wake word Pub/Sub future to cancel.")
            except Exception as e:
                logging.error(f"Error cancelling wake word Pub/Sub future: {e}")
        
        if self.raw_audio_streaming_pull_future:
            logging.info("Cancelling raw audio Pub/Sub streaming pull future...")
            try:
                self.raw_audio_streaming_pull_future.cancel()
                self.raw_audio_streaming_pull_future.result(timeout=10) # Wait for cancellation
                logging.info("Raw audio Pub/Sub future cancelled.")
            except TimeoutError:
                logging.warning("Timeout waiting for raw audio Pub/Sub future to cancel.")
            except Exception as e:
                logging.error(f"Error cancelling raw audio Pub/Sub future: {e}")

        # Close Pub/Sub clients
        if self.subscriber_client:
            try:
                logging.info("Closing wake word Pub/Sub subscriber client.")
                self.subscriber_client.close()
            except Exception as e:
                logging.error(f"Error closing wake word Pub/Sub subscriber client: {e}")
        
        if self.raw_audio_subscriber_client:
            try:
                logging.info("Closing raw audio Pub/Sub subscriber client.")
                self.raw_audio_subscriber_client.close()
            except Exception as e:
                logging.error(f"Error closing raw audio Pub/Sub subscriber client: {e}")
        
        # Removed INIT_COMPLETE_FILE cleanup as file creation was removed
        # if os.path.exists(kc.INIT_COMPLETE_FILE):
        #     try:
        #         os.remove(kc.INIT_COMPLETE_FILE)
        #         logging.info(f"Removed {kc.INIT_COMPLETE_FILE}")
        #     except Exception as e:
        #         logging.warning(f"Could not remove {kc.INIT_COMPLETE_FILE}: {e}")

        logging.info("Cleanup complete.")

if __name__ == "__main__":
    agent = None
    try:
        agent = RealTimeAIAgent()
        agent.run()
    except ValueError as ve: # Catch configuration errors from __init__
        logging.critical(f"Configuration error: {ve}. Agent cannot start.")
    except Exception as e:
        logging.critical(f"Unhandled exception in main execution: {e}")
        import traceback
        logging.critical(traceback.format_exc())
    finally:
        if agent:
            logging.info("Ensuring cleanup is called from __main__ finally block.")
            agent.cleanup() # Ensure cleanup is called on any exit
        logging.info("AI Agent application finished.")
        sys.exit(0) # Ensure a clean exit