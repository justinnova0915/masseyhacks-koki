# local_blender_bridge.py
import os
import json
import time
import logging
import uuid
from datetime import datetime
from concurrent.futures import TimeoutError
from google.cloud import pubsub_v1
from google.oauth2 import service_account # For service account key
import socket # Added
import threading # Added

# --- Configuration ---
SERVICE_ACCOUNT_FILE = "kokoro-blender-bridge-key.json" # Assumes key is in the same directory
GCP_PROJECT_ID = "diesel-dominion-452723-h7" # Replace with your actual project ID if different

LIP_SYNC_SUB_NAME = "kokoro-blender-lip-sync-sub-localpc" # Choose a unique subscription name
ANIMATION_SUB_NAME = "kokoro-blender-animation-sub-localpc"

# Topics (ensure these match what was created in GCP and in AI Agent's kokoro_config.py)
LIP_SYNC_TOPIC_NAME = "kokoro-blender-lip-sync-commands-dev"
ANIMATION_TOPIC_NAME = "kokoro-blender-animation-control-dev"

# Path where phoneme data received from Pub/Sub will be saved
# This path should be accessible by Blender and match what Lip.py expects
LOCAL_PHONEME_OUTPUT_FILE = r"D:\Koki-Texture\output.txt" # Adjusted for expected laptop path

# TCP Client settings (to communicate with Blender)
BLENDER_TCP_HOST = "localhost"
BLENDER_TCP_PORT = 65000 # Example port, ensure it matches Blender-side server

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

# --- Global State ---
stop_event = threading.Event() # To gracefully stop subscriber threads
blender_socket = None # Global socket for persistent connection
socket_lock = threading.Lock() # To protect access to blender_socket

# --- TCP Client Functions (to be implemented/enhanced) ---
def connect_to_blender_socket():
    """Establishes or re-establishes connection to Blender."""
    global blender_socket
    logging.debug("connect_to_blender_socket called.")
    try:
        if blender_socket: # Close existing if any
            logging.debug("Existing blender_socket found, attempting to close it first.")
            try:
                blender_socket.shutdown(socket.SHUT_RDWR)
                logging.debug("Existing socket shutdown.")
            except OSError as ose:
                logging.debug(f"OSError during shutdown (socket might already be closed): {ose}")
            except Exception as e_close:
                logging.debug(f"Exception closing existing socket: {e_close}")

            blender_socket.close()
            blender_socket = None
            logging.info("Closed existing Blender socket.")

        logging.info(f"Attempting to connect to Blender TCP server at {BLENDER_TCP_HOST}:{BLENDER_TCP_PORT}...")
        temp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        temp_socket.settimeout(5.0) # 5 second timeout for connection attempt
        logging.debug(f"Socket created, attempting connect to ({BLENDER_TCP_HOST}, {BLENDER_TCP_PORT})...")
        temp_socket.connect((BLENDER_TCP_HOST, BLENDER_TCP_PORT))
        logging.debug("Socket connect() call successful.")
        blender_socket = temp_socket # Assign to global only on success
        logging.info("Successfully connected to Blender TCP server.")
        return True
    except socket.timeout:
        logging.error(f"Timeout connecting to Blender TCP server ({BLENDER_TCP_HOST}:{BLENDER_TCP_PORT}).")
        blender_socket = None
        return False
    except ConnectionRefusedError:
        logging.error(f"Connection to Blender TCP server ({BLENDER_TCP_HOST}:{BLENDER_TCP_PORT}) refused. Is Blender script running and listening?")
        blender_socket = None
        return False
    except Exception as e:
        logging.error(f"Error connecting to Blender TCP server: {e}", exc_info=True)
        # Ensure temp_socket is closed if it was created but connect failed or other error occurred
        if 'temp_socket' in locals() and temp_socket:
            try:
                temp_socket.close()
                logging.debug("temp_socket closed due to exception during connect.")
            except Exception as e_close_temp:
                logging.debug(f"Exception closing temp_socket: {e_close_temp}")
        blender_socket = None
        return False

def send_command_to_blender(command_data, max_retries=2):
    """Sends a command to the Blender TCP server using a persistent connection."""
    global blender_socket
    
    # logging.debug(f"send_command_to_blender called with data: {command_data}") # Can be very verbose
    with socket_lock: # Ensure thread-safe access to the socket
        # logging.debug("Socket lock acquired.")
        for attempt in range(max_retries):
            # logging.debug(f"Send attempt {attempt + 1}/{max_retries}.")
            if blender_socket is None:
                logging.info("Blender socket is None. Attempting to connect via connect_to_blender_socket().")
                if not connect_to_blender_socket():
                    if attempt < max_retries - 1:
                        logging.info("Connection failed, will retry after delay...")
                        time.sleep(1) # Wait a bit before retrying
                        continue
                    else:
                        logging.error("Connection to Blender failed after multiple retries. Command not sent.")
                        # logging.debug("Socket lock released after connection failure.")
                        return False # Failed to connect after retries
            
            try:
                message_str = json.dumps(command_data) + "\n"
                message_bytes = message_str.encode('utf-8')
                # logging.debug(f"Attempting to sendall: {message_str.strip()}")
                blender_socket.sendall(message_bytes)
                # logging.info(f"Sent to Blender: {command_data}") # Can be too verbose
                # logging.debug("Socket lock released after successful send.")
                return True # Command sent successfully
            except (socket.error, BrokenPipeError, ConnectionResetError) as e:
                logging.warning(f"Socket error sending to Blender: {e}. Marking socket as dead. Attempt {attempt + 1}/{max_retries}.")
                if blender_socket:
                    try: blender_socket.close()
                    except: pass
                blender_socket = None # Mark socket as dead
                if attempt < max_retries - 1:
                    logging.info("Will retry sending after delay...")
                    time.sleep(0.5 + attempt * 0.5) # Exponential backoff-like delay
                else:
                    logging.error("Failed to send command to Blender after multiple retries due to socket errors.")
                    # logging.debug("Socket lock released after send failure.")
                    return False # Failed to send after retries
            except Exception as e:
                logging.error(f"Unexpected error sending command to Blender via TCP: {e}", exc_info=True)
                if blender_socket:
                    try: blender_socket.close()
                    except: pass
                blender_socket = None # Consider socket dead on any other exception too
                # logging.debug("Socket lock released after unexpected send error.")
                return False # Unexpected error
        # logging.debug("Socket lock released after exhausting retries.")
        return False

def close_blender_connection():
    """Closes the persistent TCP connection to Blender."""
    global blender_socket
    with socket_lock:
        if blender_socket:
            logging.info("Closing persistent connection to Blender.")
            try:
                blender_socket.shutdown(socket.SHUT_RDWR)
                blender_socket.close()
            except OSError as e:
                logging.warning(f"OSError while closing Blender socket (might already be closed): {e}")
            except Exception as e:
                logging.error(f"Unexpected error closing Blender socket: {e}")
            finally:
                blender_socket = None

# --- Pub/Sub Callback Functions ---
def lip_sync_callback(message: pubsub_v1.subscriber.message.Message) -> None:
    """Handles incoming amplitude data messages for lip sync."""
    logging.info(f"Received message on lip-sync/amplitude topic. ID: {message.message_id}")
    try:
        data_str = message.data.decode("utf-8")
        payload = json.loads(data_str)
        # logging.info(f"Amplitude data payload: {payload}") # Can be very verbose

        message_type = payload.get("type")
        conversation_id = payload.get("conversation_id")

        if message_type == "amplitude_data":
            data_points = payload.get("data_points")
            if isinstance(data_points, list):
                logging.info(f"Processing {len(data_points)} amplitude data points for convo ID {conversation_id}.")
                # We can send them one by one, or batch them if Blender-side can handle batches.
                # Sending one by one for now.
                for point in data_points:
                    amplitude_value = point.get("amplitude")
                    time_offset = point.get("time") # Time offset from the start of the audio
                    
                    if amplitude_value is not None and time_offset is not None:
                        blender_command = {
                            "command_type": "mouth_amplitude", # New command type for Blender
                            "value": amplitude_value,
                            "time_offset": time_offset, # Send time offset if kokoro_monitor needs it for keyframing
                            "conversation_id": conversation_id
                        }
                        send_command_to_blender(blender_command)
                        # Small sleep if sending many rapidly, to avoid overwhelming TCP or Blender's main thread.
                        # time.sleep(0.01) # Optional: tune or remove
                    else:
                        logging.warning(f"Skipping malformed amplitude point: {point}")
            else:
                logging.warning(f"Received 'amplitude_data' message but 'data_points' is not a list or is missing. Payload: {payload}")
        
        elif message_type == "phoneme_data":
            logging.warning(f"Received old 'phoneme_data' message type. System is now expecting 'amplitude_data'. Ignoring. Payload: {payload}")
        
        else:
            logging.warning(f"Unknown message type '{message_type}' on lip-sync/amplitude topic. Payload: {payload}")
        
        message.ack()
    except Exception as e:
        logging.error(f"Error processing message on lip-sync/amplitude topic: {e}", exc_info=True)
        message.nack()

def animation_callback(message: pubsub_v1.subscriber.message.Message) -> None:
    """Handles incoming animation control messages."""
    logging.info(f"Received animation message ID: {message.message_id}")
    try:
        data_str = message.data.decode("utf-8")
        payload = json.loads(data_str)
        logging.info(f"Animation payload: {payload}")

        # Directly send the received payload to Blender as it contains the command structure
        send_command_to_blender(payload)
        
        message.ack()
    except Exception as e:
        logging.error(f"Error processing animation message: {e}")
        message.nack()

# --- Main Subscriber Logic ---
def subscribe_to_topic(project_id, topic_name, subscription_name, callback_func, credentials):
    """Creates a subscription if it doesn't exist and starts pulling messages."""
    subscriber_client = pubsub_v1.SubscriberClient(credentials=credentials)
    topic_path = subscriber_client.topic_path(project_id, topic_name)
    subscription_path = subscriber_client.subscription_path(project_id, subscription_name)

    try:
        subscriber_client.get_subscription(subscription=subscription_path)
        logging.info(f"Subscription {subscription_path} already exists.")
    except Exception: # google.api_core.exceptions.NotFound
        logging.info(f"Subscription {subscription_path} not found. Creating...")
        try:
            subscriber_client.create_subscription(
                name=subscription_path, topic=topic_path
            )
            logging.info(f"Subscription {subscription_path} created for topic {topic_path}.")
        except Exception as e:
            logging.error(f"Failed to create subscription {subscription_path}: {e}")
            subscriber_client.close()
            return None, None # Ensure a tuple is always returned

    # The `callbacks` parameter is a dictionary mapping arbitrary keys to callback functions.
    # The client library will call one of these functions for each message received.
    streaming_pull_future = subscriber_client.subscribe(
        subscription_path, callback=callback_func
    )
    logging.info(f"Listening for messages on {subscription_path}...")
    return subscriber_client, streaming_pull_future


if __name__ == "__main__":
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        logging.error(f"Service account key file not found: {SERVICE_ACCOUNT_FILE}")
        logging.error("Please ensure the key file is in the same directory as this script.")
        exit(1)

    try:
        credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE)
        logging.info("Service account credentials loaded successfully.")
    except Exception as e:
        logging.error(f"Failed to load service account credentials: {e}")
        exit(1)

    # Start subscribers in separate threads if you want them to run truly concurrently
    # For simplicity here, we'll just show how to start them.
    # In a real app, you might manage these futures more robustly.

    lip_sync_subscriber, lip_sync_future = None, None
    animation_subscriber, animation_future = None, None

    try:
        logging.info("Starting Lip Sync Subscriber...")
        lip_sync_subscriber, lip_sync_future = subscribe_to_topic(
            GCP_PROJECT_ID, LIP_SYNC_TOPIC_NAME, LIP_SYNC_SUB_NAME, lip_sync_callback, credentials
        )
        if not lip_sync_future:
            logging.error("Failed to start lip sync subscriber.")
            # Potentially exit or handle error

        logging.info("Starting Animation Control Subscriber...")
        animation_subscriber, animation_future = subscribe_to_topic(
            GCP_PROJECT_ID, ANIMATION_TOPIC_NAME, ANIMATION_SUB_NAME, animation_callback, credentials
        )
        if not animation_future:
            logging.error("Failed to start animation control subscriber.")
            # Potentially exit or handle error
        
        logging.info("Subscribers started. Press Ctrl+C to exit.")
        # Keep the main thread alive to allow callbacks to run
        while not stop_event.is_set():
            time.sleep(1)

    except KeyboardInterrupt:
        logging.info("Keyboard interrupt received. Shutting down...")
        stop_event.set()
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}", exc_info=True)
    finally:
        logging.info("Cleaning up subscribers and Blender connection...")
        if lip_sync_future:
            lip_sync_future.cancel()  # Trigger the shutdown
            try:
                lip_sync_future.result(timeout=10) # Reduced timeout
            except TimeoutError:
                logging.warning("Timeout waiting for lip sync subscriber to shut down.")
            except Exception as e_sub:
                logging.warning(f"Error during lip sync subscriber shutdown: {e_sub}")
        if lip_sync_subscriber:
            lip_sync_subscriber.close()

        if animation_future:
            animation_future.cancel()
            try:
                animation_future.result(timeout=10) # Reduced timeout
            except TimeoutError:
                logging.warning("Timeout waiting for animation subscriber to shut down.")
            except Exception as e_sub:
                logging.warning(f"Error during animation subscriber shutdown: {e_sub}")
        if animation_subscriber:
            animation_subscriber.close()
        
        close_blender_connection() # Close the persistent TCP connection
        logging.info("Shutdown complete.")