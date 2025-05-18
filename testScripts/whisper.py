import time
import numpy as np
from faster_whisper import WhisperModel
import logging
import sys
import traceback
import torch

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("whisper_test.log"),
        logging.StreamHandler(sys.stdout)
    ],
    force=True
)
for handler in logging.getLogger().handlers:
    handler.flush = lambda: sys.stdout.flush() if handler.stream == sys.stdout else None

def generate_test_audio(duration=5, sample_rate=16000, noise=True):
    """Generate a test audio buffer (silence or noise)."""
    samples = int(duration * sample_rate)
    if noise:
        # Generate random noise to simulate speech-like audio
        audio = np.random.uniform(-0.05, 0.05, samples).astype(np.float32)
    else:
        audio = np.zeros(samples, dtype=np.float32)
    logging.info(f"Generated {duration}s test audio - Samples: {samples}, Type: {'noise' if noise else 'silence'}")
    return audio

def test_whisper(device="cpu", audio=None, model_size="tiny"):
    """Test Whisper transcription speed and stability on the specified device."""
    logging.info(f"\n=== Testing Whisper on {device.upper()} ===")
    timings = {"model_load": 0.0, "transcription": 0.0}
    
    start_time = time.time()
    try:
        whisper_model = WhisperModel(model_size, device=device, compute_type="float32")
        timings["model_load"] = time.time() - start_time
        logging.info(f"Model '{model_size}' loaded on {device} in {timings['model_load']:.3f}s")
    except Exception as e:
        logging.error(f"Failed to load model on {device}: {str(e)}")
        logging.error(traceback.format_exc())
        return None
    
    if device == "cuda" and torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
        logging.info(f"Pre-transcription GPU Memory - Allocated: {torch.cuda.memory_allocated(0)/1024**3:.3f} GB, Reserved: {torch.cuda.memory_reserved(0)/1024**3:.3f} GB")
    
    start_time = time.time()
    try:
        segments, info = whisper_model.transcribe(
            audio,
            language="en",
            beam_size=1,
            best_of=1,
            vad_filter=False  # Disable voice activity detection to force full processing
        )
        timings["transcription"] = time.time() - start_time
        text = " ".join([s.text for s in segments]).strip()
        logging.info(f"Transcription completed in {timings['transcription']:.3f}s")
        logging.info(f"Result: {text if text else '(No speech detected)'}")
    except Exception as e:
        logging.error(f"Transcription failed on {device}: {str(e)}")
        logging.error(traceback.format_exc())
        if device == "cuda" and torch.cuda.is_available():
            cuda_err = torch.cuda.get_last_error()
            if cuda_err:
                logging.error(f"CUDA Error: {cuda_err}")
        timings["transcription"] = time.time() - start_time
        return None
    
    if device == "cuda" and torch.cuda.is_available():
        torch.cuda.synchronize()
        logging.info(f"Post-transcription GPU Memory - Allocated: {torch.cuda.memory_allocated(0)/1024**3:.3f} GB, Reserved: {torch.cuda.memory_reserved(0)/1024**3:.3f} GB")
    
    total_time = timings["model_load"] + timings["transcription"]
    logging.info(f"Total time on {device}: {total_time:.3f}s (Load: {timings['model_load']:.3f}s, Transcribe: {timings['transcription']:.3f}s)")
    return timings

def main():
    # Test with noise to simulate speech-like audio
    test_audio = generate_test_audio(duration=5, sample_rate=16000, noise=True)
    cpu_timings = test_whisper(device="cpu", audio=test_audio, model_size="tiny")
    if torch.cuda.is_available():
        gpu_timings = test_whisper(device="cuda", audio=test_audio, model_size="tiny")
    else:
        logging.info("CUDA not available, skipping GPU test")

if __name__ == "__main__":
    logging.info("Starting Whisper performance test...")
    main()
    logging.info("Test completed")