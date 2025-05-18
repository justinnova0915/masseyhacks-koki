import ollama
import logging
import sys
import time
import re
from colorama import init, Fore, Style
from RealtimeSTT import AudioToTextRecorder
from RealtimeTTS import TextToAudioStream, KokoroEngine

# Initialize colorama for colored output
init()

# Configure logging with colored output
class ColoredFormatter(logging.Formatter):
    COLORS = {
        'INFO': Fore.WHITE,
        'DEBUG': Fore.CYAN,
        'WARNING': Fore.YELLOW,
        'ERROR': Fore.RED,
        'CRITICAL': Fore.RED + Style.BRIGHT
    }

    def format(self, record):
        levelname = record.levelname
        msg = super().format(record)
        return f"{self.COLORS.get(levelname, Fore.WHITE)}{msg}{Style.RESET_ALL}"

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("agent_debug.log"),
        logging.StreamHandler(sys.stdout)
    ]
)

# Apply colored formatter to console handler
for handler in logging.getLogger().handlers:
    if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
        handler.setFormatter(ColoredFormatter('%(asctime)s - %(levelname)s - %(message)s'))

class RealTimeAIAgent:
    def __init__(self):
        # Initialize RealtimeSTT
        logging.info("Initializing RealtimeSTT...")
        self.recorder = AudioToTextRecorder(
            model="medium",  # Use a smaller model for faster transcription
            language="en",
            compute_type="float32",
            device="cuda",
            spinner=True
        )

        # Initialize RealtimeTTS with KokoroEngine
        logging.info("Initializing RealtimeTTS...")
        self.tts_engine = KokoroEngine()
        self.tts_engine.set_voice('af_heart')  # Set the voice to American English (af_heart)
        self.tts = TextToAudioStream(
            engine=self.tts_engine
        )

        # Pre-warm the KokoroEngine to reduce initial TTS latency
        logging.debug("Pre-warming KokoroEngine...")
        self.tts.feed("Warm up").play(muted=True)
        logging.debug("KokoroEngine pre-warmed")

        # Initialize Ollama client
        logging.info("Connecting to Ollama...")
        # Test connection by sending a small request
        response = ollama.chat(
            model="llama3.1:8b",
            messages=[{"role": "user", "content": "test"}],
            options={"num_predict": 50}
        )
        if not response.get('message', {}).get('content'):
            raise Exception("Failed to connect to Ollama")
        logging.info("Successfully connected to Ollama")

    def process_text(self, text):
        """Callback to process transcribed text"""
        # STT step (already completed by the time this callback is called)
        logging.info(f"{Fore.GREEN}STT Finished: Transcribed text: {text}{Style.RESET_ALL}")
        print(f"🎤 You: {text}")

        # LLaMA step (text generation with Ollama, streamed)
        logging.info(f"{Fore.BLUE}LLaMA Started: Generating response...{Style.RESET_ALL}")
        llama_start = time.time()
        stream = ollama.chat(
            model="llama3.1:8b",
            messages=[{"role": "user", "content": text}],
            stream=True,
            options={"num_predict": 50}  # Reduced response length for faster generation
        )

        # Stream the response and feed to TTS incrementally
        response_text = ""
        chunk = ""
        word_count = 0
        first_chunk_played = False
        first_chunk_time = None

        for part in stream:
            token = part.get('message', {}).get('content', '')
            response_text += token
            chunk += token
            word_count += len(token.split())

            # Check for a sentence break or sufficient words (5-10 words)
            if re.search(r'[.!?]', chunk) or word_count >= 5:
                if chunk.strip():
                    logging.debug(f"Feeding chunk to TTS: {chunk}")
                    self.tts.feed(chunk)
                    if not first_chunk_played:
                        logging.info(f"{Fore.MAGENTA}TTS Started: Playing first chunk...{Style.RESET_ALL}")
                        self.tts.play_async()  # Start playback asynchronously
                        first_chunk_time = time.time() - llama_start
                        logging.info(f"{Fore.MAGENTA}TTS First Chunk Played: Time to first speech: {first_chunk_time:.2f}s{Style.RESET_ALL}")
                        first_chunk_played = True
                    chunk = ""  # Reset chunk for the next segment
                    word_count = 0

        # Feed any remaining text
        if chunk.strip():
            logging.debug(f"Feeding final chunk to TTS: {chunk}")
            self.tts.feed(chunk)

        # Wait for TTS playback to finish
        self.tts.stop()  # Ensure playback is complete
        llama_duration = time.time() - llama_start
        logging.info(f"{Fore.BLUE}LLaMA Finished: Generated full response: {response_text} (Total Duration: {llama_duration:.2f}s){Style.RESET_ALL}")
        print(f"💬 AI: {response_text}")

    def run(self):
        print("Wait until it says 'speak now'")
        logging.info("Starting speech recognition...")
        print("🎤 Speak now...")
        while True:
            self.recorder.text(self.process_text)

if __name__ == "__main__":
    agent = RealTimeAIAgent()
    agent.run()