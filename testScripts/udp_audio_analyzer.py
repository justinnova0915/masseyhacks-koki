import socket
import numpy as np
import time
import argparse
import struct
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

def main():
    parser = argparse.ArgumentParser(description="Analyze UDP audio stream")
    parser.add_argument("--port", type=int, default=12347, help="UDP port to listen on")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--chunk-size", type=int, default=512, help="Expected chunk size")
    parser.add_argument("--format", type=str, default="int16", help="Audio format (int16, int32, float32)")
    parser.add_argument("--channels", type=int, default=1, help="Number of audio channels")
    parser.add_argument("--visualize", action="store_true", help="Show visualization")
    args = parser.parse_args()
    
    # Set up socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))
    sock.settimeout(0.1)
    
    print(f"UDP Audio Analyzer listening on {args.host}:{args.port}")
    print(f"Settings: format={args.format}, channels={args.channels}, chunk_size={args.chunk_size}")
    
    # Stats tracking
    packets_received = 0
    bytes_received = 0
    start_time = time.time()
    last_stats_time = start_time
    audio_buffer = bytearray()
    
    # Set up visualization if requested
    if args.visualize:
        plt.ion()
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))
        
        # Waveform plot
        x_wave = np.arange(args.chunk_size)
        line_wave, = ax1.plot(x_wave, np.zeros(args.chunk_size))
        ax1.set_ylim(-1, 1)
        ax1.set_xlim(0, args.chunk_size)
        ax1.set_title('Audio Waveform')
        ax1.set_ylabel('Amplitude')
        ax1.grid(True)
        
        # RMS history plot
        rms_history = []
        peak_history = []
        history_len = 100
        x_hist = np.arange(history_len)
        line_rms, = ax2.plot(x_hist, np.zeros(history_len), 'b-', label='RMS')
        line_peak, = ax2.plot(x_hist, np.zeros(history_len), 'r-', label='Peak')
        ax2.set_ylim(0, 0.5)
        ax2.set_xlim(0, history_len)
        ax2.set_title('Audio Level History')
        ax2.set_xlabel('Time')
        ax2.set_ylabel('Level')
        ax2.legend()
        ax2.grid(True)
        
        plt.tight_layout()
        fig.canvas.draw()
    
    try:
        # Processing loop
        while True:
            try:
                # Receive UDP data
                data, addr = sock.recvfrom(8192)
                packets_received += 1
                bytes_received += len(data)
                audio_buffer.extend(data)
                
                # Process audio in chunks
                bytes_per_sample = 2 if args.format == "int16" else 4  # Bytes per sample
                frame_size = bytes_per_sample * args.channels
                required_bytes = args.chunk_size * frame_size
                
                while len(audio_buffer) >= required_bytes:
                    # Extract chunk
                    chunk = audio_buffer[:required_bytes]
                    audio_buffer = audio_buffer[required_bytes:]
                    
                    # Convert to samples
                    if args.format == "int16":
                        samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
                    elif args.format == "int32":
                        samples = np.frombuffer(chunk, dtype=np.int32).astype(np.float32) / 2147483648.0
                    elif args.format == "float32":
                        samples = np.frombuffer(chunk, dtype=np.float32)
                    
                    # If stereo, average channels
                    if args.channels == 2:
                        samples = samples.reshape(-1, 2).mean(axis=1)
                    
                    # Calculate audio metrics
                    rms = np.sqrt(np.mean(samples**2)) if len(samples) > 0 else 0
                    peak = np.max(np.abs(samples)) if len(samples) > 0 else 0
                    zero_crossings = np.sum(np.diff(np.signbit(samples).astype(int))) if len(samples) > 1 else 0
                    
                    # Update visualization
                    if args.visualize:
                        # Update waveform
                        display_samples = samples[:args.chunk_size] if len(samples) >= args.chunk_size else np.pad(samples, (0, args.chunk_size - len(samples)))
                        line_wave.set_ydata(display_samples)
                        
                        # Update RMS/peak history
                        rms_history.append(rms)
                        peak_history.append(peak)
                        if len(rms_history) > history_len:
                            rms_history.pop(0)
                        if len(peak_history) > history_len:
                            peak_history.pop(0)
                        
                        line_rms.set_ydata(rms_history + [0] * (history_len - len(rms_history)))
                        line_peak.set_ydata(peak_history + [0] * (history_len - len(peak_history)))
                        
                        # Adjust y-axis scaling if needed
                        max_level = max(max(peak_history) if peak_history else 0.1, 0.1)
                        ax2.set_ylim(0, max_level * 1.1)
                        
                        fig.canvas.draw_idle()
                        plt.pause(0.01)
                
                # Print stats periodically
                current_time = time.time()
                if current_time - last_stats_time >= 1.0:
                    elapsed = current_time - last_stats_time
                    print(f"\rPackets: {packets_received}, Bytes: {bytes_received}, " 
                          f"Rate: {bytes_received/elapsed:.1f} B/s, "
                          f"RMS: {rms:.4f}, Peak: {peak:.4f}, "
                          f"Zero-crossings: {zero_crossings}", end="")
                    packets_received = 0
                    bytes_received = 0
                    last_stats_time = current_time
                    
            except socket.timeout:
                continue
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"\nError: {e}")
                break
    
    finally:
        sock.close()
        if args.visualize:
            plt.close()
        
        print("\nAnalysis complete.")

if __name__ == "__main__":
    main()
