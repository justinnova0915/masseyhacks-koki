# blink.py (updated to save the scene)
import bpy
import random

# --- Constants based on typical usage (can be overridden) ---
LEFT_EYE_PLANE = "L eye"
RIGHT_EYE_PLANE = "R eye"
LEFT_BLINK_PROPERTY = "Blink_R" # Note: Property names seem swapped in original config
RIGHT_BLINK_PROPERTY = "Blink_L" # Note: Property names seem swapped in original config
EYE_CONTROL_EMPTY = "Empty.002"
ARMATURE_OBJECT_NAME = "Eye_brows"
LEFT_EYEBROW_BONE = "L_pos"
RIGHT_EYEBROW_BONE = "R_pos"
BLINK_DURATION_FRAMES = 2
EYEBROW_LOWER_AMOUNT = 0.2 # Match the value from __main__
MAX_EYE_SHIFT_Y_AMOUNT = 0.8 # Match the value from __main__
MAX_EYE_SHIFT_Z_AMOUNT = 0.8 # Match the value from __main__


def trigger_blink(
    left_object_name=LEFT_EYE_PLANE,
    right_object_name=RIGHT_EYE_PLANE,
    left_blink_property=LEFT_BLINK_PROPERTY,
    right_blink_property=RIGHT_BLINK_PROPERTY,
    empty_control_object_name=EYE_CONTROL_EMPTY,
    armature_name=ARMATURE_OBJECT_NAME,
    left_brow_bone_name=LEFT_EYEBROW_BONE,
    right_brow_bone_name=RIGHT_EYEBROW_BONE,
    blink_duration_frames=BLINK_DURATION_FRAMES,
    brow_lower_amount=EYEBROW_LOWER_AMOUNT,
    max_eye_shift_y=MAX_EYE_SHIFT_Y_AMOUNT,
    max_eye_shift_z=MAX_EYE_SHIFT_Z_AMOUNT
):
    """Triggers a single blink event with associated movements at the current frame."""
    try:
        current_frame = bpy.context.scene.frame_current
        blink_start_frame = current_frame
        blink_end_frame = blink_start_frame + blink_duration_frames

        left_obj = bpy.data.objects.get(left_object_name)
        right_obj = bpy.data.objects.get(right_object_name)
        empty_control = bpy.data.objects.get(empty_control_object_name)
        armature = bpy.data.objects.get(armature_name)

        if not left_obj or not right_obj:
            print(f"Error: Blink objects '{left_object_name}' or '{right_object_name}' not found.")
            return
        if left_blink_property not in left_obj or right_blink_property not in right_obj:
            print(f"Error: Blink properties not found on objects.")
            return

        left_brow = armature.pose.bones.get(left_brow_bone_name) if armature else None
        right_brow = armature.pose.bones.get(right_brow_bone_name) if armature else None

        # Store initial positions (relative to this blink action)
        initial_empty_location = empty_control.location.copy() if empty_control else None
        initial_left_brow_location = left_brow.location.copy() if left_brow else None
        initial_right_brow_location = right_brow.location.copy() if right_brow else None

        print(f"Triggering single blink at frame {current_frame}")

        # --- Sudden Eye Movement at Blink Start ---
        if empty_control and initial_empty_location:
            random_shift_y = random.uniform(-max_eye_shift_y, max_eye_shift_y)
            random_shift_z = random.uniform(-max_eye_shift_z, max_eye_shift_z)
            shifted_y = initial_empty_location[1] + random_shift_y
            shifted_z = initial_empty_location[2] + random_shift_z

            # Keyframe shift start
            empty_control.location[1] = shifted_y
            empty_control.location[2] = shifted_z
            empty_control.keyframe_insert(data_path="location", frame=blink_start_frame, group="Eye Movement")

            # Keyframe shift end (hold the shifted position during blink)
            empty_control.location[1] = shifted_y
            empty_control.location[2] = shifted_z
            empty_control.keyframe_insert(data_path="location", frame=blink_end_frame, group="Eye Movement")

            # Keyframe return to initial position after blink
            empty_control.location[1] = initial_empty_location[1]
            empty_control.location[2] = initial_empty_location[2]
            empty_control.keyframe_insert(data_path="location", frame=blink_end_frame + 1, group="Eye Movement")

        # --- Sharp Eyebrow Lowering at Blink Start ---
        if left_brow and initial_left_brow_location:
            left_brow.location[1] = initial_left_brow_location[1] - brow_lower_amount
            left_brow.keyframe_insert(data_path="location", frame=blink_start_frame, group="Eyebrows")
        if right_brow and initial_right_brow_location:
            right_brow.location[1] = initial_right_brow_location[1] - brow_lower_amount
            right_brow.keyframe_insert(data_path="location", frame=blink_start_frame, group="Eyebrows")

        # --- Trigger Blink ---
        left_obj[left_blink_property] = True
        left_obj.keyframe_insert(data_path=f'["{left_blink_property}"]', frame=blink_start_frame, group="Blinking")
        right_obj[right_blink_property] = True
        right_obj.keyframe_insert(data_path=f'["{right_blink_property}"]', frame=blink_start_frame, group="Blinking")

        # --- End Blink ---
        left_obj[left_blink_property] = False
        left_obj.keyframe_insert(data_path=f'["{left_blink_property}"]', frame=blink_end_frame, group="Blinking")
        right_obj[right_blink_property] = False
        right_obj.keyframe_insert(data_path=f'["{right_blink_property}"]', frame=blink_end_frame, group="Blinking")

        # --- Sharp Eyebrow Reset at Blink End ---
        if left_brow and initial_left_brow_location:
            left_brow.location[1] = initial_left_brow_location[1]
            left_brow.keyframe_insert(data_path="location", frame=blink_end_frame, group="Eyebrows")
        if right_brow and initial_right_brow_location:
            right_brow.location[1] = initial_right_brow_location[1]
            right_brow.keyframe_insert(data_path="location", frame=blink_end_frame, group="Eyebrows")

        # Optional: Set interpolation for the new keyframes if needed (e.g., CONSTANT)
        # This might require iterating through fcurves similar to the generation function

        print(f"Single blink keyframes inserted from {blink_start_frame} to {blink_end_frame}.")

        # Save the scene? Might be too frequent if called often. Consider saving elsewhere.
        # bpy.ops.wm.save_mainfile()

    except Exception as e:
        print(f"An error occurred during trigger_blink: {e}")


# --- Function to generate random blinks over time (Original Function) ---
def add_synchronized_blinking_with_sharp_eye_brow_movement(
    left_object_name, right_object_name, left_blink_property, right_blink_property,
    empty_control_object_name="Empty.002",
    armature_name="Eye_brows",
    left_brow_bone_name="L_pos",
    right_brow_bone_name="R_pos",
    min_interval_seconds=2.0, max_interval_seconds=5.0, blink_duration_frames=2,
    max_eye_shift_y=0.2,
    max_eye_shift_z=0.2,
    brow_lower_amount=0.05
):
    try:
        left_obj = bpy.data.objects[left_object_name]
        right_obj = bpy.data.objects[right_object_name]
        empty_control = bpy.data.objects.get(empty_control_object_name)
        armature = bpy.data.objects.get(armature_name)

        if not empty_control:
            print(f"Warning: Control object '{empty_control_object_name}' not found.")
        if not armature:
            print(f"Error: Armature object '{armature_name}' not found.")
            return

        left_brow = armature.pose.bones.get(left_brow_bone_name)
        right_brow = armature.pose.bones.get(right_brow_bone_name)

        if not left_brow:
            print(f"Warning: Left brow bone '{left_brow_bone_name}' not found in armature.")
        if not right_brow:
            print(f"Warning: Right brow bone '{right_brow_bone_name}' not found in armature.")

        if left_blink_property not in left_obj or right_blink_property not in right_obj:
            print(f"Error: One or both blink properties not found on the specified objects.")
            return

        # --- AGGRESSIVE CLEARING OF ARMATURE ANIMATION ---
        if armature.animation_data:
            armature.animation_data_clear()
            print(f"Cleared all animation data from armature '{armature_name}'.")

        # Clear existing keyframes for blinking
        if left_obj.animation_data and left_obj.animation_data.action:
            for fcurve in left_obj.animation_data.action.fcurves:
                if fcurve.data_path == f'["{left_blink_property}"]':
                    bpy.data.actions.remove(left_obj.animation_data.action)
                    left_obj.animation_data_clear()
                    break
            else:
                bpy.data.actions.remove(left_obj.animation_data.action)
                left_obj.animation_data_clear()
        elif left_obj.animation_data:
            left_obj.animation_data_clear()
        if right_obj.animation_data and right_obj.animation_data.action:
            for fcurve in right_obj.animation_data.action.fcurves:
                if fcurve.data_path == f'["{right_blink_property}"]':
                    bpy.data.actions.remove(right_obj.animation_data.action)
                    right_obj.animation_data_clear()
                    break
            else:
                bpy.data.actions.remove(right_obj.animation_data.action)
                right_obj.animation_data_clear()
        elif right_obj.animation_data:
            right_obj.animation_data_clear()

        # Clear existing keyframes for eye movement
        if empty_control and empty_control.animation_data and empty_control.animation_data.action:
            action = empty_control.animation_data.action
            for fcurve in list(action.fcurves):
                if fcurve.data_path == "location":
                    action.fcurves.remove(fcurve)
            if not action.fcurves:
                bpy.data.actions.remove(action)
                empty_control.animation_data_clear()
        elif empty_control and empty_control.animation_data:
            empty_control.animation_data_clear()

        scene_fps = bpy.context.scene.render.fps
        total_frames = bpy.context.scene.frame_end
        current_frame = 1

        # Set initial Empty position
        if empty_control:
            empty_control.location[1] = 1.8
            empty_control.location[2] = 0.0
            empty_control.keyframe_insert(data_path="location", frame=1, group="Eye Movement")
            initial_empty_location = empty_control.location.copy()
            # Set interpolation to constant for initial keyframe
            if empty_control.animation_data and empty_control.animation_data.action:
                for index in [1, 2]:  # Y and Z axes
                    fcurve = empty_control.animation_data.action.fcurves.find("location", index=index)
                    if fcurve:
                        for keyframe in fcurve.keyframe_points:
                            if keyframe.co[0] == 1:
                                keyframe.interpolation = 'CONSTANT'

        # Store initial brow positions
        initial_left_brow_location = left_brow.location.copy() if left_brow else None
        initial_right_brow_location = right_brow.location.copy() if right_brow else None

        # --- Reset bone positions to initial values and keyframe ---
        if left_brow and initial_left_brow_location:
            left_brow.location = initial_left_brow_location  # Reset all axes
            left_brow.keyframe_insert(data_path="location", frame=1, group="Eyebrows")
            # Set interpolation to constant for initial keyframe
            if armature.animation_data and armature.animation_data.action:
                fcurve = armature.animation_data.action.fcurves.find(f'pose.bones["{left_brow_bone_name}"].location', index=1)
                if fcurve:
                    for keyframe in fcurve.keyframe_points:
                        if keyframe.co[0] == 1:
                            keyframe.interpolation = 'CONSTANT'
        if right_brow and initial_right_brow_location:
            right_brow.location = initial_right_brow_location  # Reset all axes
            right_brow.keyframe_insert(data_path="location", frame=1, group="Eyebrows")
            # Set interpolation to constant for initial keyframe
            if armature.animation_data and armature.animation_data.action:
                fcurve = armature.animation_data.action.fcurves.find(f'pose.bones["{right_brow_bone_name}"].location', index=1)
                if fcurve:
                    for keyframe in fcurve.keyframe_points:
                        if keyframe.co[0] == 1:
                            keyframe.interpolation = 'CONSTANT'

        # Ensure initial blink state is open
        left_obj[left_blink_property] = False
        left_obj.keyframe_insert(data_path=f'["{left_blink_property}"]', frame=1, group="Blinking")
        right_obj[right_blink_property] = False
        right_obj.keyframe_insert(data_path=f'["{right_blink_property}"]', frame=1, group="Blinking")

        while current_frame < total_frames:
            blink_interval_frames = int(random.uniform(min_interval_seconds, max_interval_seconds) * scene_fps)
            blink_start_frame = current_frame + blink_interval_frames
            blink_end_frame = blink_start_frame + blink_duration_frames

            if blink_start_frame < total_frames:
                # --- Sudden Eye Movement at Blink Start ---
                if empty_control:
                    random_shift_y = random.uniform(-max_eye_shift_y, max_eye_shift_y)
                    random_shift_z = random.uniform(-max_eye_shift_z, max_eye_shift_z)
                    shifted_y = initial_empty_location[1] + random_shift_y
                    shifted_z = initial_empty_location[2] + random_shift_z
                    empty_control.location[1] = shifted_y
                    empty_control.keyframe_insert(data_path="location", frame=blink_start_frame, group="Eye Movement")
                    empty_control.location[2] = shifted_z
                    empty_control.keyframe_insert(data_path="location", frame=blink_start_frame, group="Eye Movement")
                    # Set interpolation to constant for blink start keyframes
                    if empty_control.animation_data and empty_control.animation_data.action:
                        for index in [1, 2]:  # Y and Z axes
                            fcurve = empty_control.animation_data.action.fcurves.find("location", index=index)
                            if fcurve:
                                for keyframe in fcurve.keyframe_points:
                                    if keyframe.co[0] == blink_start_frame:
                                        keyframe.interpolation = 'CONSTANT'
                    empty_control.location[1] = shifted_y
                    empty_control.keyframe_insert(data_path="location", frame=blink_end_frame, group="Eye Movement")
                    empty_control.location[2] = shifted_z
                    empty_control.keyframe_insert(data_path="location", frame=blink_end_frame, group="Eye Movement")
                    # Set interpolation to constant for blink end keyframes
                    if empty_control.animation_data and empty_control.animation_data.action:
                        for index in [1, 2]:  # Y and Z axes
                            fcurve = empty_control.animation_data.action.fcurves.find("location", index=index)
                            if fcurve:
                                for keyframe in fcurve.keyframe_points:
                                    if keyframe.co[0] == blink_end_frame:
                                        keyframe.interpolation = 'CONSTANT'

                # --- Sharp Eyebrow Lowering at Blink Start ---
                if left_brow and initial_left_brow_location:
                    left_brow.location[1] = initial_left_brow_location[1] - brow_lower_amount
                    left_brow.keyframe_insert(data_path="location", frame=blink_start_frame, group="Eyebrows")
                    # Set interpolation to constant
                    if armature.animation_data and armature.animation_data.action:
                        fcurve = armature.animation_data.action.fcurves.find(f'pose.bones["{left_brow_bone_name}"].location', index=1)
                        if fcurve:
                            for keyframe in fcurve.keyframe_points:
                                if keyframe.co[0] == blink_start_frame:
                                    keyframe.interpolation = 'CONSTANT'
                if right_brow and initial_right_brow_location:
                    right_brow.location[1] = initial_right_brow_location[1] - brow_lower_amount
                    right_brow.keyframe_insert(data_path="location", frame=blink_start_frame, group="Eyebrows")
                    # Set interpolation to constant
                    if armature.animation_data and armature.animation_data.action:
                        fcurve = armature.animation_data.action.fcurves.find(f'pose.bones["{right_brow_bone_name}"].location', index=1)
                        if fcurve:
                            for keyframe in fcurve.keyframe_points:
                                if keyframe.co[0] == blink_start_frame:
                                    keyframe.interpolation = 'CONSTANT'

                # --- Trigger Blink ---
                left_obj[left_blink_property] = True
                left_obj.keyframe_insert(data_path=f'["{left_blink_property}"]', frame=blink_start_frame, group="Blinking")
                right_obj[right_blink_property] = True
                right_obj.keyframe_insert(data_path=f'["{right_blink_property}"]', frame=blink_start_frame, group="Blinking")

            if blink_end_frame < total_frames:
                # Set blink back to open
                left_obj[left_blink_property] = False
                left_obj.keyframe_insert(data_path=f'["{left_blink_property}"]', frame=blink_end_frame, group="Blinking")
                right_obj[right_blink_property] = False
                right_obj.keyframe_insert(data_path=f'["{right_blink_property}"]', frame=blink_end_frame, group="Blinking")

                # --- Sharp Eyebrow Reset at Blink End ---
                if left_brow and initial_left_brow_location:
                    left_brow.location[1] = initial_left_brow_location[1]
                    left_brow.keyframe_insert(data_path="location", frame=blink_end_frame, group="Eyebrows")
                    # Set interpolation to constant for the return
                    if armature.animation_data and armature.animation_data.action:
                        fcurve = armature.animation_data.action.fcurves.find(f'pose.bones["{left_brow_bone_name}"].location', index=1)
                        if fcurve:
                            for keyframe in fcurve.keyframe_points:
                                if keyframe.co[0] == blink_end_frame:
                                    keyframe.interpolation = 'CONSTANT'
                if right_brow and initial_right_brow_location:
                    right_brow.location[1] = initial_right_brow_location[1]
                    right_brow.keyframe_insert(data_path="location", frame=blink_end_frame, group="Eyebrows")
                    # Set interpolation to constant for the return
                    if armature.animation_data and armature.animation_data.action:
                        fcurve = armature.animation_data.action.fcurves.find(f'pose.bones["{right_brow_bone_name}"].location', index=1)
                        if fcurve:
                            for keyframe in fcurve.keyframe_points:
                                if keyframe.co[0] == blink_end_frame:
                                    keyframe.interpolation = 'CONSTANT'

            current_frame = blink_end_frame

        print(f"Synchronized blinking with sharp eyebrow movement added. Blinks occur every {min_interval_seconds}-{max_interval_seconds} seconds, last for {blink_duration_frames} frames. Eyebrows (L_pos and R_pos) within armature 'Eye_brows' sharply lower by {brow_lower_amount} on the Y-axis during the blink.")

        # Save the scene to ensure keyframes are persisted
        bpy.ops.wm.save_mainfile()
        print("Saved Blender scene with updated keyframes.")

    except KeyError:
        print(f"Error: One of the specified objects not found.")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    # --- Configuration for Synchronized Blinking with Sharp Eye and Brow Movement ---
    # --- Configuration for Standalone Execution (Generates full sequence) ---
    # Use constants defined at the top
    min_blink_interval_seconds = 1.5
    max_blink_interval_seconds = 10.5

    print("Running blink.py standalone: Generating full blink sequence...")
    add_synchronized_blinking_with_sharp_eye_brow_movement(
        LEFT_EYE_PLANE, RIGHT_EYE_PLANE, LEFT_BLINK_PROPERTY, RIGHT_BLINK_PROPERTY,
        EYE_CONTROL_EMPTY,
        ARMATURE_OBJECT_NAME,
        LEFT_EYEBROW_BONE,
        RIGHT_EYEBROW_BONE,
        min_blink_interval_seconds, max_blink_interval_seconds, BLINK_DURATION_FRAMES,
        MAX_EYE_SHIFT_Y_AMOUNT,
        MAX_EYE_SHIFT_Z_AMOUNT,
        EYEBROW_LOWER_AMOUNT
    )
    print("Standalone blink sequence generation complete.")

    # Example of how to test the single trigger function (optional)
    # print("\nTesting single blink trigger...")
    # bpy.context.scene.frame_set(50) # Go to a specific frame
    # trigger_blink()
    # print("Single blink trigger test complete.")