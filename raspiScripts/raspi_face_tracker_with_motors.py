# raspi_face_tracker_with_motors.py
# Uses Google Cloud Vision API for face detection and controls motors on Raspberry Pi.

import cv2
import numpy as np
import time
import os
import io # For image byte conversion
import json # Added for Pub/Sub
from datetime import datetime # Added for Pub/Sub timestamp

# Add the parent directory (Kokoro) to sys.path
import sys
# Correctly determine the project root relative to the current script
_RASPI_SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
_KOKORO_PROJECT_ROOT = os.path.abspath(os.path.join(_RASPI_SCRIPT_DIR, '..'))
if _KOKORO_PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _KOKORO_PROJECT_ROOT) # Prepend to allow overriding modules if necessary

kokoro_config = None # Initialize to None
try:
    import kokoro_config # Added for Pub/Sub topic and Project ID
except ImportError as e:
    print(f"INFO: Could not import kokoro_config. This is expected if not present on Pi. Pub/Sub init will use hardcoded values if needed. Error: {e}")
    # Allow script to continue; Pub/Sub init will fail gracefully later if hardcoding isn't done.

try:
    from google.cloud import pubsub_v1
    GOOGLE_CLOUD_PUBSUB_AVAILABLE = True
except ImportError:
    GOOGLE_CLOUD_PUBSUB_AVAILABLE = False
    print("WARNING: google-cloud-pubsub library not found. Publishing will not work.")
    print("Please install it: pip install google-cloud-pubsub")
try:
    from google.cloud import vision
    GOOGLE_CLOUD_VISION_AVAILABLE = True
except ImportError:
    GOOGLE_CLOUD_VISION_AVAILABLE = False
    print("WARNING: google-cloud-vision library not found. Face detection will not work.")
    print("Please install it: pip install google-cloud-vision")
from google.oauth2 import service_account # For explicit credential loading

# Global variables for Pub/Sub
publisher = None
topic_path = None

# --- Configuration Parameters ---
# Google Cloud Vision API Configuration
GCP_SERVICE_ACCOUNT_KEY_PATH = "raspi-vision-key.json"

# --- Pub/Sub Setup ---
def initialize_pubsub_publisher():
    """Initializes the Google Cloud Pub/Sub publisher client and topic path."""
    global publisher, topic_path

    if not GOOGLE_CLOUD_PUBSUB_AVAILABLE:
        print("Error: Google Cloud Pub/Sub library not installed. Cannot initialize publisher.")
        return False

    # Hardcoded values
    project_id = "diesel-dominion-452723-h7"
    face_topic = "kokoro-face-tracking-coordinates"
    
    print(f"INFO: Using hardcoded project_id: {project_id}")
    print(f"INFO: Using hardcoded face_topic: {face_topic}")
    print(f"INFO: Attempting to use service account key from: {GCP_SERVICE_ACCOUNT_KEY_PATH}")

    try:
        # Explicitly load credentials
        if not os.path.exists(GCP_SERVICE_ACCOUNT_KEY_PATH):
            print(f"FATAL ERROR: Service account key file not found at {GCP_SERVICE_ACCOUNT_KEY_PATH} for Pub/Sub.")
            return False
        
        credentials = service_account.Credentials.from_service_account_file(GCP_SERVICE_ACCOUNT_KEY_PATH)
        publisher = pubsub_v1.PublisherClient(credentials=credentials)
        print(f"INFO: Pub/Sub PublisherClient initialized explicitly with credentials from {GCP_SERVICE_ACCOUNT_KEY_PATH}")
            
        topic_path = publisher.topic_path(project_id, face_topic)
        print(f"Pub/Sub publisher initialized for topic: {topic_path}")
        return True
    except Exception as e:
        print(f"FATAL ERROR: Error initializing Pub/Sub publisher with explicit credentials: {e}")
        print(f"Details: project_id='{project_id}', face_topic='{face_topic}', key_path='{GCP_SERVICE_ACCOUNT_KEY_PATH}'")
        traceback.print_exc() # Print full traceback for detailed debugging
        publisher = None
        topic_path = None
        return False

# Camera Configuration
FRAME_WIDTH = 320
FRAME_HEIGHT = 240
FPS = 2

# Motor Control Configuration
MOTOR_LEFT_IN1 = 17
MOTOR_LEFT_IN2 = 27
MOTOR_RIGHT_IN1 = 22
MOTOR_RIGHT_IN2 = 23

# Control Logic
DEAD_ZONE_THRESHOLD = 0.1
MOTOR_PULSE_DURATION = 0.15 # Seconds motors run per correction pulse
DETECTION_CONFIDENCE_THRESHOLD = 0 # Minimum confidence score to consider a face detected

# Display Window
SHOW_CV_WINDOW = False

# --- GPIO Setup ---

# --- Face Detection (Google Cloud) ---
def initialize_vision_client(key_path=None):
    if not GOOGLE_CLOUD_VISION_AVAILABLE:
        print("Error: Google Cloud Vision library not installed.")
        return None
    try:
        # Use the globally defined GCP_SERVICE_ACCOUNT_KEY_PATH for the vision client as well for consistency
        if not os.path.exists(GCP_SERVICE_ACCOUNT_KEY_PATH):
             print(f"FATAL ERROR: Service account key file not found at {GCP_SERVICE_ACCOUNT_KEY_PATH} for Vision API.")
             return None
        
        credentials_vision = service_account.Credentials.from_service_account_file(GCP_SERVICE_ACCOUNT_KEY_PATH)
        client = vision.ImageAnnotatorClient(credentials=credentials_vision)
        print(f"Google Cloud Vision client initialized explicitly with credentials from {GCP_SERVICE_ACCOUNT_KEY_PATH}")
        return client
        
    except Exception as e:
        print(f"Error initializing Vision client with explicit credentials: {e}");
        traceback.print_exc()
        return None

def detect_face_google_cloud(client, frame):
    if client is None:
        print("LOG: detect_face_google_cloud - Vision client is None.")
        return None, None, None, None # Ensure 4 values for unpacking
    
    if frame is None:
        print("LOG: detect_face_google_cloud - Input frame is None.")
        return None, None, None, None # Return 4 Nones to avoid unpack error if frame is bad early

    h_orig, w_orig, _ = frame.shape
    try:
        success, encoded_image = cv2.imencode('.jpg', frame)
        if not success: print("LOG: detect_face_google_cloud - Failed to encode frame."); return None, None, None, None
        image = vision.Image(content=encoded_image.tobytes())
        response = client.face_detection(image=image)
        if response.error.message:
            print(f"LOG: Vision API Error: {response.error.message}"); return None, None, None, None
        if not response.face_annotations:
            return None, None, None, None # Return 4 Nones to prevent ValueError
        
        largest_face = max(response.face_annotations, key=lambda face: (face.bounding_poly.vertices[2].x - face.bounding_poly.vertices[0].x) * (face.bounding_poly.vertices[2].y - face.bounding_poly.vertices[0].y))
        
        v = largest_face.bounding_poly.vertices
        box = (int(v[0].x), int(v[0].y), int(v[2].x - v[0].x), int(v[2].y - v[0].y))
        score = largest_face.detection_confidence
        
        center_x = box[0] + box[2] / 2.0
        center_y = box[1] + box[3] / 2.0 # Calculate center_y

        norm_x = (center_x / w_orig - 0.5) * 2.0 # Normalized x
        norm_y = (center_y / h_orig - 0.5) * 2.0 # Normalized y

        norm_x = float(np.clip(norm_x, -1.0, 1.0))
        norm_y = float(np.clip(norm_y, -1.0, 1.0))
        
        return norm_x, norm_y, box, score
    except Exception as e:
        print(f"LOG: detect_face_google_cloud - Error: {e}"); return None, None, None, None

import traceback # Added for detailed error logging

# --- Main ---
def pubsub_publish_callback(future):
    try:
        message_id = future.result(timeout=5) # Wait up to 5s for result
        print(f"LOG_PUBSUB: Message {message_id} published successfully.")
    except TimeoutError:
        print(f"LOG_PUBSUB: Timeout waiting for publish result.")
    except Exception as e_cb:
        print(f"LOG_PUBSUB: Error publishing message: {e_cb}")
def main():
    picam2, cap, using_picamera2 = None, None, False
    try:
        from picamera2 import Picamera2
        picam2 = Picamera2()
        cfg = picam2.create_preview_configuration(main={"size":(FRAME_WIDTH,FRAME_HEIGHT),"format":"RGB888"}, controls={"FrameRate":float(FPS)})
        picam2.configure(cfg); picam2.start()
        using_picamera2 = True; print(f"picamera2 initialized: {FRAME_WIDTH}x{FRAME_HEIGHT} @ {FPS}FPS")
    except Exception as e:
        print(f"picamera2 failed: {e}. Fallback to OpenCV.")
        if picam2:
            try:
                picam2.close()
            except Exception: # Catch all exceptions
                pass
        picam2 = None
        cap = cv2.VideoCapture(0)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,FRAME_WIDTH); cap.set(cv2.CAP_PROP_FRAME_HEIGHT,FRAME_HEIGHT); cap.set(cv2.CAP_PROP_FPS,FPS)
            print(f"OpenCV initialized: {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))} @ {cap.get(cv2.CAP_PROP_FPS):.2f}FPS")
        else: print("Error: All camera backends failed."); return
    
    vision_client = initialize_vision_client() # Now uses GCP_SERVICE_ACCOUNT_KEY_PATH by default
    if vision_client is None: print("Vision client failed. Exiting."); return

    if not initialize_pubsub_publisher():
        print("Pub/Sub client failed to initialize. Face coordinates will not be published.")

        
    print("Starting tracking loop (Ctrl+C to quit)...")
    interval = 1.0/FPS; last_time = time.time()

    try:
        while True:
            now = time.time()
            if (now - last_time) < interval: time.sleep(interval - (now - last_time))
            last_time = time.time()

            frame = None
            if using_picamera2:
                if picam2: frame_rgb = picam2.capture_array(); frame = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR) if frame_rgb is not None else None
            elif cap: ret, frame = cap.read()
            
            if frame is None: print("Error: Failed to capture frame."); time.sleep(0.1); continue

            norm_x, norm_y, box, score = detect_face_google_cloud(vision_client, frame)

            # Apply confidence threshold
            if box is not None and score is not None and score < DETECTION_CONFIDENCE_THRESHOLD:
                print(f"LOG: Face discarded due to low confidence: {score:.4f} < {DETECTION_CONFIDENCE_THRESHOLD}")
                norm_x, norm_y, box, score = None, None, None, None # Treat as no detection
            elif box is not None and score is None: # Should not happen if box is not None, but as a safeguard
                print(f"LOG: Face discarded due to missing score, though box was present.")
                norm_x, norm_y, box, score = None, None, None, None # Treat as no detection

            # ---- DEBUG LOGGING ----
            if norm_x is not None and norm_y is not None and score is not None:
                 score_display_val = f"{score:.2f}"
                 print(f"DEBUG_BLENDER: Face detected. norm_x: {norm_x:.4f}, norm_y: {norm_y:.4f}, score: {score_display_val}")
            elif box is None:
                 print(f"DEBUG_BLENDER: No face detected (box is None or score too low).")
            # ---- END DEBUG LOGGING ----
            
            # --- Publish face data to Pub/Sub ---
            if publisher and topic_path:
                face_data = {}
                if box: # Face detected and passed threshold
                    face_data = {
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "face_center_x_normalized": norm_x,
                        "face_center_y_normalized": norm_y,
                        "detection_confidence": score if score is not None else 0.0, # score could be None if discarded
                        "face_detected": True,
                        "box_x_px": int(box[0]), 
                        "box_y_px": int(box[1]),
                        "box_w_px": int(box[2]),
                        "box_h_px": int(box[3]),
                    }
                else: # No face detected or discarded due to low confidence
                    face_data = {
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "face_detected": False
                    }

                try:
                    message_json = json.dumps(face_data)
                    message_bytes = message_json.encode('utf-8')
                    publish_future = publisher.publish(topic_path, data=message_bytes)
                    publish_future.add_done_callback(pubsub_publish_callback)
                    # Optional: publish_future.add_done_callback(...)
                except Exception as e_pub:
                    print(f"LOG: Error preparing/publishing to Pub/Sub: {e_pub}")
            # --- End Publish face data ---

            
            if SHOW_CV_WINDOW:
                disp_frame = frame.copy()
                if box: cv2.rectangle(disp_frame, (box[0],box[1]),(box[0]+box[2],box[1]+box[3]), (0,255,0),2)
                cv2.imshow("Face Tracker", disp_frame)
                if cv2.waitKey(1)&0xFF == ord('q'): break
    except KeyboardInterrupt: print("\nKeyboard interrupt.")
    finally:
        print("Cleaning up...")
        if using_picamera2 and picam2:
            try:
                picam2.stop()
                picam2.close()
            except Exception: 
                pass
        if cap: cap.release()
        if SHOW_CV_WINDOW: cv2.destroyAllWindows()
        # stop_all_motors_and_cleanup()

if __name__ == "__main__":
    if not GOOGLE_CLOUD_VISION_AVAILABLE:
        print("Exiting: google-cloud-vision library required.")
    else:
        # Check for Vision API credentials (now primarily for existence, as it's explicitly loaded)
        if not os.path.exists(GCP_SERVICE_ACCOUNT_KEY_PATH):
             print(f"FATAL ERROR: Service account key file not found at {GCP_SERVICE_ACCOUNT_KEY_PATH}. This key is required for both Vision and Pub/Sub.")
        else:
            main()