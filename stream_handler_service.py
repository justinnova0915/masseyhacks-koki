# stream_handler_service.py
import fastapi
import uvicorn
import logging
import os
import json
import time
from google.cloud import pubsub_v1
from google.cloud import storage # Added for GCS
import uuid # Added for unique IDs
from datetime import datetime # Added for GCS object path and timestamp
import kokoro_config as kc # Assuming kokoro_config.py is in the same directory or PYTHONPATH
import base64 # For potential future use with audio_data_b64

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = fastapi.FastAPI()
publisher_client = None
storage_client: storage.Client = None # Added for GCS
raw_audio_topic_path = None
wake_word_event_topic_path = None # Added for wake word events

@app.on_event("startup")
async def startup_event():
    global publisher_client, raw_audio_topic_path, wake_word_event_topic_path, storage_client # Added storage_client
    logger.info(f"Attempting to use GCS Bucket from config: '{kc.KOKORO_AUDIO_CHUNKS_GCS_BUCKET if hasattr(kc, 'KOKORO_AUDIO_CHUNKS_GCS_BUCKET') else 'NOT FOUND IN kc'}'")
    logger.info("Attempting to initialize Pub/Sub and GCS clients...")
    try:
        if not kc.GCP_PROJECT_ID:
            logger.error("GCP_PROJECT_ID not configured in kokoro_config.py. Clients cannot be initialized.")
            return

        # Initialize GCS Client
        try:
            storage_client = storage.Client()
            logger.info("Google Cloud Storage client initialized successfully.")
            # Verify bucket exists and is accessible (optional, but good practice)
            if hasattr(kc, 'KOKORO_AUDIO_CHUNKS_GCS_BUCKET') and kc.KOKORO_AUDIO_CHUNKS_GCS_BUCKET:
                try:
                    bucket = storage_client.bucket(kc.KOKORO_AUDIO_CHUNKS_GCS_BUCKET)
                    if not bucket.exists():
                        logger.error(f"GCS Bucket {kc.KOKORO_AUDIO_CHUNKS_GCS_BUCKET} does not exist.")
                        # Decide if this is a fatal error for startup
                    else:
                        logger.info(f"Successfully accessed GCS bucket: {kc.KOKORO_AUDIO_CHUNKS_GCS_BUCKET}")
                except Exception as e_bucket:
                    logger.error(f"Error accessing GCS bucket {kc.KOKORO_AUDIO_CHUNKS_GCS_BUCKET}: {e_bucket}")
            else:
                logger.error("KOKORO_AUDIO_CHUNKS_GCS_BUCKET not configured in kokoro_config.py. GCS uploads will fail.")

        except Exception as e_gcs:
            logger.error(f"Failed to initialize Google Cloud Storage client: {e_gcs}")
            storage_client = None # Ensure it's None if init fails
        
        # Initialize Pub/Sub Client
        if not hasattr(kc, 'PUBSUB_RAW_AUDIO_TOPIC') or not kc.PUBSUB_RAW_AUDIO_TOPIC:
            logger.error("PUBSUB_RAW_AUDIO_TOPIC not configured in kokoro_config.py. Pub/Sub client for raw audio cannot be initialized.")
            # publisher_client will remain None for raw audio if this path fails
        else:
            try:
                if publisher_client is None: # Initialize only if not already (e.g. if wake word init failed but this is ok)
                    publisher_client = pubsub_v1.PublisherClient()
                raw_audio_topic_path = publisher_client.topic_path(kc.GCP_PROJECT_ID, kc.PUBSUB_RAW_AUDIO_TOPIC)
                logger.info(f"Pub/Sub publisher initialized for raw audio topic: {raw_audio_topic_path}")
            except Exception as e_pubsub_raw:
                logger.error(f"Failed to initialize Pub/Sub client for raw audio topic: {e_pubsub_raw}")
                # publisher_client might be partially initialized or None

        # Initialize Wake Word Event Topic
        if not hasattr(kc, 'PUBSUB_WAKE_WORD_TOPIC') or not kc.PUBSUB_WAKE_WORD_TOPIC:
            logger.error("PUBSUB_WAKE_WORD_TOPIC not configured in kokoro_config.py. Wake word event publishing will be disabled.")
            # wake_word_event_topic_path will remain None
        else:
            try:
                if publisher_client is None:
                    publisher_client = pubsub_v1.PublisherClient()
                wake_word_event_topic_path = publisher_client.topic_path(kc.GCP_PROJECT_ID, kc.PUBSUB_WAKE_WORD_TOPIC)
                logger.info(f"Pub/Sub publisher initialized for wake word event topic: {wake_word_event_topic_path}")
            except Exception as e_pubsub_wake:
                logger.error(f"Failed to initialize Pub/Sub client for wake word topic: {e_pubsub_wake}")
                # publisher_client might be partially initialized or None

    except AttributeError as ae:
        logger.error(f"Configuration attribute missing in kokoro_config.py: {ae}. Please ensure it is defined.")
        # Ensure clients are None if critical config is missing
        if 'GCP_PROJECT_ID' in str(ae):
            publisher_client = None
            storage_client = None
    except Exception as e:
        logger.error(f"Failed to initialize clients during startup: {e}")
        publisher_client = None
        storage_client = None

@app.post("/stream/audio/ingress")
async def handle_audio_ingress(audio_chunk: bytes = fastapi.Body(...)):
    current_utc_time = datetime.utcnow()
    timestamp_iso = current_utc_time.isoformat() + "Z"
    chunk_size = len(audio_chunk)
    logger.info(f"Received audio chunk of size: {chunk_size} bytes at {current_utc_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} UTC")

    gcs_uri = None
    upload_success = False

    # 1. Upload to GCS
    if storage_client and hasattr(kc, 'KOKORO_AUDIO_CHUNKS_GCS_BUCKET') and kc.KOKORO_AUDIO_CHUNKS_GCS_BUCKET:
        try:
            object_name = f"audio_chunks/{current_utc_time.strftime('%Y/%m/%d/%H')}/{uuid.uuid4()}.raw"
            bucket = storage_client.bucket(kc.KOKORO_AUDIO_CHUNKS_GCS_BUCKET)
            blob = bucket.blob(object_name)
            
            blob.upload_from_string(audio_chunk, content_type='application/octet-stream')
            gcs_uri = f"gs://{kc.KOKORO_AUDIO_CHUNKS_GCS_BUCKET}/{object_name}"
            logger.info(f"Successfully uploaded audio chunk to GCS: {gcs_uri}")
            upload_success = True
        except AttributeError as ae: # Catch if KOKORO_AUDIO_CHUNKS_GCS_BUCKET is missing after startup check
            logger.error(f"GCS configuration error: {ae}. Cannot upload to GCS.")
        except Exception as e_gcs_upload:
            logger.error(f"Failed to upload audio chunk to GCS: {e_gcs_upload}")
            # Optionally, you could try to publish a message indicating upload failure
            # or just proceed to publish without a GCS URI if that's a desired fallback.
            # For now, we log and gcs_uri will remain None or the failed attempt.
    else:
        logger.warning("Storage client not available or GCS bucket not configured. Cannot upload audio chunk to GCS.")

    # 2. Publish to Pub/Sub
    if publisher_client and raw_audio_topic_path:
        message_id_pubsub = str(uuid.uuid4())
        # Prepare message data
        message_data = {
            "message_id": message_id_pubsub,
            "timestamp": timestamp_iso,
            "type": "audio_chunk_received", # Changed from event_type
            "metadata": { # Added metadata block
                "source_device_id": "unknown_device", # Placeholder, can be enhanced
                "original_chunk_size_bytes": chunk_size
            }
        }

        if upload_success and gcs_uri:
            message_data["data_reference_type"] = "gcs_uri"
            message_data["data_reference"] = gcs_uri
        else:
            # Fallback or error state: if GCS upload failed or was skipped
            # Option 1: Publish with an error indicator
            message_data["data_reference_type"] = "error_no_gcs_uri"
            message_data["data_reference"] = "GCS upload failed or skipped"
            logger.warning("Proceeding to publish Pub/Sub message without GCS URI due to earlier error/skip.")
            # Option 2: Do not publish if GCS URI is essential (depends on requirements)
            # logger.error("GCS URI not available. Skipping Pub/Sub message for this chunk.")
            # return {"status": "error", "message": "Failed to process audio chunk due to GCS upload failure."}

        data_to_publish = json.dumps(message_data).encode("utf-8")
        
        try:
            future = publisher_client.publish(raw_audio_topic_path, data_to_publish)
            published_message_id = future.result(timeout=30) # Blocking call with timeout
            logger.info(f"Published message ID: {published_message_id} (internal ref: {message_id_pubsub}) to raw audio topic ({kc.PUBSUB_RAW_AUDIO_TOPIC}). GCS URI: {gcs_uri if gcs_uri else 'N/A'}")
        except TimeoutError:
            logger.error(f"Timeout publishing audio chunk event (msg_id: {message_id_pubsub}) to Pub/Sub topic {raw_audio_topic_path}.")
        except Exception as e_pubsub:
            logger.error(f"Error publishing audio chunk event (msg_id: {message_id_pubsub}) to Pub/Sub for raw audio: {e_pubsub}")
    else:
        logger.warning("Pub/Sub client not available for raw audio. Cannot publish audio chunk event.")
    
    if upload_success:
        return {"status": "audio chunk uploaded to GCS and notification sent", "gcs_uri": gcs_uri, "size": chunk_size, "timestamp": timestamp_iso}
    else:
        return fastapi.responses.JSONResponse(
            status_code=500, # Internal Server Error if GCS upload failed but we attempted
            content={"status": "error processing audio chunk", "message": "Failed to upload to GCS. Pub/Sub notification may have indicated failure.", "size": chunk_size, "timestamp": timestamp_iso}
        )

@app.post("/event/wake-word-detected")
async def handle_wake_word_event():
    """
    Handles the wake word detected event, typically triggered by an external device like a Raspberry Pi.
    Publishes a message to the wake word Pub/Sub topic.
    """
    logger.info("Wake word detected event received.")

    if not publisher_client or not wake_word_event_topic_path:
        logger.error("Pub/Sub client or wake_word_event_topic_path not initialized. Cannot publish wake word event.")
        return fastapi.responses.JSONResponse(
            status_code=503,
            content={"status": "error", "message": "Pub/Sub service not available for wake word events"}
        )

    timestamp = time.time()
    message_payload = {
        "event": "wake_word_detected_from_pi",
        "timestamp": timestamp,
        "source_device_id": "raspberry_pi_001" # Example, can be made dynamic if needed
    }
    data_to_publish = json.dumps(message_payload).encode("utf-8")

    try:
        future = publisher_client.publish(wake_word_event_topic_path, data_to_publish)
        message_id = future.result(timeout=30) # Blocking call with timeout
        logger.info(f"Successfully published wake word event. Message ID: {message_id}")
        return {"status": "wake_word_event_published", "message_id": message_id}
    except TimeoutError: # Specific exception for future.result() timeout
        logger.error(f"Timeout publishing wake word event to Pub/Sub topic {wake_word_event_topic_path}.")
        return fastapi.responses.JSONResponse(
            status_code=504, # Gateway Timeout
            content={"status": "error", "message": "Timeout publishing wake word event"}
        )
    except Exception as e:
        logger.error(f"Failed to publish wake word event to Pub/Sub topic {wake_word_event_topic_path}: {e}")
        # Consider more specific error handling based on Pub/Sub exceptions if needed
        return fastapi.responses.JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Failed to publish wake word event: {str(e)}"}
        )

if __name__ == "__main__":
    # This allows running directly with uvicorn for local testing
    # Uvicorn will typically be run by GKE in production
    port = int(os.getenv("PORT", "8080")) # GCP Cloud Run/GKE often sets PORT env var
    
    # Ensure kokoro_config is loaded and PUBSUB_RAW_AUDIO_TOPIC is checked before starting server if run directly
    # The startup_event will handle the actual initialization
    if not hasattr(kc, 'GCP_PROJECT_ID') or not kc.GCP_PROJECT_ID:
        logger.critical("CRITICAL: GCP_PROJECT_ID is not set in kokoro_config.py. Service may not function correctly.")
    if not hasattr(kc, 'PUBSUB_RAW_AUDIO_TOPIC') or not kc.PUBSUB_RAW_AUDIO_TOPIC:
        logger.critical("CRITICAL: PUBSUB_RAW_AUDIO_TOPIC is not set in kokoro_config.py. Service may not function correctly.")
        logger.critical("Please add 'PUBSUB_RAW_AUDIO_TOPIC = os.getenv(\"PUBSUB_RAW_AUDIO_TOPIC\", \"kokoro-raw-audio-dev\")' or similar to kokoro_config.py")
    if not hasattr(kc, 'PUBSUB_WAKE_WORD_TOPIC') or not kc.PUBSUB_WAKE_WORD_TOPIC: # Added check for wake word topic
        logger.critical("CRITICAL: PUBSUB_WAKE_WORD_TOPIC is not set in kokoro_config.py. Wake word event handling will not function.")
        logger.critical("Please add 'PUBSUB_WAKE_WORD_TOPIC = os.getenv(\"PUBSUB_WAKE_WORD_TOPIC\", \"kokoro-wake-word-dev\")' or similar to kokoro_config.py")

    logger.info(f"Starting Stream Handler Service on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)