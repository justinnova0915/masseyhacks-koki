import pyaudio
import socket
import time
import numpy as np
import argparse
import sys
import os
import subprocess
import warnings

# Suppress ALSA warnings and errors - this must be done BEFORE importing pyaudio
os.environ['ALSA_CARD'] = '3'  # Set default ALSA card
# Redirect stderr to /dev/null to suppress ALSA error messages
if hasattr(os, 'devnull'):
    devnull = open(os.devnull, 'w')
    old_stderr = os.dup(2)
    os.dup2(devnull.fileno(), 2)

# Add parent directory to path so we can import the config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from kokoro_config import (
        COMPUTER_IP, WAKE_WORD_PORT, STT_PORT, 
        CAPTURE_FORMAT, CAPTURE_CHANNELS, CAPTURE_RATE, CAPTURE_CHUNK_SIZE
    )
    # Override CAPTURE_RATE if it's not 48000 (USB mic native rate)
    if CAPTURE_RATE != 48000:
        print(f"Warning: Config specified {CAPTURE_RATE} Hz, but USB mic requires 48000 Hz. Using 48000 Hz.")
        CAPTURE_RATE = 48000
except ImportError:
    print("Config file not found. Using default values.")
    # Default values as fallback
    COMPUTER_IP = "192.168.2.160"  
    WAKE_WORD_PORT = 12347  
    STT_PORT = 12346  
    CAPTURE_FORMAT = "int16"
    CAPTURE_CHANNELS = 1
    CAPTURE_RATE = 48000  # Set to 48000 by default (USB mic native rate)
    CAPTURE_CHUNK_SIZE = 512

# Restore stderr now that imports are done
if 'old_stderr' in locals():
    os.dup2(old_stderr, 2)
    os.close(old_stderr)
    if 'devnull' in locals():
        devnull.close()

# Suppress warnings
warnings.filterwarnings("ignore", category=RuntimeWarning, module="pyaudio")

# Convert format string to PyAudio format
FORMAT_MAP = {
    "int16": pyaudio.paInt16,
    "int32": pyaudio.paInt32,
    "float32": pyaudio.paFloat32,
    "int8": pyaudio.paInt8,
    "uint8": pyaudio.paUInt8
}
FORMAT = FORMAT_MAP.get(CAPTURE_FORMAT, pyaudio.paInt16)

def run_shell_command(command):
    """Run shell command and return output"""
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                               shell=True, text=True, check=False)
        return result.stdout
    except Exception as e:
        return f"Error running command: {e}"

def get_alsa_devices():
    """Get ALSA devices using arecord -l"""
    return run_shell_command("arecord -l")

def get_alsa_info():
    """Get detailed ALSA info"""
    return run_shell_command("arecord -L")

def list_audio_devices():
    """List all available audio devices to help with troubleshooting"""
    info = "\nAvailable audio devices:\n"
    
    # Add ALSA information
    info += "\n--- ALSA Device List ---\n"
    info += get_alsa_devices() + "\n"
    
    # Add more detailed ALSA info
    info += "\n--- ALSA Detailed Info ---\n"
    info += get_alsa_info() + "\n"
    
    # Add PyAudio device info
    info += "\n--- PyAudio Device Info ---\n"
    try:
        p = pyaudio.PyAudio()
        for i in range(p.get_device_count()):
            try:
                dev_info = p.get_device_info_by_index(i)
                input_channels = dev_info.get('maxInputChannels', 0)
                
                if input_channels > 0:  # Only show devices with input capability
                    info += f"Device {i}: {dev_info.get('name')}\n"
                    info += f"  Input channels: {input_channels}\n"
                    info += f"  Default sample rate: {dev_info.get('defaultSampleRate')}\n"
            except Exception as e:
                info += f"Error getting device {i} info: {e}\n"
        p.terminate()
    except Exception as e:
        info += f"Error initializing PyAudio: {e}\n"
    
    return info

def get_device_supported_rates(device_index):
    """Get supported sample rates for the device"""
    try:
        p = pyaudio.PyAudio()
        device_info = p.get_device_info_by_index(device_index)
        p.terminate()
        
        # Common sample rates to test
        rates_to_test = [8000, 11025, 16000, 22050, 44100, 48000, 96000]
        supported_rates = []
        
        for rate in rates_to_test:
            # We test if the rate is supported by actually trying to open a stream
            # but with a very small buffer size and closing immediately
            try:
                p = pyaudio.PyAudio()
                stream = p.open(
                    format=FORMAT,
                    channels=1,
                    rate=rate,
                    input=True,
                    input_device_index=device_index,
                    frames_per_buffer=512,
                    start=False  # Don't actually start the stream
                )
                stream.close()
                p.terminate()
                supported_rates.append(rate)
            except Exception:
                pass
            finally:
                if 'p' in locals():
                    p.terminate()
        
        return supported_rates
    except Exception as e:
        print(f"Error getting supported rates: {e}")
        return []

def create_asoundrc(device_index=2):
    """Create a .asoundrc file in the user's home directory for better ALSA configuration"""
    home_dir = os.path.expanduser("~")
    asoundrc_path = os.path.join(home_dir, ".asoundrc")
    
    # Only create if it doesn't exist to avoid overwriting user customizations
    if not os.path.exists(asoundrc_path):
        try:
            with open(asoundrc_path, "w") as f:
                f.write(f"""
# ALSA config for better USB microphone support
pcm.!default {{
    type plug
    slave.pcm "hw:{device_index}"
}}
                
ctl.!default {{
    type hw
    card {device_index}
}}
                """)
            print(f"Created .asoundrc file at {asoundrc_path}")
            return True
        except Exception as e:
            print(f"Error creating .asoundrc file: {e}")
    return False

def main():
    parser = argparse.ArgumentParser(description="Send microphone audio from Raspberry Pi to computer")
    parser.add_argument("--computer_ip", default=COMPUTER_IP, help="IP address of the computer")
    parser.add_argument("--wake_port", type=int, default=WAKE_WORD_PORT, help="UDP port for wake word detection")
    parser.add_argument("--stt_port", type=int, default=STT_PORT, help="UDP port for speech recognition")
    parser.add_argument("--device", type=str, default="plughw:2,0", help="Audio input device (e.g., plughw:3,0 or 2)")
    parser.add_argument("--list_devices", action="store_true", help="List available audio devices and exit")
    parser.add_argument("--rate", type=int, default=CAPTURE_RATE, help="Audio sample rate (use 48000 for USB mic)")
    parser.add_argument("--channels", type=int, default=CAPTURE_CHANNELS, help="Audio channels (1=mono, 2=stereo)")
    parser.add_argument("--chunk_size", type=int, default=CAPTURE_CHUNK_SIZE, help="Audio chunk size")
    parser.add_argument("--quiet", action="store_true", help="Suppress informational messages")
    parser.add_argument("--create-asoundrc", action="store_true", help="Create a .asoundrc file for better audio config")
    args = parser.parse_args()
    
    # Create .asoundrc file if requested
    if args.create_asoundrc:
        device_num = 3  # Default
        if args.device.startswith("hw:") or args.device.startswith("plughw:"):
            try:
                device_num = int(args.device.split(":")[1].split(",")[0])
            except (IndexError, ValueError):
                pass
        elif args.device.isdigit():
            device_num = int(args.device)
        create_asoundrc(device_num)
    
    # Set up error redirection for quiet mode
    if args.quiet:
        old_stderr = sys.stderr
        sys.stderr = open(os.devnull, 'w')
    
    # Force sample rate to 48000 Hz for USB microphones
    if args.rate != 48000:
        print(f"Warning: Requested rate {args.rate} Hz may not work with USB mic. Forcing to 48000 Hz.")
        args.rate = 48000
    
    # List devices if requested
    if args.list_devices:
        print(list_audio_devices())
        return
    
    print("Kokoro AI Assistant - Audio Capture Client")
    print(f"Starting audio capture and transmission to {args.computer_ip}")
    print(f"Wake word detection port: {args.wake_port}")
    print(f"Speech recognition port: {args.stt_port}")
    print(f"Audio settings: {args.rate} Hz, {args.channels} channels, chunk size: {args.chunk_size}")
    print(f"Using device: {args.device}")
    
    if not args.quiet:
        # Only show device list in verbose mode
        print(list_audio_devices())
    
    # Convert device string to appropriate format
    device_index = None
    
    # If using "hw:" or "plughw:", convert to PyAudio device index if needed
    if isinstance(args.device, str) and (args.device.startswith('plughw:') or args.device.startswith('hw:')):
        # For ALSA hardware device strings, extract card number
        try:
            device_parts = args.device.split(':')[1].split(',')
            device_index = int(device_parts[0])
            print(f"Using card number {device_index} from {args.device}")
        except (IndexError, ValueError):
            print(f"Could not parse device string '{args.device}', using as is")
            device_index = None
    else:
        # For numeric device ID
        try:
            device_index = int(args.device)
            print(f"Using numeric device index: {device_index}")
        except ValueError:
            print(f"Could not parse device '{args.device}' as number, using as is")
            device_index = None

    # Initialize PyAudio
    try:
        p = pyaudio.PyAudio()

        # Check device info when using index
        if device_index is not None:
            try:
                device_info = p.get_device_info_by_index(device_index)
                print(f"Selected device: {device_info['name']}")
                print(f"  Max input channels: {device_info['maxInputChannels']}")
                print(f"  Default sample rate: {device_info['defaultSampleRate']} Hz")
                
                # Force the rate to match the device's native rate if different
                native_rate = int(device_info['defaultSampleRate'])
                if args.rate != native_rate:
                    print(f"Warning: Requested rate {args.rate} Hz differs from device native rate {native_rate} Hz")
                    args.rate = native_rate
                    print(f"Using device's native rate: {native_rate} Hz")
            except Exception as e:
                print(f"Error checking device: {e}")

        # Open audio stream
        print(f"Opening audio device {device_index} with rate {args.rate} Hz")
        
        # Suppress warnings during stream opening
        if args.quiet:
            warnings.filterwarnings("ignore")
            old_stderr_tmp = os.dup(2)
            os.dup2(devnull.fileno() if 'devnull' in locals() else os.open(os.devnull, os.O_WRONLY), 2)
        
        # Try to open the stream
        stream = p.open(
            format=FORMAT,
            channels=args.channels,
            rate=args.rate,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=args.chunk_size
        )
        
        # Restore stderr after stream opening
        if args.quiet and 'old_stderr_tmp' in locals():
            os.dup2(old_stderr_tmp, 2)
            os.close(old_stderr_tmp)
        
        print("Audio stream opened successfully")

    except Exception as e:
        print(f"Error opening audio stream: {e}")
        if 'p' in locals():
            p.terminate()
        # Restore stderr if we're in quiet mode
        if args.quiet:
            sys.stderr = old_stderr
        
        # Suggest solutions
        print("\nSuggested solutions:")
        print("1. Try using the plughw device: --device plughw:2,0")
        print("2. Create an .asoundrc file: --create-asoundrc")
        print("3. Try with the exact device name from the device list")
        return

    # Initialize UDP sockets
    wake_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    stt_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    print("Capturing and sending audio. Press Ctrl+C to stop.")
    
    try:
        packets_sent = 0
        start_time = time.time()
        last_report = start_time
        
        while True:
            # Read audio data from mic with robust error handling
            try:
                audio_data = stream.read(args.chunk_size, exception_on_overflow=False)
                
                # Basic sanity check on audio data
                if len(audio_data) == 0:
                    if not args.quiet:
                        print("Warning: Empty audio data received")
                    continue
                
                # Send the same audio to both ports
                wake_sock.sendto(audio_data, (args.computer_ip, args.wake_port))
                stt_sock.sendto(audio_data, (args.computer_ip, args.stt_port))
                
                packets_sent += 1
                
                # Report stats every 10 seconds (unless quiet mode)
                if not args.quiet:
                    now = time.time()
                    if now - last_report > 10:
                        elapsed = now - start_time
                        rate = packets_sent / elapsed if elapsed > 0 else 0
                        print(f"Sent {packets_sent} packets ({rate:.1f} packets/sec)")
                        last_report = now
                
                # Small delay to avoid overwhelming the network
                time.sleep(0.001)
            except IOError as e:
                if not args.quiet:
                    print(f"Audio read error (continuing): {e}")
                continue
            
    except KeyboardInterrupt:
        print("Stopping...")
    except Exception as e:
        print(f"Unexpected error: {e}")
    finally:
        # Cleanup
        print("Closing audio stream and sockets...")
        if 'stream' in locals() and stream:
            stream.stop_stream()
            stream.close()
        if 'p' in locals() and p:
            p.terminate()
        wake_sock.close()
        stt_sock.close()
        # Restore stderr if we're in quiet mode
        if args.quiet:
            sys.stderr = old_stderr
        print("Done!")

if __name__ == "__main__":
    main()
