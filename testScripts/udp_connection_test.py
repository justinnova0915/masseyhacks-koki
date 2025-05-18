import socket
import time
import struct
import numpy as np
import matplotlib.pyplot as plt
import argparse
import os
from datetime import datetime

def main():
    parser = argparse.ArgumentParser(description="Test UDP connection from Raspberry Pi")
    parser.add_argument("--port", type=int, default=12347, help="UDP port to listen on")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host address to bind to")
    parser.add_argument("--chunk-size", type=int, default=512, help="Expected audio chunk size")
    parser.add_argument("--save-audio", action="store_true", help="Save received audio to a file")
    parser.add_argument("--visualize", action="store_true", help="Visualize audio in real-time")
    args = parser.parse_args()
    
    # Create UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))
    sock.settimeout(0.1)  # 100ms timeout for non-blocking
    
    print(f"UDP server listening on {args.host}:{args.port}")
    print("Waiting for data from Raspberry Pi...")
    
    # Stats tracking
    start_time = time.time()
    packets_received = 0
    bytes_received = 0
    last_stats_time = start_time
    last_sender = None
    
    # For visualization
    if args.visualize:
        try:
            import matplotlib.pyplot as plt
            from matplotlib.animation import FuncAnimation
            
            plt.ion()  # Enable interactive mode
            fig, ax = plt.subplots(figsize=(10, 4))
            line, = ax.plot([], [], lw=2)
            ax.set_ylim(-32768, 32768)
            ax.set_xlim(0, args.chunk_size)
            ax.set_title("Audio Waveform")
            ax.set_xlabel("Sample")
            ax.set_ylabel("Amplitude")
            plt.grid(True)
            fig.canvas.draw()
            plt.pause(0.001)
            
            audio_buffer = np.zeros(args.chunk_size)
        except ImportError:
            print("Matplotlib not available. Disabling visualization.")
            args.visualize = False
            
    # For saving audio
    audio_file = None
    if args.save_audio:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"udp_audio_{timestamp}.raw"
        audio_file = open(filename, "wb")
        print(f"Saving audio to {filename}")
    
    try:
        while True:
            try:
                # Receive data
                data, addr = sock.recvfrom(4096)
                
                # Update stats
                now = time.time()
                packets_received += 1
                bytes_received += len(data)
                
                # Save first sender
                if last_sender is None:
                    last_sender = addr
                    print(f"First packet received from {addr}")
                
                # Print stats every second
                if now - last_stats_time >= 1.0:
                    elapsed = now - start_time
                    avg_packet_rate = packets_received / elapsed
                    avg_data_rate = bytes_received / elapsed / 1024  # KB/s
                    
                    print(f"Connection active: {elapsed:.1f} seconds")
                    print(f"Sender: {addr}")
                    print(f"Packets: {packets_received} ({avg_packet_rate:.1f} packets/s)")
                    print(f"Data: {bytes_received/1024:.1f} KB ({avg_data_rate:.1f} KB/s)")
                    
                    if last_sender != addr:
                        print(f"Warning: Sender changed from {last_sender} to {addr}")
                        last_sender = addr
                    
                    last_stats_time = now
                    print("-" * 40)
                
                # Save audio if requested
                if args.save_audio and audio_file:
                    audio_file.write(data)
                
                # Visualize audio if requested
                if args.visualize:
                    try:
                        # Convert bytes to samples
                        format_str = f"{len(data)//2}h"  # 16-bit samples
                        samples = np.array(struct.unpack(format_str, data))
                        
                        # Update the plot
                        line.set_data(range(len(samples)), samples)
                        if len(samples) > 0:
                            ax.set_xlim(0, len(samples))
                        fig.canvas.draw_idle()
                        plt.pause(0.001)
                    except Exception as e:
                        print(f"Visualization error: {e}")
                
            except socket.timeout:
                # No data received, just continue
                continue
            except KeyboardInterrupt:
                print("\nExiting...")
                break
    
    finally:
        print("\nShutting down...")
        sock.close()
        
        if args.save_audio and audio_file:
            audio_file.close()
            print(f"Audio saved to {filename}")
        
        # Print final stats
        elapsed = time.time() - start_time
        if elapsed > 0 and packets_received > 0:
            print(f"\nSummary:")
            print(f"Total time: {elapsed:.1f} seconds")
            print(f"Total packets: {packets_received}")
            print(f"Average packet rate: {packets_received/elapsed:.1f} packets/s")
            print(f"Total data: {bytes_received/1024:.1f} KB")
            print(f"Average data rate: {bytes_received/elapsed/1024:.1f} KB/s")

if __name__ == "__main__":
    main()
