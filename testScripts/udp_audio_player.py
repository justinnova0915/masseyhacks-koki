import socket
import pyaudio
import argparse
import numpy as np
import wave
import os
import time
from datetime import datetime
import struct
from collections import deque

def main():
    parser = argparse.ArgumentParser(description="Play audio received via UDP")
    parser.add_argument("--port", type=int, default=12347, help="UDP port to listen on")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host address to bind to")
    parser.add_argument("--channels", type=int, default=1, help="Audio channels (1=mono, 2=stereo)")
    parser.add_argument("--rate", type=int, default=48000, help="Sample rate (samples per second)")
    parser.add_argument("--format", type=str, default="int16", help="Audio format (int16, int32, float32)")
    parser.add_argument("--buffer", type=float, default=0.2, help="Buffer size in seconds")
    parser.add_argument("--record", action="store_true", help="Record audio to a WAV file")
    args = parser.parse_args()
    
    # Set up format
    format_map = {
        "int16": pyaudio.paInt16,
        "int32": pyaudio.paInt32,
        "float32": pyaudio.paFloat32,
    }
    audio_format = format_map.get(args.format, pyaudio.paInt16)
    sample_width = 2 if args.format == "int16" else 4  # bytes per sample
    
    # Create UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))
    sock.settimeout(0.1)  # 100ms timeout
    
    print(f"UDP audio player listening on {args.host}:{args.port}")
    print(f"Audio settings: {args.rate}Hz, {args.channels} channels, {args.format} format")
    
    # Initialize PyAudio
    p = pyaudio.PyAudio()
    
    # Calculate buffer parameters
    buffer_size_samples = int(args.rate * args.buffer)
    chunk_size = 1024  # Processing chunks
    
    # Create a circular buffer for audio data
    buffer = deque(maxlen=buffer_size_samples)
    
    # File for recording if enabled
    wav_file = None
    if args.record:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"udp_audio_{timestamp}.wav"
        wav_file = wave.open(filename, 'wb')
        wav_file.setnchannels(args.channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(args.rate)
        print(f"Recording to {filename}")
    
    # Open audio stream for playback
    stream = p.open(
        format=audio_format,
        channels=args.channels,
        rate=args.rate,
        output=True,
        frames_per_buffer=chunk_size
    )
    
    print("Starting playback. Press Ctrl+C to stop.")
    
    # Statistics tracking
    stats_start_time = time.time()
    packets_received = 0
    bytes_received = 0
    samples_played = 0
    buffer_status = "Initializing"
    
    try:
        # Initial buffer filling
        print("Buffering audio...")
        buffer_target = buffer_size_samples // 2  # Fill half the buffer before starting
        
        while len(buffer) < buffer_target:
            try:
                data, addr = sock.recvfrom(4096)
                packets_received += 1
                bytes_received += len(data)
                
                # Unpack audio samples and add to buffer
                if args.format == "int16":
                    fmt = f"{len(data)//2}h"
                elif args.format == "int32":
                    fmt = f"{len(data)//4}i"
                elif args.format == "float32":
                    fmt = f"{len(data)//4}f"
                
                samples = struct.unpack(fmt, data)
                buffer.extend(samples)
                
                # Save to WAV if recording
                if wav_file:
                    wav_file.writeframes(data)
                
            except socket.timeout:
                continue  # Keep waiting for data
        
        print(f"Buffer filled with {len(buffer)} samples. Starting playback...")
        buffer_status = "Playing"
        
        # Main loop - receive and play audio
        while True:
            # Try to receive a packet
            try:
                data, addr = sock.recvfrom(4096)
                packets_received += 1
                bytes_received += len(data)
                
                # Unpack audio samples and add to buffer
                if args.format == "int16":
                    fmt = f"{len(data)//2}h"
                elif args.format == "int32":
                    fmt = f"{len(data)//4}i"
                elif args.format == "float32":
                    fmt = f"{len(data)//4}f"
                
                samples = struct.unpack(fmt, data)
                buffer.extend(samples)
                
                # Save to WAV if recording
                if wav_file:
                    wav_file.writeframes(data)
                
            except socket.timeout:
                pass  # No data received, continue

            # Play audio if we have enough in the buffer
            if len(buffer) >= chunk_size:
                # Extract chunk from buffer
                chunk = list(buffer)[:chunk_size]
                for _ in range(chunk_size):
                    if buffer:
                        buffer.popleft()
                
                # Convert back to bytes
                if args.format == "int16":
                    output_data = struct.pack(f"{chunk_size}h", *chunk)
                elif args.format == "int32":
                    output_data = struct.pack(f"{chunk_size}i", *chunk)
                elif args.format == "float32":
                    output_data = struct.pack(f"{chunk_size}f", *chunk)
                
                # Play the audio
                stream.write(output_data)
                samples_played += chunk_size
            
            # Show statistics every second
            if time.time() - stats_start_time >= 1.0:
                elapsed = time.time() - stats_start_time
                buffer_percent = len(buffer) * 100 / buffer.maxlen
                
                print(f"\rBuffer: {buffer_percent:.1f}% | "
                      f"Packets: {packets_received} | "
                      f"Data rate: {bytes_received/elapsed/1024:.1f} KB/s | "
                      f"Played: {samples_played/elapsed:.1f} samples/s | "
                      f"Status: {buffer_status}", end="")
                
                stats_start_time = time.time()
                packets_received = 0
                bytes_received = 0
                samples_played = 0
                
                # Update buffer status
                if buffer_percent < 25:
                    buffer_status = "Buffering low"
                elif buffer_percent > 90:
                    buffer_status = "Buffering high"
                else:
                    buffer_status = "Stable"
    
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        print("\nCleaning up...")
        
        # Close stream and PyAudio
        stream.stop_stream()
        stream.close()
        p.terminate()
        
        # Close socket
        sock.close()
        
        # Close WAV file if recording
        if wav_file:
            wav_file.close()
            print(f"Audio saved to {filename}")

if __name__ == "__main__":
    main()
