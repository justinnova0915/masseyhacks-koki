import pvporcupine
import pyaudio
import struct
import numpy as np
import os
import wave
import time
import logging
import argparse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

def play_test_audio(filename, frame_length, sample_rate):
    """Play a test audio file through Porcupine to check detection"""
    logging.info(f"Testing wake word detection with file: {filename}")
    
    # Load the audio file
    with wave.open(filename, 'rb') as wf:
        audio_data = wf.readframes(wf.getnframes())
    
    # Convert to numpy array
    audio = np.frombuffer(audio_data, dtype=np.int16)
    
    # Process frames
    frames_processed = 0
    detections = 0
    
    # Create Porcupine instance
    access_key = "R9JpPtNjUCi3TM+sDhFDwHju2ukhq5mdhOse7YNQ/cLH+5g+TAQrSA=="
    keyword_path = r"C:\Users\justi\Downloads\hey-koki_en_windows_v3_0_0\hey-koki_en_windows_v3_0_0.ppn"
    
    # Try different sensitivities
    sensitivities = [0.5, 0.6, 0.7, 0.8, 0.9]
    
    for sensitivity in sensitivities:
        logging.info(f"Testing with sensitivity: {sensitivity}")
        
        try:
            porcupine = pvporcupine.create(
                access_key=access_key,
                keyword_paths=[keyword_path],
                sensitivities=[sensitivity]
            )
            
            # Process frames
            frames_processed = 0
            detections = 0
            
            # Process in chunks of frame_length
            for i in range(0, len(audio) - frame_length, frame_length):
                frame = audio[i:i+frame_length]
                if len(frame) != frame_length:
                    continue
                    
                result = porcupine.process(frame)
                frames_processed += 1
                
                if result >= 0:
                    detections += 1
                    logging.info(f"Detection at frame {frames_processed}, offset {i/sample_rate:.2f} seconds")
            
            logging.info(f"Sensitivity {sensitivity}: Processed {frames_processed} frames, detected {detections} instances")
            
        finally:
            if 'porcupine' in locals():
                porcupine.delete()

def record_test_audio(duration=5, filename="test_hey_koki.wav"):
    """Record a test audio file saying 'hey koki'"""
    logging.info(f"Recording {duration} seconds of audio to {filename}...")
    
    p = pyaudio.PyAudio()
    
    # Set up recording
    stream = p.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=16000,
        input=True,
        frames_per_buffer=1024
    )
    
    print(f"Say 'hey koki' clearly within the next {duration} seconds...")
    time.sleep(1)  # Give a moment to prepare
    
    # Record audio
    frames = []
    for i in range(0, int(16000 / 1024 * duration)):
        data = stream.read(1024)
        frames.append(data)
        if i % 10 == 0:
            print(f"Recording: {i/(16000/1024*duration)*100:.0f}% complete", end="\r")
    
    # Clean up
    stream.stop_stream()
    stream.close()
    p.terminate()
    
    # Save the recording
    wf = wave.open(filename, 'wb')
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(16000)
    wf.writeframes(b''.join(frames))
    wf.close()
    
    logging.info(f"Saved recording to {filename}")
    return filename

def check_porcupine_requirements():
    """Check the requirements for Porcupine"""
    try:
        porcupine = pvporcupine.create(
            access_key="R9JpPtNjUCi3TM+sDhFDwHju2ukhq5mdhOse7YNQ/cLH+5g+TAQrSA==",
            keywords=["porcupine"]  # Use built-in keyword for testing
        )
        
        logging.info(f"Porcupine initialized successfully")
        logging.info(f"Required sample rate: {porcupine.sample_rate} Hz")
        logging.info(f"Required frame length: {porcupine.frame_length} samples")
        
        porcupine.delete()
    except Exception as e:
        logging.error(f"Failed to initialize Porcupine: {e}")

def main():
    parser = argparse.ArgumentParser(description="Test wake word detection")
    parser.add_argument("--record", action="store_true", help="Record a test audio file")
    parser.add_argument("--test", action="store_true", help="Test wake word detection with a file")
    parser.add_argument("--file", type=str, default="test_hey_koki.wav", help="Audio file to test")
    parser.add_argument("--check", action="store_true", help="Check Porcupine requirements")
    args = parser.parse_args()
    
    if args.check:
        check_porcupine_requirements()
        return
        
    if args.record:
        filename = record_test_audio(5, args.file)
    else:
        filename = args.file
        
    if args.test:
        # Create temporary Porcupine instance to get parameters
        porcupine = pvporcupine.create(
            access_key="R9JpPtNjUCi3TM+sDhFDwHju2ukhq5mdhOse7YNQ/cLH+5g+TAQrSA==",
            keywords=["porcupine"]  # Use built-in keyword just to get params
        )
        frame_length = porcupine.frame_length
        sample_rate = porcupine.sample_rate
        porcupine.delete()
        
        play_test_audio(filename, frame_length, sample_rate)

if __name__ == "__main__":
    main()
