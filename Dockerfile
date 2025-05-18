# 1. Base Image
FROM python:3.9-slim

# 5. Environment Variables (non-sensitive defaults)
ENV PYTHONUNBUFFERED=1
# Set a default path for the Porcupine keyword file within the container.
# This will be used by kokoro_config.py if KOKORO_CUSTOM_KEYWORD_PATH is not overridden at runtime.
ENV KOKORO_CUSTOM_KEYWORD_PATH=/app/porcupine_files/hey-koki_en_linux_v3_0_0.ppn

# 2. Working Directory
WORKDIR /app

# 3. Copy Requirements and Install Dependencies
COPY requirements.txt .

# Install system dependencies that pvporcupine or other packages might need (e.g., C build tools)
# python:3.9-slim is minimal, so build-essential is a good general inclusion.
# If specific .so files for audio (like libasound) are missing at runtime for pvporcupine,
# they would need to be added here (e.g., apt-get install -y libasound2).
# However, pvporcupine Python wheels are often self-contained for common architectures.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies from requirements.txt.
# google-cloud-pubsub is added here as it's required by wake_detector.py for cloud integration
# and might not be in the base requirements.txt yet.
RUN pip install --no-cache-dir -r requirements.txt google-cloud-pubsub

# 4. Copy Application Code
COPY wake_detector.py .
COPY kokoro_config.py .
COPY audio_stream_pb2.py .
COPY audio_stream_pb2_grpc.py .

# Copy the Porcupine keyword file.
# IMPORTANT: Before building, ensure the keyword file (e.g., 'hey-koki_en_windows_v3_0_0.ppn')
# is placed in a directory named 'porcupine_files' at the root of your project
# (e.g., 'c:/Users/justi/PycharmProjects/Kokoro/porcupine_files/hey-koki_en_windows_v3_0_0.ppn').
COPY porcupine_files/hey-koki_en_linux_v3_0_0.ppn /app/porcupine_files/hey-koki_en_linux_v3_0_0.ppn

# 6. Command
CMD ["python", "wake_detector.py"]