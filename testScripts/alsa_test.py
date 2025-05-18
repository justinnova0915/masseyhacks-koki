import sounddevice as sd
import numpy as np
import time
import argparse

# --- Configuration ---
DEFAULT_SAMPLE_RATE = 44100  # Hz
DEFAULT_CHANNELS = 1         # Mono
DELAY_SECONDS = 0.5          # Seconds
BUFFER_DURATION = 0.05         # Duration of each audio chunk in seconds (blocksize for the stream). Default to 50ms.

def record_and_play_with_delay(samplerate=DEFAULT_SAMPLE_RATE, channels=DEFAULT_CHANNELS, delay=DELAY_SECONDS, buffer_duration=BUFFER_DURATION, input_device_index=None, output_device_index=None):
    """
    Captures audio from the specified/default input, delays it, and plays it on the specified/default output.
    """
    print(f"Starting ALSA loopback test with {delay}s delay.")
    print(f"Sample rate: {samplerate} Hz, Channels: {channels}")
    print(f"Buffer/Block duration: {buffer_duration}s")
    print(f"Press Ctrl+C to stop.")

    try:
        print("\n--- Audio Device Information ---")
        print("Available audio devices:")
        print(sd.query_devices())
        default_input_device = sd.query_devices(kind='input')
        default_output_device = sd.query_devices(kind='output')
        
        selected_input_device_info = sd.query_devices(device=input_device_index) if input_device_index is not None else default_input_device
        selected_output_device_info = sd.query_devices(device=output_device_index) if output_device_index is not None else default_output_device

        print(f"Using Input Device: {selected_input_device_info['name']} (Index: {selected_input_device_info['index']})")
        print(f"Using Output Device: {selected_output_device_info['name']} (Index: {selected_output_device_info['index']})")
        print("--- End Audio Device Information ---\n")

        delay_frames_target = int(delay * samplerate)
        buffer_frames_per_callback = int(buffer_duration * samplerate)

        if delay_frames_target <= 0:
            print("Delay is zero or non-positive. Using passthrough (no delay).")
            def passthrough_callback(indata, outdata, frames, time_info, status):
                if status:
                    print(f"Stream status: {status}")
                # Diagnostic print for passthrough
                # print(f"Passthrough - Indata min: {np.min(indata):.4f}, max: {np.max(indata):.4f}")
                outdata[:] = indata
            
            with sd.Stream(device=(input_device_index, output_device_index),
                           samplerate=samplerate,
                           channels=channels,
                           dtype='float32',
                           callback=passthrough_callback,
                           blocksize=buffer_frames_per_callback):
                print("Passthrough stream started...")
                while True:
                    time.sleep(0.1) # Keep the main thread alive
            return # Exit if passthrough

        # Ring buffer to store audio data for the delay
        # Its size is determined by the desired delay in frames.
        ring_buffer = np.zeros((delay_frames_target, channels), dtype='float32')
        
        # g_write_idx points to the next location in ring_buffer to write an incoming frame.
        # g_read_idx points to the location in ring_buffer from which to read a frame for output.
        # The data at g_read_idx should be delay_frames_target old.
        # They both cycle through the ring_buffer.
        g_write_idx = 0
        g_read_idx = 0 # Starts at 0, will read initial zeros until buffer fills with delayed audio.
        callback_count = 0 # For diagnostic printing

        print(f"Ring buffer size (frames for delay): {delay_frames_target}")
        print(f"Block size (frames per callback): {buffer_frames_per_callback}")

        if buffer_frames_per_callback >= delay_frames_target and delay_frames_target > 0 :
            print("\nWARNING: The block size for each callback is greater than or equal to the target delay buffer size.")
            print("This configuration might lead to unexpected behavior or no audible delay.")
            print(f"  Block size (frames): {buffer_frames_per_callback} (from {buffer_duration}s buffer duration)")
            print(f"  Delay buffer (frames): {delay_frames_target} (from {delay}s delay)")
            print("Consider reducing --buffer_duration or increasing --delay.\n")
        elif delay_frames_target > 0 and buffer_frames_per_callback == 0:
             print("\nWARNING: Block size per callback is 0. This will likely not work. Increase --buffer_duration.\n")


        def delay_callback(indata, outdata, frames_in_block, time_info, status):
            nonlocal g_write_idx, g_read_idx, callback_count
            callback_count += 1
            if status:
                print(f"Stream status: {status}")
            
            # Diagnostic print more frequently now that block sizes are smaller
            # Print roughly every 0.5 seconds of processed audio, or at least every 200 callbacks
            callbacks_per_half_second = 0
            if buffer_frames_per_callback > 0:
                callbacks_per_half_second = int(0.5 * samplerate / buffer_frames_per_callback)
            
            print_interval = max(1, callbacks_per_half_second) # Ensure at least 1
            if callback_count % print_interval == 0 or callback_count < 5: # Print first few callbacks too
                 print(f"Callback {callback_count}: Indata min: {np.min(indata):.4f}, max: {np.max(indata):.4f} | Outdata (before fill) min: {np.min(outdata):.4f}, max: {np.max(outdata):.4f}")


            # frames_in_block will be equal to buffer_frames_per_callback
            for i in range(frames_in_block):
                # Output the delayed sample (from read_idx)
                outdata[i] = ring_buffer[g_read_idx]
                
                # Store the current input sample (to write_idx)
                ring_buffer[g_write_idx] = indata[i]
                
                # Advance indices, wrapping around the ring buffer
                g_read_idx = (g_read_idx + 1) % delay_frames_target
                g_write_idx = (g_write_idx + 1) % delay_frames_target
            
            if (callback_count % print_interval == 0 or callback_count < 5) and delay_frames_target > 0 :
                 print(f"Callback {callback_count}: Outdata (after fill) min: {np.min(outdata):.4f}, max: {np.max(outdata):.4f}")
        
        # Using Stream for simultaneous input and output
        with sd.Stream(device=(input_device_index, output_device_index),
                       samplerate=samplerate,
                       channels=channels,
                       dtype='float32',
                       callback=delay_callback,
                       blocksize=buffer_frames_per_callback): # Process in chunks of this size
            print("Delay stream started...")
            while True:
                time.sleep(0.1) # Keep the main thread alive

    except KeyboardInterrupt:
        print("\nLoopback test stopped by user.")
    except Exception as e:
        print(f"An error occurred: {e}")
        print("Please ensure you have a working ALSA setup and the 'sounddevice' Python package installed.")
        print("You might need to install system dependencies for PortAudio (which sounddevice uses):")
        print("  sudo apt-get install libasound2-dev portaudio19-dev")
        print("And then install sounddevice: pip install sounddevice numpy")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ALSA input/output test with delay.")
    parser.add_argument("--samplerate", type=int, default=DEFAULT_SAMPLE_RATE, help="Sample rate in Hz.")
    parser.add_argument("--channels", type=int, default=DEFAULT_CHANNELS, choices=[1, 2], help="Number of audio channels (1 for mono, 2 for stereo).")
    parser.add_argument("--delay", type=float, default=DELAY_SECONDS, help="Delay in seconds.")
    parser.add_argument("--buffer_duration", type=float, default=BUFFER_DURATION, help="Duration of audio chunks (blocksize) to process in seconds.")
    parser.add_argument("-i", "--input_device", type=int, help="Input device ID. See available devices list when run.")
    parser.add_argument("-o", "--output_device", type=int, help="Output device ID. See available devices list when run.")
    
    args = parser.parse_args()

    record_and_play_with_delay(samplerate=args.samplerate,
                               channels=args.channels,
                               delay=args.delay,
                               buffer_duration=args.buffer_duration,
                               input_device_index=args.input_device,
                               output_device_index=args.output_device)