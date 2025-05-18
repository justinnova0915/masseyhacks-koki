import bpy
import socket
import threading
import json
import math

# --- Configuration ---
# Network settings
TCP_IP = '0.0.0.0'  # Listen on all available interfaces. Use 'localhost' for local only.
TCP_PORT = 9999     # Port to listen on, must match the server's blender_tcp_port

# Blender object settings
TARGET_OBJECT_NAME = "Head_Control_Object"  # Name of the object to control in Blender

# Tilt control settings
MIN_TILT_ANGLE_DEG = -30.0  # Degrees for maximum upward tilt (face at top of frame)
MAX_TILT_ANGLE_DEG = 30.0   # Degrees for maximum downward tilt (face at bottom of frame)
NEUTRAL_TILT_ANGLE_DEG = 0.0 # Degrees for neutral position (face at center or not detected)

# Convert degrees to radians for bpy
MIN_TILT_ANGLE_RAD = math.radians(MIN_TILT_ANGLE_DEG)
MAX_TILT_ANGLE_RAD = math.radians(MAX_TILT_ANGLE_DEG)
NEUTRAL_TILT_ANGLE_RAD = math.radians(NEUTRAL_TILT_ANGLE_DEG)

# Global variable to store the latest tilt command
# This is a simple way to communicate between the network thread and Blender's main thread
# For more complex scenarios, Blender's modal operators or message queues might be better.
latest_tilt_command = {
    "active": False,
    "tilt_rad": NEUTRAL_TILT_ANGLE_RAD
}
server_running = False
server_thread = None
server_socket = None

def update_object_tilt():
    """
    Applies the tilt stored in `latest_tilt_command` to the target object.
    This function is intended to be run by Blender's application timer.
    """
    try:
        target_object = bpy.data.objects.get(TARGET_OBJECT_NAME)
        if target_object:
            if latest_tilt_command["active"]:
                # Apply calculated tilt
                # Assuming X-axis is the tilt axis. Adjust if your model's local axes are different.
                # Ensure rotation mode is Euler (XYZ is common)
                if target_object.rotation_mode != 'XYZ':
                    print(f"Warning: Object '{TARGET_OBJECT_NAME}' rotation mode is {target_object.rotation_mode}. Consider XYZ.")
                target_object.rotation_euler.x = latest_tilt_command["tilt_rad"]
            else:
                # Return to neutral if no active command (e.g., face not detected)
                target_object.rotation_euler.x = NEUTRAL_TILT_ANGLE_RAD
        else:
            if bpy.context.scene: # Only print if we are in a valid scene context
                print(f"Error: Target object '{TARGET_OBJECT_NAME}' not found.")
    except Exception as e:
        print(f"Error updating object tilt: {e}")
    return 0.01  # Interval in seconds for the timer to run again (e.g., 100 times per second)

def handle_client_connection(conn, addr):
    """Handles a single client connection."""
    global latest_tilt_command
    print(f"Connection from: {addr}")
    try:
        buffer = ""
        while True:
            data = conn.recv(1024)
            if not data:
                print(f"Client {addr} disconnected.")
                break
            
            buffer += data.decode('utf-8')
            
            # Process complete JSON messages (assuming messages are newline-separated or one per packet for simplicity)
            # A more robust solution would handle fragmented JSON messages.
            while '\n' in buffer: # Or some other delimiter if your server uses one
                message, buffer = buffer.split('\n', 1)
                try:
                    if not message.strip():
                        continue

                    print(f"Received raw data: {message}")
                    payload = json.loads(message)
                    print(f"Received JSON: {payload}")

                    if payload.get("face_detected", False):
                        face_center_y = payload.get("face_center_y")
                        image_height = payload.get("image_height")

                        if face_center_y is not None and image_height is not None and image_height > 0:
                            # Normalize face_center_y (0.0 at top, 0.5 at center, 1.0 at bottom)
                            normalized_y = face_center_y / image_height
                            
                            # Map normalized_y to tilt angle
                            # When face is at top (normalized_y approaches 0), tilt upwards (MIN_TILT_ANGLE_RAD)
                            # When face is at bottom (normalized_y approaches 1), tilt downwards (MAX_TILT_ANGLE_RAD)
                            # Linear interpolation:
                            tilt_rad = MIN_TILT_ANGLE_RAD + (normalized_y * (MAX_TILT_ANGLE_RAD - MIN_TILT_ANGLE_RAD))
                            
                            # Clamp the angle to the defined min/max range
                            tilt_rad = max(MIN_TILT_ANGLE_RAD, min(tilt_rad, MAX_TILT_ANGLE_RAD))

                            latest_tilt_command["active"] = True
                            latest_tilt_command["tilt_rad"] = tilt_rad
                            print(f"Calculated tilt: {math.degrees(tilt_rad):.2f} degrees for object '{TARGET_OBJECT_NAME}'")
                        else:
                            print("Warning: 'face_center_y' or 'image_height' missing or invalid.")
                            latest_tilt_command["active"] = False # Revert to neutral if data is bad
                    else:
                        print("Face not detected or 'face_detected' is false.")
                        latest_tilt_command["active"] = False # Revert to neutral

                except json.JSONDecodeError:
                    print(f"Error decoding JSON from: {message}")
                except Exception as e:
                    print(f"Error processing message: {e}")
            
            # If there's remaining data in buffer not ending with newline, keep it for next recv
            # This simple split might lose data if JSON is not newline terminated.
            # For robust streaming, consider a proper framing protocol or accumulate until valid JSON.

    except ConnectionResetError:
        print(f"Client {addr} forcibly closed the connection.")
    except Exception as e:
        print(f"Error in client handler {addr}: {e}")
    finally:
        print(f"Closing connection to {addr}")
        conn.close()
        # If this was the only client, or based on some logic, you might set latest_tilt_command["active"] = False

def tcp_server_thread():
    """Runs the TCP server in a separate thread."""
    global server_running, server_socket
    
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) # Allow reuse of address
    try:
        server_socket.bind((TCP_IP, TCP_PORT))
        server_socket.listen(1) # Listen for one connection at a time
        print(f"Blender TCP Server listening on {TCP_IP}:{TCP_PORT} for object '{TARGET_OBJECT_NAME}'")
        server_running = True

        while server_running:
            print("Server waiting for a connection...")
            try:
                # Set a timeout for accept() so the loop can check server_running
                server_socket.settimeout(1.0) 
                conn, addr = server_socket.accept()
                server_socket.settimeout(None) # Reset timeout after connection
                
                # Handle client in a new thread or directly if only one client is expected
                # For simplicity, handling directly. For multiple simultaneous clients, spawn a thread.
                handle_client_connection(conn, addr)

            except socket.timeout:
                # This allows the while loop to check `server_running` periodically
                continue 
            except OSError as e: # Handle cases like socket closed by stop_server
                 if server_running: # Only print if we weren't expecting it to close
                    print(f"Socket error during accept: {e}")
                 break # Exit loop if socket is closed
            except Exception as e:
                if server_running:
                    print(f"Error accepting connections: {e}")
                break # Exit loop on other critical errors

    except Exception as e:
        print(f"Failed to start TCP server: {e}")
    finally:
        if server_socket:
            server_socket.close()
        server_running = False
        print("Blender TCP Server stopped.")

class StartServerOperator(bpy.types.Operator):
    """Starts the TCP server and the Blender timer"""
    bl_idname = "wm.start_tilt_receiver_server"
    bl_label = "Start Face Track Tilt Receiver"

    def execute(self, context):
        global server_thread, server_running, server_socket
        if not server_running:
            # Check if target object exists before starting
            if not bpy.data.objects.get(TARGET_OBJECT_NAME):
                self.report({'WARNING'}, f"Target object '{TARGET_OBJECT_NAME}' not found. Please create it or check name.")
                # return {'CANCELLED'} # Or allow starting anyway

            server_running = True # Set flag before starting thread
            server_thread = threading.Thread(target=tcp_server_thread, daemon=True)
            server_thread.start()
            
            # Register the application timer if not already registered
            if not bpy.app.timers.is_registered(update_object_tilt):
                bpy.app.timers.register(update_object_tilt, persistent=True)
            
            self.report({'INFO'}, f"TCP Server started for '{TARGET_OBJECT_NAME}'. Listening on {TCP_IP}:{TCP_PORT}.")
        else:
            self.report({'INFO'}, "Server is already running.")
        return {'FINISHED'}

class StopServerOperator(bpy.types.Operator):
    """Stops the TCP server and the Blender timer"""
    bl_idname = "wm.stop_tilt_receiver_server"
    bl_label = "Stop Face Track Tilt Receiver"

    def execute(self, context):
        global server_running, server_thread, server_socket

        if server_running:
            server_running = False # Signal the thread to stop
            if server_socket:
                try:
                    # Shut down the socket to interrupt accept()
                    server_socket.shutdown(socket.SHUT_RDWR) 
                except OSError:
                    pass # Socket might already be closed
                finally:
                    server_socket.close()
                    server_socket = None
            
            if server_thread and server_thread.is_alive():
                server_thread.join(timeout=2.0) # Wait for thread to finish
            
            if server_thread and server_thread.is_alive():
                 self.report({'WARNING'}, "Server thread did not stop cleanly.")
            else:
                 self.report({'INFO'}, "TCP Server stopped.")
            server_thread = None
        else:
            self.report({'INFO'}, "Server is not running.")

        # Unregister the timer
        if bpy.app.timers.is_registered(update_object_tilt):
            bpy.app.timers.unregister(update_object_tilt)
            self.report({'INFO'}, "Object tilt timer stopped.")
            
        # Reset command state
        latest_tilt_command["active"] = False
        latest_tilt_command["tilt_rad"] = NEUTRAL_TILT_ANGLE_RAD
        # Optionally, update the object one last time to neutral
        try:
            target_object = bpy.data.objects.get(TARGET_OBJECT_NAME)
            if target_object:
                target_object.rotation_euler.x = NEUTRAL_TILT_ANGLE_RAD
        except Exception as e:
            print(f"Could not reset object to neutral: {e}")

        return {'FINISHED'}

# --- Panel for UI in Blender ---
class TiltReceiverPanel(bpy.types.Panel):
    bl_label = "Face Track Tilt Receiver"
    bl_idname = "OBJECT_PT_tilt_receiver"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Tool' # Or your custom tab name

    def draw(self, context):
        layout = self.layout
        col = layout.column()

        col.label(text="Server Control:")
        if not server_running:
            col.operator("wm.start_tilt_receiver_server", text="Start Server", icon='PLAY')
        else:
            col.operator("wm.stop_tilt_receiver_server", text="Stop Server", icon='PAUSE')
        
        col.separator()
        col.label(text="Configuration:")
        col.prop_search(context.scene, "target_object_name_prop", bpy.data, "objects", text="Target Object")
        # Note: For IP and Port, you'd typically use Scene properties and update the script's globals
        # For simplicity, they are hardcoded here but can be exposed via Scene properties.
        # Example: context.scene.tcp_ip_prop, context.scene.tcp_port_prop
        # These would need to be defined using:
        # bpy.types.Scene.tcp_ip_prop = bpy.props.StringProperty(name="IP Address", default=TCP_IP)
        # bpy.types.Scene.tcp_port_prop = bpy.props.IntProperty(name="Port", default=TCP_PORT, min=1, max=65535)
        # And then update TCP_IP and TCP_PORT globals when the operator runs or properties change.
        # For this script, to change IP/Port, edit the script text directly.
        
        col.label(text=f"Listening on: {TCP_IP}:{TCP_PORT}")
        col.label(text=f"Controlling: {TARGET_OBJECT_NAME}") # This should ideally update if prop changes
        
        col.separator()
        col.label(text="Status:")
        status_text = "Running" if server_running else "Stopped"
        col.label(text=f"Server: {status_text}")
        if server_running and latest_tilt_command["active"]:
            col.label(text=f"Current Tilt: {math.degrees(latest_tilt_command['tilt_rad']):.2f}°")
        elif server_running:
            col.label(text="Current Tilt: Neutral (No face or inactive)")


# --- Registration ---
classes = (
    StartServerOperator,
    StopServerOperator,
    TiltReceiverPanel,
)

def register():
    # Define a scene property to pick the object name via UI (optional)
    # This makes TARGET_OBJECT_NAME in the script a default, but UI can override
    # For this to truly override, the operators/timer would need to read from this prop.
    # For now, TARGET_OBJECT_NAME at the top of the script is the master.
    bpy.types.Scene.target_object_name_prop = bpy.props.StringProperty(
        name="Target Object Name",
        description="Name of the Blender object to control for tilt",
        default=TARGET_OBJECT_NAME 
    )

    for cls in classes:
        bpy.utils.register_class(cls)
    print("Face Track Tilt Receiver registered.")

def unregister():
    # Ensure server is stopped if script is unregistered
    if server_running:
        # Create a temporary context if needed for the operator
        # This might not always work perfectly if unregistering during certain Blender states.
        try:
            bpy.ops.wm.stop_tilt_receiver_server()
        except Exception as e:
            print(f"Could not cleanly stop server on unregister: {e}")
            # Force stop if operator fails
            global server_running_flag, server_socket_ref
            server_running_flag = False
            if server_socket_ref:
                try:
                    server_socket_ref.close()
                except: pass


    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    
    del bpy.types.Scene.target_object_name_prop
    print("Face Track Tilt Receiver unregistered.")

if __name__ == "__main__":
    # --- How to Use ---
    # 1. Open Blender.
    # 2. Go to the "Scripting" tab or open a Text Editor view.
    # 3. Click "New" to create a new text block, or "Open" to load this script file.
    # 4. Paste or load this script's content.
    # 5. **Configuration (Important!):**
    #    - Modify `TARGET_OBJECT_NAME` at the top of this script to match the exact name
    #      of the Blender object you want to control (e.g., an Empty, a Bone, or a Mesh object
    #      that serves as the head's rotation pivot).
    #    - Ensure `TCP_IP` and `TCP_PORT` match your face tracking server's output configuration
    #      for Blender (e.g., server sends to port 9999, Blender listens on 9999).
    #      `0.0.0.0` makes Blender listen on all network interfaces.
    #    - Adjust `MIN_TILT_ANGLE_DEG` and `MAX_TILT_ANGLE_DEG` to define the desired
    #      range of motion for the tilt.
    # 6. Click "Run Script" (the play button icon in the Text Editor header).
    #
    # 7. **Controlling the Server:**
    #    - After running the script, a new panel named "Face Track Tilt Receiver"
    #      should appear in the 3D Viewport's UI panel (press 'N' if it's hidden,
    #      look under the "Tool" tab or the category you set for `bl_category`).
    #    - Click "Start Server" in this panel.
    #    - The Blender console (Window > Toggle System Console) will show messages like
    #      "Blender TCP Server listening..."
    #    - Your external face tracking server application can now connect and send JSON data.
    #    - The target object should tilt based on the received `face_center_y` data.
    #    - Click "Stop Server" to shut down the listener.
    #
    # 8. **Troubleshooting:**
    #    - Check Blender's System Console for error messages.
    #    - Ensure the `TARGET_OBJECT_NAME` is correct and the object exists.
    #    - Verify firewall settings are not blocking the `TCP_PORT`.
    #    - Make sure the JSON data format sent by the server matches exactly what this
    #      script expects (see the JSON structure in the script's comments or the problem description).
    #    - The `update_object_tilt` function uses `rotation_euler.x`. If your object's
    #      local X-axis is not the desired tilt axis, you might need to change it to `.y` or `.z`,
    #      or parent the control object to another Empty and rotate that Empty.
    #
    # To make changes to IP/Port/Target Object Name after initial run without UI elements for them:
    #   - Stop the server using the UI panel.
    #   - Modify the script text.
    #   - Run the script again (this will unregister and re-register the addon).
    #   - Start the server again.
    #
    # This script registers itself as a mini-addon with UI controls.
    # If you save your .blend file after running the script, Blender might ask if you want to
    # "Register" the script on load. You can allow this if you want it to be active when opening the file.
    # Otherwise, you'll need to run the script manually each time you open the .blend file.

    # Unregister first if script was run before, to prevent errors on re-run
    # This is good practice for script development in Blender
    try:
        unregister()
    except Exception: # Catches errors if classes weren't registered yet
        pass
    register()

    print("-" * 30)
    print("Blender Tilt Receiver Script Loaded.")
    print(f"Target Object: {TARGET_OBJECT_NAME}")
    print(f"Listening on: {TCP_IP}:{TCP_PORT}")
    print(f"Tilt Range (Degrees): {MIN_TILT_ANGLE_DEG} to {MAX_TILT_ANGLE_DEG}")
    print("Find the 'Face Track Tilt Receiver' panel in the 3D View's UI (N-panel) to start/stop.")
    print("-" * 30)