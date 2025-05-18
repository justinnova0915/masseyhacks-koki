# Koki: A More Natural Human-Computer Interface

## Inspiration

The digital world is increasingly integrated into our daily lives, yet our interactions with technology often feel clunky and unnatural. Koki was born from a desire to bridge this gap, to create a human-computer interface that feels more intuitive, responsive, and engaging. We wanted a system that moves beyond simple command-and-response, aiming for an interaction that leverages voice and visual cues for a richer experience.

## What it does

Koki is a voice-controlled assistant designed to provide a more natural and interactive experience. At its core, Koki listens for a wake word ("Hey Koki," using [`porcupine_files/hey-koki_en_windows_v3_0_0.ppn`](porcupine_files/hey-koki_en_windows_v3_0_0.ppn)) and then processes voice commands.

Key functionalities include:

* **Voice Control:** Users interact with Koki using natural language, managed by components such as [`real_time_ai_agent.py`](real_time_ai_agent.py) and audio processing scripts like [`raspiScripts/rpi_audio_client.py`](raspiScripts/rpi_audio_client.py).
* **Visual Feedback:** Koki provides visual feedback through an animated character or interface, utilizing [`blenderScripts/`](blenderScripts/) like [`blenderScripts/local_blender_bridge.py`](blenderScripts/local_blender_bridge.py) and [`blenderScripts/kokoro_monitor.py`](blenderScripts/kokoro_monitor.py) for connection to Blender for visual rendering.

Essentially, Koki is an attentive assistant that you can talk to, and it visually acknowledges and responds to you.

## How we built it

Koki is a multi-component system that combines local hardware for user interaction with a powerful cloud-based backend for AI processing and logic. AI tools also played a significant role in the development, refinement, and debugging of key software components throughout the project.

**1. User Interface (Client-Side):**

* **Hardware:** A Raspberry Pi serves as the primary interface. It handles:
  * **Audio Input:** Capturing the user's voice via a microphone, using scripts like [`raspiScripts/audio_capture.py`](raspiScripts/audio_capture.py).
  * **Wake Word Detection:** Locally running Picovoice Porcupine to listen for "Hey Koki."
  * **Audio Output:** Playing back Koki's responses.
  * **Visual Output:** The Raspberry Pi drives a display for visual feedback or connects to the Blender instance.
* **Software (Client-Side):** Python scripts on the Raspberry Pi manage hardware interaction, wake word detection, and communication with the backend. Key scripts like [`raspiScripts/rpi_audio_client.py`](raspiScripts/rpi_audio_client.py:1) were refined with AI assistance. Libraries like [`numpy`](requirements.txt:8) are used for processing data from the camera.

**2. Backend Logic (Server-Side):**

* **Infrastructure:** The core logic runs on custom Python microservices, including components like [`real_time_ai_agent.py`](real_time_ai_agent.py:1) (which benefited from AI-assisted development and debugging), deployed as a cluster in Kubernetes. This is detailed in files like [`ai-agent-deployment.yaml`](ai-agent-deployment.yaml) and [`Dockerfile.ai_agent`](Dockerfile.ai_agent).
* **Communication:**
  * Services communicate using a combination of REST APIs (built with [`fastapi`](requirements.txt:2) and [`uvicorn`](requirements.txt:16)) and gRPC (using [`grpcio`](requirements.txt:17) and [`grpcio-tools`](requirements.txt:18), defined in [`audio_stream.proto`](audio_stream.proto)).
  * Google Cloud Pub/Sub ([`google-cloud-pubsub`](requirements.txt:4)) is used for asynchronous messaging between services.
* **AI Processing (Google Cloud):**
  * **Speech-to-Text (STT):** Google Cloud Speech-to-Text ([`google-cloud-speech`](requirements.txt:5)) converts the user's spoken audio (streamed from the Raspberry Pi) into text.
  * **Natural Language Processing (NLP) / Core AI:** Google Cloud Vertex AI ([`google-cloud-aiplatform`](requirements.txt:3)) is leveraged for the main AI logic, understanding the user's intent and formulating responses.
  * **Text-to-Speech (TTS):** Google Cloud Text-to-Speech ([`google-cloud-texttospeech`](requirements.txt:6)) converts the AI's text response back into natural-sounding speech.
* **Data Storage:** Google Cloud Storage ([`google-cloud-storage`](requirements.txt:7)) is used for storing audio files, logs, or other necessary data.

**3. Visual Rendering:**

* **Software:** Blender is used for rendering Koki's visual representation.
* **Control:** Python scripts within the [`blenderScripts/`](blenderScripts/) directory (e.g., [`blenderScripts/local_blender_bridge.py`](blenderScripts/local_blender_bridge.py), [`blenderScripts/kokoro_monitor.py`](blenderScripts/kokoro_monitor.py)) control Blender's actions, receiving commands from the backend to animate Koki based on the conversation or detected user presence. This runs on a separate computer (laptop).

**Key Python Libraries:**

Beyond the Google Cloud client libraries and API/communication tools, other important libraries from [`requirements.txt`](requirements.txt:1) include:

* [`soundfile`](requirements.txt:15), [`resampy`](requirements.txt:13), [`scipy`](requirements.txt:14): For audio processing tasks.
* [`python-dotenv`](requirements.txt:9): For managing environment variables and configuration.

## Workflow Overview:

1. User says "Hey Koki."
2. Raspberry Pi detects the wake word and starts streaming audio to the backend.
3. Backend service ([`stream_handler_service.py`](stream_handler_service.py)) receives the audio.
4. Audio is sent to Google STT.
5. Text transcript is sent to Vertex AI via Pub/Sub.
6. Vertex AI processes the text and generates a response.
7. The text response is sent to Google TTS.
8. The synthesized audio is streamed back to the Raspberry Pi for playback.
9. Simultaneously, commands are sent to the Blender instance to update Koki's visual expression or actions.
10. The Raspberry Pi's face detection feeds information to the backend to influence Koki's behavior (e.g., turning to face the user).

## Challenges we ran into

Developing Koki was a significant undertaking, and nearly every aspect presented its own set of hurdles:

* **Fundamental Code Logic:** Establishing the foundational software architecture and core logic for a multi-component system like Koki was an initial complex task. Making sure everything could connect and play nice together meant a lot of careful steps and going back to the drawing board.
* **Cloud Migration and Integration:** Transitioning to and integrating with Google Cloud services (Pub/Sub, STT, Vertex AI, TTS) was a major step. This involved understanding each service's API, managing authentication (e.g., `rpi-audio-client-key.json`, `kokoro-blender-bridge-key.json`), configuring services correctly, and orchestrating the data flow between them and the local Raspberry Pi client. Deploying and managing the Kubernetes cluster also added a layer of complexity.
* **CAD and Hardware Implementation:** Bringing Koki to life physically – designing in Fusion 360, 3D printing the pieces was a real learning curve. Figuring out CAD and getting the physical designs just right took some serious trial and error.
* **Latency Optimization:** Getting Koki to respond quickly, like a natural conversation, was particularly hard. We spent a lot of time trying to shave off delays in how it heard, sent info to the cloud (for understanding and generating speech), and then spoke back. Tweaking the code, how it talked to the network, and even picking the right cloud spots helped a ton, but Koki still has the occasional slight pause. It's way better than it used to be, though!
* **Blender Integration:** Connecting the backend logic to Blender for real-time visual feedback ([`blenderScripts/local_blender_bridge.py`](blenderScripts/local_blender_bridge.py), [`blenderScripts/kokoro_monitor.py`](blenderScripts/kokoro_monitor.py)) presented its own integration challenges. Ensuring that Blender animations responded promptly to conversational cues required robust communication and control mechanisms.

## Accomplishments that we're proud of

Despite the numerous challenges, developing Koki has led to several key accomplishments:

* **Successful End-to-End System Integration:** Perhaps the most significant achievement is the successful integration of all disparate components – the Raspberry Pi client, the Kubernetes-hosted backend, various Google Cloud AI services, and the Blender visual interface – into a cohesive, functioning system. Orchestrating this complex pipeline from voice input on the Pi, through cloud-based AI processing, and back to audio-visual output represents a major engineering feat.
* **Real-time Voice Interaction with Visual Feedback:** We successfully created a system where users can interact with Koki using natural voice commands, and Koki responds not just with audio but also with synchronized visual feedback through Blender. Achieving this real-time, multi-modal interaction brings the vision of a more natural human-computer interface to life.
* **Functioning Proof-of-Concept:** Koki is a working proof-of-concept for a more natural and engaging human-computer interface. It demonstrates the potential of combining local hardware, cloud AI, and rich visual rendering to create more intuitive and responsive digital assistants.
* **Mastering Diverse Technologies:** The project necessitated learning and applying a wide array of technologies, from embedded systems programming on the Raspberry Pi and hardware interfacing (like with the face-tracking motors) to deploying scalable microservices on Kubernetes and leveraging sophisticated cloud AI platforms. Gaining proficiency across these fields is a substantial accomplishment in itself.

## What we learned

The path of building Koki was a significant learning experience, providing deep insights into several key areas:

* **Cloud Service Integration and Microservices:** A major takeaway was the complexity and power of integrating various cloud services. We learned firsthand how to architect and manage a microservices-based backend using Kubernetes, orchestrating Google Cloud services like Pub/Sub for messaging, STT/TTS for voice processing, and Vertex AI for core intelligence. This involved understanding API intricacies, authentication, and data flow management in a distributed environment.
* **Real-time Audio Processing and Latency Management:** The project encountered the critical challenges of real-time audio processing. We gained practical experience in capturing, streaming, and processing audio with minimal delay, learning techniques to mitigate latency across the entire pipeline – from the Raspberry Pi, through the cloud services, and back.
* **Hardware, CAD, and 3D Printing:** Koki provided invaluable experience in hardware integration. This included interfacing with sensors and motors on the Raspberry Pi ([`raspiScripts/raspi_face_tracker_with_motors.py`](raspiScripts/raspi_face_tracker_with_motors.py)), as well as the practicalities of CAD design (e.g., Fusion 360) and 3D printing for creating custom parts. This hands-on experience was crucial for bringing the physical embodiment of Koki to life.
* **Leveraging AI in Development:** The project also highlighted the benefits of using AI tools. Specifically, AI assistance was instrumental in editing and refining key Python scripts such as [`raspiScripts/rpi_audio_client.py`](raspiScripts/rpi_audio_client.py:1) and [`real_time_ai_agent.py`](real_time_ai_agent.py:1). Furthermore, AI significantly aided the overall debugging process, contributing to more efficient development cycles.

## What's next for Koki

While Koki has achieved its initial goals as a proof-of-concept, there are several things for future development:

* **Enhanced Conversational AI:** A primary focus will be on improving the depth and naturalness of Koki's conversational abilities. This could involve exploring more advanced NLP models within Vertex AI, fine-tuning existing models with more specific data, and implementing more sophisticated dialogue management to handle longer, more complex interactions and remember context more effectively.
* **Expanded Knowledge Base and Integrations:** To make Koki more useful and informative, we plan to expand its knowledge base. This could involve integrating with external APIs to fetch real-time information (e.g., weather, news, general knowledge) or connecting to personal data sources (with user permission) to provide more personalized assistance.
* **Further Latency Reduction and Responsiveness:** Continuous improvement in responsiveness remains a key goal. We will continue to explore ways to reduce latency throughout the system, from optimizing audio processing on the Raspberry Pi to refining the communication between services and potentially exploring edge AI capabilities to handle some tasks locally.
