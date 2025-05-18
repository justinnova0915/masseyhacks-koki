# Lip.py (fixed typo and enhanced logging)
import bpy
import re
import os

def set_keyframe_interpolation(obj, data_path, frame, interpolation='BEZIER'):
    """Set the interpolation type for a keyframe on the given data path."""
    # Removed internal debug logging
    if obj.animation_data and obj.animation_data.action:
        for fcurve in obj.animation_data.action.fcurves:
            if fcurve.data_path == data_path:
                for kf in fcurve.keyframe_points:
                    if kf.co.x == frame:
                        kf.interpolation = interpolation
                        # Set Bezier handles for smooth easing
                        kf.handle_left_type = 'AUTO_CLAMPED'  # Fixed typo
                        kf.handle_right_type = 'AUTO_CLAMPED'
                        break
                break # Exit fcurve loop once found

def apply_rhubarb_lipsync(filepath, object_name, shape_key_mapping, scene_fps, min_frames_per_phoneme=4):
    try:
        print(f"Starting lip-sync application for object '{object_name}' with file '{filepath}'")
        
        # Check if object exists
        obj = bpy.data.objects[object_name]
        if not obj.data.shape_keys:
            print(f"Error: Object '{object_name}' has no shape keys.")
            return

        print(f"Found object '{object_name}' with shape keys.")

        # Clear existing animation data to start fresh
        if obj.animation_data:
            obj.animation_data_clear()
            print(f"Cleared existing animation data from object '{object_name}'.")
        else:
             print(f"No existing animation data found on object '{object_name}'.") # Added else for clarity

        # Removed explicit animation_data/action creation block

        # Read Rhubarb file
        if not os.path.exists(filepath):
            print(f"Error: File not found at '{filepath}'.")
            return
        
        with open(filepath, 'r') as f:
            lines = f.readlines()
        print(f"Read {len(lines)} lines from Rhubarb file '{filepath}'.")

        # Initialize: set all shape keys to 0 at frame 1
        for sk_name in shape_key_mapping.values():
            if sk_name in obj.data.shape_keys.key_blocks:
                shape_key = obj.data.shape_keys.key_blocks[sk_name]
                shape_key.value = 0.0
                shape_key.keyframe_insert(data_path="value", frame=1)
                # Ensure action exists before setting interpolation (Attempt 2)
                if not obj.animation_data or not obj.animation_data.action:
                    print(f"WARN: Action missing before interpolation for {sk_name}. Attempting recovery.")
                    if not obj.animation_data: obj.animation_data_create()
                    if not obj.animation_data.action: obj.animation_data.action = bpy.data.actions.new(name=f"{obj.name}Action_InitFix")
                set_keyframe_interpolation(obj=obj, data_path=f'key_blocks["{sk_name}"].value', frame=1) # FIX: Pass obj, not obj.data.shape_keys
                print(f"Initialized shape key '{sk_name}' to 0 at frame 1.")
            else:
                print(f"Warning: Shape key '{sk_name}' not found on object '{object_name}'.")

        # Initialize custom properties at frame 1
        if all(prop in obj for prop in ["height", "width", "x", "y", "Tongue", "Teeth"]):
            for prop in ["width", "height"]:
                obj[prop] = 1.0
                obj.keyframe_insert(data_path=f'["{prop}"]', frame=1)
                # Ensure action exists before setting interpolation (Attempt 2)
                if not obj.animation_data or not obj.animation_data.action:
                    print(f"WARN: Action missing before interpolation for {prop}. Attempting recovery.")
                    if not obj.animation_data: obj.animation_data_create()
                    if not obj.animation_data.action: obj.animation_data.action = bpy.data.actions.new(name=f"{obj.name}Action_InitFix")
                set_keyframe_interpolation(obj=obj, data_path=f'["{prop}"]', frame=1)
                print(f"Initialized custom property '{prop}' to 1.0 at frame 1.")
            for prop in ["x", "y", "Tongue", "Teeth"]:
                obj[prop] = 0.0 if prop in ["x", "y"] else False
                obj.keyframe_insert(data_path=f'["{prop}"]', frame=1)
                # Ensure action exists before setting interpolation (Attempt 2)
                if not obj.animation_data or not obj.animation_data.action:
                    print(f"WARN: Action missing before interpolation for {prop}. Attempting recovery.")
                    if not obj.animation_data: obj.animation_data_create()
                    if not obj.animation_data.action: obj.animation_data.action = bpy.data.actions.new(name=f"{obj.name}Action_InitFix")
                set_keyframe_interpolation(obj=obj, data_path=f'["{prop}"]', frame=1)
                print(f"Initialized custom property '{prop}' to default at frame 1.")
        else:
            print(f"Warning: Not all custom properties ['height', 'width', 'x', 'y', 'Tongue', 'Teeth'] found on object '{object_name}'.")

        # Track the last frame
        last_frame = 1
        phoneme_data = []

        # First pass: collect phoneme timings and enforce minimum duration
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = line.split('\t')
            if len(parts) != 2:
                print(f"Warning: Unexpected line format: {line}")
                continue

            timestamp_str, phoneme = parts
            try:
                timestamp = float(timestamp_str)
                frame_number = int(timestamp * scene_fps)
                # Enforce minimum duration: if too close to the last frame, push it forward
                if frame_number < last_frame + min_frames_per_phoneme:
                    frame_number = last_frame + min_frames_per_phoneme
                phoneme_data.append((frame_number, phoneme))
                last_frame = frame_number
                print(f"Processed phoneme '{phoneme}' at timestamp {timestamp} (frame {frame_number}).")
            except ValueError:
                print(f"Warning: Invalid timestamp: {timestamp_str}")

        # Second pass: create keyframes with smooth transitions
        for i, (frame_number, phoneme) in enumerate(phoneme_data):
            # Calculate the midpoint for holding the phoneme
            hold_frame = frame_number - min_frames_per_phoneme // 2  # Start holding a bit before the peak
            if hold_frame < 1:
                hold_frame = 1

            # Handle shape keys
            if phoneme in shape_key_mapping:
                shape_key_to_activate_name = shape_key_mapping[phoneme]
                if shape_key_to_activate_name in obj.data.shape_keys.key_blocks:
                    shape_key_to_activate = obj.data.shape_keys.key_blocks[shape_key_to_activate_name]

                    # Start ramping up to 1.0 a bit before the peak
                    shape_key_to_activate.value = 0.0
                    shape_key_to_activate.keyframe_insert(data_path="value", frame=hold_frame - min_frames_per_phoneme // 2)
                    set_keyframe_interpolation(obj=obj, data_path=f'key_blocks["{shape_key_to_activate_name}"].value', frame=hold_frame - min_frames_per_phoneme // 2) # FIX: Pass obj
                    print(f"Set shape key '{shape_key_to_activate_name}' to 0.0 at frame {hold_frame - min_frames_per_phoneme // 2}.")

                    # Hold at 1.0 for the minimum duration
                    shape_key_to_activate.value = 1.0
                    shape_key_to_activate.keyframe_insert(data_path="value", frame=hold_frame)
                    set_keyframe_interpolation(obj=obj, data_path=f'key_blocks["{shape_key_to_activate_name}"].value', frame=hold_frame) # FIX: Pass obj
                    print(f"Set shape key '{shape_key_to_activate_name}' to 1.0 at frame {hold_frame}.")

                    # Start ramping down after the hold
                    if i < len(phoneme_data) - 1:  # If there's a next phoneme
                        next_frame = phoneme_data[i + 1][0]
                        next_hold_frame = next_frame - min_frames_per_phoneme // 2
                        shape_key_to_activate.value = 0.0
                        shape_key_to_activate.keyframe_insert(data_path="value", frame=next_hold_frame - min_frames_per_phoneme // 2)
                        set_keyframe_interpolation(obj=obj, data_path=f'key_blocks["{shape_key_to_activate_name}"].value', frame=next_hold_frame - min_frames_per_phoneme // 2) # FIX: Pass obj
                        print(f"Set shape key '{shape_key_to_activate_name}' to 0.0 at frame {next_hold_frame - min_frames_per_phoneme // 2}.")
                else:
                    print(f"Warning: Shape key '{shape_key_to_activate_name}' for phoneme '{phoneme}' not found on object '{object_name}'.")

            # Handle custom properties
            if all(prop in obj for prop in ["height", "width", "x", "y", "Tongue", "Teeth"]):
                width_value = 1.0
                height_value = 1.0
                x_value = 0.0
                y_value = 0.0
                tongue = False
                teeth = False

                if phoneme == "A":
                    width_value = -0.224
                    height_value = 0.487
                    x_value = 0
                    y_value = 3.509
                    tongue = True
                    teeth = True
                elif phoneme == "B":
                    tongue = False
                    teeth = False
                elif phoneme == "C":
                    width_value = 1.413
                    height_value = 0.487
                    x_value = 0
                    y_value = 2.589
                    tongue = True
                    teeth = True
                elif phoneme == "D":
                    width_value = 1.413
                    height_value = 0.487
                    x_value = 0
                    y_value = 2.589
                    tongue = True
                    teeth = True
                elif phoneme == "E":
                    width_value = -0.417
                    height_value = 0.155
                    x_value = 0.011
                    y_value = 3.564
                    tongue = True
                    teeth = True
                elif phoneme == "F":
                    tongue = False
                    teeth = True
                elif phoneme == "G":
                    width_value = 2.442
                    height_value = 0.158
                    x_value = 0.192
                    y_value = 1.859
                    tongue = True
                    teeth = True
                elif phoneme == "H":
                    width_value = 2.024
                    height_value = 0.497
                    x_value = 0.010
                    y_value = 2.216
                    tongue = True
                    teeth = True
                elif phoneme == "X":
                    width_value = 1.0
                    height_value = 1.0
                    x_value = 0.0
                    y_value = 0.0
                    tongue = False
                    teeth = False
                elif phoneme == "L":
                    width_value = 2.024
                    height_value = 0.497
                    x_value = 0.010
                    y_value = 2.216
                    tongue = True
                    teeth = True

                # Keyframe custom properties
                for prop, value in [
                    ("width", width_value),
                    ("height", height_value),
                    ("x", x_value),
                    ("y", y_value),
                    ("Tongue", tongue),
                    ("Teeth", teeth)
                ]:
                    # Ramp up to the value
                    default = 1.0 if prop in ["width", "height"] else 0.0 if prop in ["x", "y"] else False
                    obj[prop] = default
                    obj.keyframe_insert(data_path=f'["{prop}"]', frame=hold_frame - min_frames_per_phoneme // 2)
                    set_keyframe_interpolation(obj=obj, data_path=f'["{prop}"]', frame=hold_frame - min_frames_per_phoneme // 2)
                    print(f"Set custom property '{prop}' to {default} at frame {hold_frame - min_frames_per_phoneme // 2}.")

                    # Hold the value
                    obj[prop] = value
                    obj.keyframe_insert(data_path=f'["{prop}"]', frame=hold_frame)
                    set_keyframe_interpolation(obj=obj, data_path=f'["{prop}"]', frame=hold_frame)
                    print(f"Set custom property '{prop}' to {value} at frame {hold_frame}.")

                    # Ramp back to default
                    if i < len(phoneme_data) - 1:  # If there's a next phoneme
                        next_frame = phoneme_data[i + 1][0]
                        next_hold_frame = next_frame - min_frames_per_phoneme // 2
                        obj[prop] = default
                        obj.keyframe_insert(data_path=f'["{prop}"]', frame=next_hold_frame - min_frames_per_phoneme // 2)
                        set_keyframe_interpolation(obj=obj, data_path=f'["{prop}"]', frame=next_hold_frame - min_frames_per_phoneme // 2)
                        print(f"Set custom property '{prop}' to {default} at frame {next_hold_frame - min_frames_per_phoneme // 2}.")

        # Final reset at the end
        last_frame = phoneme_data[-1][0] if phoneme_data else 1
        end_frame = last_frame + min_frames_per_phoneme  # Extend after the last phoneme

        # Reset all shape keys to 0
        for sk_name in shape_key_mapping.values():
            if sk_name in obj.data.shape_keys.key_blocks:
                shape_key = obj.data.shape_keys.key_blocks[sk_name]
                shape_key.value = 0.0
                shape_key.keyframe_insert(data_path="value", frame=end_frame)
                set_keyframe_interpolation(obj=obj, data_path=f'key_blocks["{sk_name}"].value', frame=end_frame) # FIX: Pass obj
                print(f"Reset shape key '{sk_name}' to 0 at frame {end_frame}.")

        # Reset custom properties
        if all(prop in obj for prop in ["height", "width", "x", "y", "Tongue", "Teeth"]):
            for prop in ["width", "height"]:
                obj[prop] = 1.0
                obj.keyframe_insert(data_path=f'["{prop}"]', frame=end_frame)
                set_keyframe_interpolation(obj=obj, data_path=f'["{prop}"]', frame=end_frame)
                print(f"Reset custom property '{prop}' to 1.0 at frame {end_frame}.")
            for prop in ["x", "y", "Tongue", "Teeth"]:
                default = 0.0 if prop in ["x", "y"] else False
                obj[prop] = default
                obj.keyframe_insert(data_path=f'["{prop}"]', frame=end_frame)
                set_keyframe_interpolation(obj=obj, data_path=f'["{prop}"]', frame=end_frame)
                print(f"Reset custom property '{prop}' to {default} at frame {end_frame}.")

        print("Rhubarb lip sync applied with Bezier interpolation and minimum phoneme duration to avoid flashing.")

        # Save the scene to ensure keyframes are persisted
        bpy.ops.wm.save_mainfile()
        print("Saved Blender scene with updated keyframes.")

    except KeyError:
        print(f"Error: Object '{object_name}' not found.")
    except FileNotFoundError:
        print(f"Error: File not found at '{filepath}'.")
    except Exception as e:
        print(f"An error occurred: {e}")

# --- Main execution block (for standalone testing) ---
if __name__ == "__main__":
    print("Running Lip.py as standalone script for testing.")
    
    # --- Configuration (for standalone testing) ---
    # Use the default output file expected from real_time_ai_agent.py
    rhubarb_file_path = "C:\\Users\\justi\\PycharmProjects\\Kokoro\\output.txt"
    target_object_name = "Mouth" # Make sure this matches your Blender object
    scene_fps = bpy.context.scene.render.fps # Get FPS from the current scene
    min_frames_per_phoneme = 4  # Minimum frames to hold each phoneme

    phoneme_to_shapekey = {
        "A": "A",
        "B": "B_CHJSH",
        "C": "C",
        "D": "D",
        "E": "E_R",
        "F": "F",
        "G": "G",
        "H": "H",
        "X": "X", # Assuming 'X' is the neutral/rest pose
        "L": "L"
        # Add other phonemes used by Rhubarb if necessary
    }

    # Check if the default rhubarb file exists before running
    if os.path.exists(rhubarb_file_path):
        print(f"Found test file: {rhubarb_file_path}")
        apply_rhubarb_lipsync(rhubarb_file_path, target_object_name, phoneme_to_shapekey, scene_fps, min_frames_per_phoneme)
        print("Standalone test finished.")
    else:
        print(f"Test file {rhubarb_file_path} not found. Skipping standalone execution.")
        print("To test, ensure 'output.txt' exists in the Kokoro directory.")