# kokoro_monitor.py
# This script runs inside Blender and monitors command files created by real_time_ai_agent.py

import bpy
import os
import time
import threading
import sys
import traceback
import socket
import json

# --- Configuration ---
# Determine the directory for Lip.py and blink.py
# Option 1: If the .blend file is saved, use its directory.
# This is often the most reliable if scripts are co-located with the .blend.
blend_file_directory = None
if bpy.data.filepath:
    blend_file_directory = os.path.dirname(bpy.data.filepath)
    print(f"DEBUG: .blend file directory: {blend_file_directory}")

# Option 2: If running this script as an external file, use its directory.
script_file_directory = None
try:
    script_file_directory = os.path.dirname(os.path.realpath(__file__))
    print(f"DEBUG: Script __file__ directory: {script_file_directory}")
except NameError:
    print("DEBUG: __file__ is not defined (e.g., running from internal text block or console).")

# Prioritize the script's own directory if it's valid and different from .blend dir (or .blend not saved)
# Or if .blend dir is not valid.
if script_file_directory and os.path.isdir(script_file_directory):
    MONITOR_DIR = script_file_directory
    print(f"DEBUG: Using script's own directory for MONITOR_DIR: {MONITOR_DIR}")
elif blend_file_directory and os.path.isdir(blend_file_directory):
    MONITOR_DIR = blend_file_directory
    print(f"DEBUG: Using .blend file's directory for MONITOR_DIR: {MONITOR_DIR}")
else:
    # Absolute fallback - ensure this path is correct for your laptop.
    MONITOR_DIR = r"D:\Koki-texture" # << ENSURE THIS IS THE CORRECT PATH ON YOUR LAPTOP
    print(f"DEBUG: Using absolute fallback for MONITOR_DIR: {MONITOR_DIR}")

if not os.path.isdir(MONITOR_DIR):
    print(f"CRITICAL WARNING: MONITOR_DIR '{MONITOR_DIR}' is not a valid directory. Imports for Lip.py/blink.py will likely fail.")
else:
    print(f"DEBUG: Final MONITOR_DIR to be used for sys.path: {MONITOR_DIR}")

# TCP Server Configuration (must match local_blender_bridge.py)
TCP_HOST = "localhost"
TCP_PORT = 65000
BUFFER_SIZE = 4096 # Increased buffer size for potentially larger JSON payloads

# Add the script directory to sys.path to allow importing Lip and blink
print(f"DEBUG: Determined MONITOR_DIR: {MONITOR_DIR}") # DEBUG
print(f"DEBUG: Current sys.path before modification: {sys.path}") # DEBUG
if MONITOR_DIR not in sys.path:
    print(f"DEBUG: Adding {MONITOR_DIR} to sys.path") # DEBUG
    sys.path.append(MONITOR_DIR)
else:
    print(f"DEBUG: {MONITOR_DIR} already in sys.path") # DEBUG
print(f"DEBUG: Current sys.path after modification: {sys.path}") # DEBUG

# Try importing the necessary functions/classes from blink.py (Lip.py is no longer used directly here)
print(f"DEBUG: Attempting imports with sys.path: {sys.path}") # DEBUG
# We assume blink.py has a function like `trigger_blink()`
Lip = None # Lip module no longer used by this script directly

try:
    import blink
    print("Successfully imported blink.py")
except ImportError:
    print("Error: Could not import blink.py. Make sure it's in the same directory or sys.path.")
    blink = None
except Exception as e:
    print(f"Error importing blink.py: {e}")
    traceback.print_exc()
    blink = None

# --- Global State ---
is_monitoring = False # Will indicate if TCP server is running
monitor_thread = None # Will hold the TCP server thread
stop_event = threading.Event()
server_socket = None # Global reference to the server socket for cleanup

# Configuration for amplitude-driven mouth
TARGET_MOUTH_OBJECT = "Mouth"  # <<< USER CONFIGURABLE: Name of your mouth object
JAW_OPEN_SHAPE_KEY = "open" # <<< USER CONFIGURABLE: Name of the shape key for jaw/mouth opening

# --- Core Logic (New TCP Server based) ---

# Store the last conversation ID processed for mouth animation to handle clearing old keyframes
last_animated_mouth_convo_id = None

def _schedule_mouth_amplitude_keyframe(obj_name, shape_key_name, value, time_offset, conversation_id):
    """
    This function is intended to be called by bpy.app.timers.register
    to ensure it runs in Blender's main thread.
    """
    global last_animated_mouth_convo_id
    try:
        obj = bpy.data.objects.get(obj_name)
        if not obj:
            print(f"Error in _schedule_mouth_amplitude_keyframe: Object '{obj_name}' not found.")
            return

        if not (obj.data and hasattr(obj.data, 'shape_keys') and obj.data.shape_keys):
            print(f"Error in _schedule_mouth_amplitude_keyframe: Object '{obj_name}' has no shape keys.")
            return

        jaw_shape_key = obj.data.shape_keys.key_blocks.get(shape_key_name)
        if not jaw_shape_key:
            print(f"Error in _schedule_mouth_amplitude_keyframe: Shape key '{shape_key_name}' not found on object '{obj_name}'.")
            return

        # Ensure animation data and action exist
        if not obj.animation_data:
            obj.animation_data_create()
        
        action_name = f"{obj.name}_AmplitudeAction" # Consistent action name

        if conversation_id != last_animated_mouth_convo_id:
            print(f"New conversation ID '{conversation_id}' for mouth animation. Aggressively resetting action '{action_name}'.")
            
            # Unlink action from object first, if it's currently linked to an action we might remove
            if obj.animation_data and obj.animation_data.action:
                # If it's our target action, or any action, good to unlink before potential removal from bpy.data.actions
                print(f"Unlinking current action '{obj.animation_data.action.name}' from '{obj_name}' before reset.")
                obj.animation_data.action = None
            
            # Attempt to remove the old action by name if it exists in bpy.data.actions
            old_action = bpy.data.actions.get(action_name)
            if old_action:
                try:
                    # Check users. If this object was the only user, or no users, it's safer to remove.
                    # Forcing removal for this test to ensure a clean slate.
                    # Note: old_action.users might be > 0 if it was just unlinked from this obj but still in a NLA track, etc.
                    # For a truly aggressive reset, we remove it from bpy.data.actions regardless of other users,
                    # assuming this action is exclusively for this script's purpose.
                    bpy.data.actions.remove(action=old_action)
                    print(f"Removed existing action '{action_name}' from bpy.data.actions.")
                except Exception as e_remove_action:
                    # This might fail if the action is still "in use" by Blender in some way (e.g. NLA editor)
                    print(f"Could not remove action '{action_name}' from bpy.data.actions (it might be in use elsewhere or protected): {e_remove_action}")
            else:
                print(f"No action named '{action_name}' found in bpy.data.actions to remove.")

            # Create a new action
            new_action = bpy.data.actions.new(name=action_name)
            print(f"Created new empty action '{action_name}'.")
            
            # Assign this new, empty action to the object
            if not obj.animation_data:
                obj.animation_data_create()
            obj.animation_data.action = new_action
            print(f"Assigned new action '{action_name}' to object '{obj_name}'.")
            
            last_animated_mouth_convo_id = conversation_id
            
            # --- REFINED Auto-playback logic ---
            try:
                print(f"MAIN THREAD: New conversation '{conversation_id}'. Setting frame_current to 1.")
                bpy.context.scene.frame_current = 1 # More direct way to set frame

                animation_was_playing = False
                try:
                    if bpy.context.screen and hasattr(bpy.context.screen, 'is_animation_playing'):
                        animation_was_playing = bpy.context.screen.is_animation_playing
                    print(f"MAIN THREAD: Animation playing status before potential toggle: {animation_was_playing}")
                except Exception as e_check_play:
                    print(f"MAIN THREAD: Error checking if animation is playing: {e_check_play}")

                if not animation_was_playing:
                    print(f"MAIN THREAD: Animation was not playing. Attempting to start playback for conversation {conversation_id}.")
                    played_successfully = False
                    for window in bpy.context.window_manager.windows:
                        screen = window.screen
                        for area in screen.areas:
                            if area.type in {'VIEW_3D', 'TIMELINE', 'DOPESHEET_EDITOR', 'GRAPH_EDITOR'}:
                                override = {'window': window, 'screen': screen, 'area': area}
                                try:
                                    bpy.ops.screen.animation_play(override)
                                    print(f"MAIN THREAD: Called animation_play() for conversation {conversation_id} with context from area {area.type}")
                                    played_successfully = True
                                    break
                                except Exception as e_op:
                                    print(f"MAIN THREAD: Error calling animation_play with context from area {area.type}: {e_op}")
                        if played_successfully:
                            break
                    if not played_successfully:
                        print(f"MAIN THREAD: Could not find suitable context to call animation_play() for conversation {conversation_id}. Trying default context.")
                        try:
                            bpy.ops.screen.animation_play() # Fallback to default context
                            print(f"MAIN THREAD: Called animation_play() (default context) for conversation: {conversation_id}")
                        except Exception as e_default_play:
                             print(f"MAIN THREAD: Error calling animation_play() (default context) for conversation {conversation_id}: {e_default_play}")
                else:
                    print(f"MAIN THREAD: Animation was already playing. Frame jumped to 1 for new conversation {conversation_id}.")

            except Exception as e_play:
                print(f"MAIN THREAD: General error in playback logic for conversation {conversation_id}: {e_play}")
                traceback.print_exc()
            # --- END REFINED Auto-playback ---

        elif not obj.animation_data or not obj.animation_data.action or obj.animation_data.action.name != action_name:
            # This case handles if the action got unlinked or was never set for the current convo_id
            # (should be less likely with the aggressive reset, but good fallback)
            print(f"Re-assigning action '{action_name}' to '{obj_name}' (current convo: {conversation_id}).")
            target_action = bpy.data.actions.get(action_name)
            if not target_action:
                # This implies it's not a new convo_id, but action is missing. Create it.
                target_action = bpy.data.actions.new(name=action_name)
                print(f"Action '{action_name}' was missing, created new one.")
            if not obj.animation_data:
                obj.animation_data_create()
            obj.animation_data.action = target_action
            print(f"Ensured action '{action_name}' is assigned to '{obj_name}'.")

        jaw_shape_key.value = float(value) # Set current value
        if time_offset is not None:
            scene_fps = bpy.context.scene.render.fps
            frame_to_key = max(1, int(round(time_offset * scene_fps)) + 1)
            
            jaw_shape_key.keyframe_insert(data_path="value", frame=frame_to_key)
            
            # Set interpolation to Linear for the newly inserted keyframe
            if obj.animation_data.action:
                for fcurve in obj.animation_data.action.fcurves:
                    if fcurve.data_path == f'key_blocks["{shape_key_name}"].value':
                        for kf_point in fcurve.keyframe_points:
                            if kf_point.co.x == frame_to_key:
                                kf_point.interpolation = 'LINEAR'
                                break
                        break
            print(f"MAIN THREAD: Keyframed {obj_name}.{shape_key_name} to {value:.3f} at frame {frame_to_key} (time: {time_offset:.3f}s)")
        else:
            # This case should ideally not happen if time_offset is always sent
            print(f"MAIN THREAD: Set {obj_name}.{shape_key_name} to {value:.3f} (no time_offset, direct set).")

    except Exception as e:
        print(f"Error in _schedule_mouth_amplitude_keyframe: {e}")
        traceback.print_exc()


def handle_tcp_client(conn, addr):
    """Handles an incoming client connection."""
    print(f"Accepted connection from {addr}")
    command_count_session = 0 # Counter for this specific client connection
    try:
        # Buffer to handle partial messages if they span multiple recv calls
        # This is important if local_blender_bridge sends data very rapidly
        # or if network fragmentation occurs (less likely on localhost).
        # Each JSON command is expected to end with a newline.
        recv_buffer = ""
        while not stop_event.is_set():
            try:
                data = conn.recv(BUFFER_SIZE)
                if not data:
                    print(f"Connection from {addr} closed by client (received empty data).")
                    break
                
                recv_buffer += data.decode('utf-8')
                
                # Process all complete JSON messages in the buffer
                while '\n' in recv_buffer:
                    message_str, recv_buffer = recv_buffer.split('\n', 1)
                    if not message_str.strip(): # Skip empty lines if any
                        continue

                    command_count_session += 1
                    # print(f"Processing message #{command_count_session} from {addr}: {message_str[:100]}...") # Log snippet

                    command_data = json.loads(message_str)
                    # print(f"Parsed command #{command_count_session} from {addr}: {command_data.get('command_type')}")


                    command_type = command_data.get("command_type")

                if command_type == "mouth_amplitude":
                    amplitude_value = command_data.get("value")
                    time_offset = command_data.get("time_offset")
                    conversation_id = command_data.get("conversation_id") # Make sure this is sent by bridge
                    
                    if amplitude_value is not None and time_offset is not None and conversation_id is not None:
                        # Schedule the Blender operation to run in the main thread
                        # Using a lambda to pass arguments to the timer function
                        bpy.app.timers.register(
                            lambda val=amplitude_value, t_off=time_offset, convo_id=conversation_id:
                            _schedule_mouth_amplitude_keyframe(
                                TARGET_MOUTH_OBJECT,
                                JAW_OPEN_SHAPE_KEY,
                                val,
                                t_off,
                                convo_id
                            )
                        )
                    else:
                        print(f"Amplitude command missing value, time_offset, or conversation_id: {command_data}")

                elif command_type == "blink":
                    if blink and hasattr(blink, 'trigger_blink'):
                        print("Queueing blink command.")
                        bpy.app.timers.register(lambda: safe_execute(blink.trigger_blink))
                    else:
                        print("blink.py module or trigger_blink function not available.")

                elif command_type == "play_animation":
                    animation_name = command_data.get("animation_name", "UnknownAnimation") # Default if not provided
                    print(f"Queueing play_animation command for: {animation_name}")
                    # Modify safe_play_animation if it needs to handle specific animation names
                    bpy.app.timers.register(lambda name=animation_name: safe_play_animation(name))
                
                else:
                    print(f"Unknown command_type received: {command_type}")

                # Optionally send an ACK back to the client
                # conn.sendall(json.dumps({"status": "received", "command": command_type}).encode('utf-8'))

            except json.JSONDecodeError:
                print(f"Error: Could not decode JSON from {addr}. Data: {data.decode('utf-8', errors='ignore')}")
            except Exception as e:
                print(f"Error processing command from {addr}: {e}")
                traceback.print_exc()
                # Optionally send an NACK or error message back
                # conn.sendall(json.dumps({"status": "error", "detail": str(e)}).encode('utf-8'))
    except ConnectionResetError:
        print(f"Connection from {addr} reset by peer.")
    except Exception as e:
        if not stop_event.is_set(): # Avoid logging errors if we are intentionally stopping
            print(f"Error in handle_tcp_client for {addr}: {e}")
            traceback.print_exc()
    finally:
        print(f"Closing connection from {addr}. Total commands processed in this session: {command_count_session}")
        conn.close()

def tcp_server_loop():
    """The main loop for the TCP server thread."""
    global server_socket
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_socket.bind((TCP_HOST, TCP_PORT))
        server_socket.listen(5) # Listen for up to 5 queued connections
        server_socket.settimeout(1.0) # Timeout for accept() to allow checking stop_event
        print(f"TCP Server started. Listening on {TCP_HOST}:{TCP_PORT}")

        while not stop_event.is_set():
            try:
                conn, addr = server_socket.accept()
                # Potentially use a thread pool for many clients, but for one bridge, direct thread is fine.
                client_thread = threading.Thread(target=handle_tcp_client, args=(conn, addr), daemon=True)
                client_thread.start()
            except socket.timeout:
                continue # Allow loop to check stop_event
            except Exception as e:
                if not stop_event.is_set():
                    print(f"Error accepting connection in TCP server loop: {e}")
                    time.sleep(0.1) # Avoid busy-looping on persistent accept errors

    except Exception as e:
        if not stop_event.is_set(): # Don't log error if we are stopping
            print(f"Fatal error starting TCP server: {e}")
            traceback.print_exc()
    finally:
        print("TCP Server loop stopping...")
        if server_socket:
            server_socket.close()
            server_socket = None
        print("TCP Server socket closed.")

def safe_execute(func, *args, **kwargs):
    """Safely executes a function, catching and printing exceptions."""
    try:
        print(f"Executing function: {func.__name__} with args: {args}, kwargs: {kwargs}")
        func(*args, **kwargs)
        print(f"Function {func.__name__} executed successfully.")
    except Exception as e:
        print(f"Error executing {func.__name__}: {e}")
        traceback.print_exc()

def safe_play_animation(animation_name="default_play"): # Added animation_name
    """Safely plays the animation. TODO: Implement logic to play specific animation_name if needed."""
    try:
        print(f"Attempting to play animation: {animation_name}...")
        # If you have different actions/NLA strips, you'd use animation_name here
        # For now, it just plays the main timeline.
        # Example:
        # if animation_name == "idle_01":
        #     # code to play idle_01 NLA strip
        #     pass
        # else:
        #     bpy.ops.screen.animation_play()
        bpy.ops.screen.animation_play() # Default: play current timeline
        print(f"Animation play command issued for '{animation_name}'.")
    except Exception as e:
        print(f"Error playing animation '{animation_name}': {e}")
        traceback.print_exc()

# monitor_loop and check_commands are no longer needed with TCP server.
# They will be removed in a subsequent step or can be removed now if preferred.

# --- Blender Operator ---
class KokoroMonitorOperator(bpy.types.Operator):
    """Operator to start/stop the Kokoro TCP command server"""
    bl_idname = "wm.kokoro_monitor_control"
    bl_label = "Kokoro TCP Server Control"

    _timer = None # Used for modal operator to check for stop_event from other threads/actions
    action: bpy.props.StringProperty()

    def modal(self, context, event):
        global is_monitoring, monitor_thread # server_socket is handled by _stop_monitoring

        if event.type == 'TIMER':
            # This timer allows the modal to be responsive to external stop requests
            # or if the server thread stops unexpectedly.
            if stop_event.is_set() or (monitor_thread and not monitor_thread.is_alive() and is_monitoring):
                print("Modal timer detected stop event or dead server thread.")
                self._stop_monitoring(context) # Ensure cleanup
                return {'CANCELLED'}

        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            print("ESC or Right Mouse pressed in modal, stopping server.")
            self._stop_monitoring(context)
            return {'CANCELLED'}
        
        # Allow other events to pass through if server is running
        return {'PASS_THROUGH'}

    def _start_monitoring(self, context):
        global is_monitoring, monitor_thread, stop_event, server_socket
        
        # Ensure server_socket is None before starting a new server
        if server_socket is not None:
            print("Warning: server_socket was not None before starting. Attempting to close.")
            try:
                server_socket.close()
            except Exception as e:
                print(f"Error closing pre-existing server_socket: {e}")
            finally:
                server_socket = None

        # Lip.py is no longer a direct dependency for starting the server for amplitude-based animation
        # if not Lip or not hasattr(Lip, 'apply_rhubarb_lipsync'):
        #     self.report({'ERROR'}, "Lip.py or apply_rhubarb_lipsync not loaded correctly. Cannot start TCP server.")
        #     return False
        if not blink or not hasattr(blink, 'trigger_blink'): # Still need blink
            self.report({'ERROR'}, "blink.py or trigger_blink not loaded correctly. Cannot start TCP server.")
            return False

        print("Starting Kokoro TCP Server...")
        stop_event.clear()
        monitor_thread = threading.Thread(target=tcp_server_loop, daemon=True)
        monitor_thread.start()
        is_monitoring = True # Indicates TCP server thread has been started
        
        wm = context.window_manager
        if self._timer is None: # Add timer only if not already present
            self._timer = wm.event_timer_add(1.0, window=context.window) # Check every 1 second
            print("Modal timer added.")
        else:
            print("Modal timer already exists.")
            
        wm.modal_handler_add(self)
        print(f"Kokoro TCP Server initiated. Listening on {TCP_HOST}:{TCP_PORT}")
        self.report({'INFO'}, f"Kokoro TCP Server listening on {TCP_HOST}:{TCP_PORT}")
        return True

    def _stop_monitoring(self, context):
        global is_monitoring, monitor_thread, stop_event, server_socket
        
        if not is_monitoring and not (monitor_thread and monitor_thread.is_alive()):
            print("Stop called, but monitor doesn't seem to be active.")
            self.cancel(context) # Ensure timer is cleaned up if modal was somehow active
            return

        print("Stopping Kokoro TCP Server...")
        stop_event.set() # Signal the server_loop and client_handling_threads to stop

        if server_socket:
            try:
                print("Attempting to shutdown and close server_socket...")
                # Forcing close, as shutdown might block if accept() is blocked by settimeout
                server_socket.close()
                print("Server_socket closed directly.")
            except OSError as e:
                print(f"Error closing server_socket (may already be closed or in use): {e}")
            except Exception as e:
                print(f"Unexpected error closing server_socket: {e}")
            finally:
                server_socket = None # Ensure it's marked as None
        
        if monitor_thread and monitor_thread.is_alive():
            print("Waiting for TCP server thread to join...")
            monitor_thread.join(timeout=2.0) # Reduced timeout slightly
            if monitor_thread.is_alive():
                print("Warning: TCP server thread did not stop gracefully after timeout.")
        
        monitor_thread = None
        is_monitoring = False # Mark as no longer monitoring
        print("Kokoro TCP Server stopped.")
        self.report({'INFO'}, "Kokoro TCP Server stopped.")
        
        self.cancel(context) # Clean up modal timer

    def execute(self, context):
        global is_monitoring # monitor_thread is managed by _start/_stop

        if self.action == "START":
            if not is_monitoring:
                if self._start_monitoring(context):
                    return {'RUNNING_MODAL'}
                else:
                    # _start_monitoring failed (e.g., script deps missing), it would have reported.
                    return {'CANCELLED'}
            else:
                self.report({'INFO'}, "Kokoro TCP Server is already running.")
                return {'CANCELLED'}
        elif self.action == "STOP":
            # _stop_monitoring will handle reporting and cancelling the modal.
            self._stop_monitoring(context)
            return {'FINISHED'} # Indicate the operator's action is done.
        else:
            self.report({'WARNING'}, "Invalid action specified for Kokoro TCP Server.")
            return {'CANCELLED'}

    def cancel(self, context):
        # This method is called by Blender when the modal operator is cancelled.
        if self._timer:
            try:
                wm = context.window_manager
                wm.event_timer_remove(self._timer)
                print("Modal timer removed.")
            except Exception as e:
                print(f"Error removing modal timer: {e}")
            finally:
                self._timer = None
        # Ensure monitoring is truly stopped if cancel is called externally
        # This might be redundant if _stop_monitoring is always the path to cancellation.
        # if is_monitoring:
        #    print("Cancel called while monitoring was true, ensuring stop.")
        #    self._stop_monitoring(context) # This could lead to recursion if _stop_monitoring calls cancel.
                                         # Better to ensure _stop_monitoring is robust.

# --- Registration ---
def register():
    bpy.utils.register_class(KokoroMonitorOperator)
    print("Kokoro Monitor Operator Registered")

def unregister():
    # Ensure monitoring is stopped on unregister
    if is_monitoring:
         print("Stopping monitor due to unregistration...")
         stop_event.set()
         if monitor_thread:
             monitor_thread.join(timeout=1)
    bpy.utils.unregister_class(KokoroMonitorOperator)
    print("Kokoro Monitor Operator Unregistered")

# --- Main Execution ---
if __name__ == "__main__":
    # Clean up previous registration if script is re-run
    try:
        unregister()
    except RuntimeError: # Already unregistered
        pass
    register()

    # Optional: Automatically start monitoring when the script is run
    # bpy.ops.wm.kokoro_monitor_control(action='START')
    print("\nKokoro Monitor Ready.")
    print("To start monitoring, run this from Blender's Text Editor:")
    print("bpy.ops.wm.kokoro_monitor_control(action='START')")
    print("To stop monitoring, press ESC in the Blender window or run:")
    print("bpy.ops.wm.kokoro_monitor_control(action='STOP')")