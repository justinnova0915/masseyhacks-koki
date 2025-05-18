import logging
import os
import re
from datetime import datetime
import requests
import pytz

import kokoro_config as kc
from vertexai.generative_models import GenerativeModel
from google.cloud import aiplatform

# Initialize logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(module)s - %(message)s')

# --- Mappings and helpers for placeholder replacement (Retained from original functionality) ---
HOUR_WORDS = {1: 'one', 2: 'two', 3: 'three', 4: 'four', 5: 'five', 6: 'six',
              7: 'seven', 8: 'eight', 9: 'nine', 10: 'ten', 11: 'eleven', 12: 'twelve'}
DIGIT_WORDS = {0: '', 1: 'one', 2: 'two', 3: 'three', 4: 'four', 5: 'five',
               6: 'six', 7: 'seven', 8: 'eight', 9: 'nine'}
TEEN_WORDS = {10: 'ten', 11: 'eleven', 12: 'twelve', 13: 'thirteen', 14: 'fourteen',
              15: 'fifteen', 16: 'sixteen', 17: 'seventeen', 18: 'eighteen', 19: 'nineteen'}
TENS_PREFIX = {2: 'twenty', 3: 'thirty', 4: 'forty', 5: 'fifty'}

def format_time_to_words(dt_object):
    """Converts a datetime object to a word-based time string, as per original script."""
    hour = dt_object.hour
    minute = dt_object.minute
    am_pm = dt_object.strftime("%p").lower() # e.g., am/pm

    hour_12 = hour % 12
    if hour_12 == 0:  # Midnight or Noon
        hour_12 = 12
    hour_word = HOUR_WORDS.get(hour_12, str(hour_12))

    minute_word_str = "" # This will store the complete minute part, e.g., " o-five" or " ten"
    if 1 <= minute <= 9:
        minute_word_str = f" o-{DIGIT_WORDS.get(minute, str(minute))}"
    elif 10 <= minute <= 19:
        minute_word_str = f" {TEEN_WORDS.get(minute, str(minute))}"
    elif 20 <= minute <= 59:
        tens_digit = minute // 10
        ones_digit = minute % 10
        tens_word = TENS_PREFIX.get(tens_digit, '')
        ones_word_val = DIGIT_WORDS.get(ones_digit, '') # Handle empty string for 0
        minute_word_str = f" {tens_word}{ones_word_val}"
    
    if minute == 0:
         return f"{hour_word} {am_pm}"
    else:
         return f"{hour_word}{minute_word_str} {am_pm}"

location_timezones = {
    "local": os.getenv("LOCAL_TIMEZONE", "America/Detroit"),
    "New York": "America/New_York",
    "LA": "America/Los_Angeles",
    "Los Angeles": "America/Los_Angeles",
    "London": "Europe/London",
    "Toronto": "America/Toronto",
    "Barcelona": "Europe/Madrid",
    "Detroit": "America/Detroit",
    "Tokyo": "Asia/Tokyo",
    "Shanghai": "Asia/Shanghai"
}
weather_location_mapping = {
    "local": os.getenv("LOCAL_WEATHER_CITY", "Detroit")
}

OPENWEATHERMAP_API_KEY_FALLBACK = "58c8308231c9c24eaed12723638efec0" # Original fallback

def normalize_location(query, preserve_numbers=False):
    """Normalizes location strings by removing special characters."""
    if preserve_numbers:
        return re.sub(r'[^a-zA-Z0-9\s]', '', query)
    else:
        return re.sub(r'[^a-zA-Z\s]', '', query)

def replace_placeholders(response_text: str) -> str:
    """Replaces placeholders like $(time:New York) in the LLM's response text."""
    # Post-process common "local" phrases for better readability before placeholder substitution
    if "The current time in local is" in response_text:
        response_text = response_text.replace("The current time in local is", "The current time here is")
    if "The weather in local is" in response_text:
        response_text = response_text.replace("The weather in local is", "The weather here is")

    placeholders = re.findall(r'\$\((.*?)\)', response_text)
    logging.info(f"Found placeholders: {placeholders} in response: '{response_text}'")
    modified_response = response_text

    for placeholder_content in placeholders:
        full_placeholder_tag = f"$({placeholder_content})"
        logging.info(f"Processing placeholder content: '{placeholder_content}'")
        try:
            var_type, var_param = placeholder_content.split(":", 1)
            var_param = var_param.strip()
            logging.info(f"Split into var_type: '{var_type}', var_param: '{var_param}'")
        except ValueError:
            logging.warning(f"Malformed placeholder (could not split by ':'): {full_placeholder_tag} (content: '{placeholder_content}') in response: '{response_text}'")
            continue

        replacement_value = f"[Error: Unprocessed placeholder {full_placeholder_tag}]"

        if var_type == "time":
            location_input = normalize_location(var_param)
            timezone_name = None
            for loc_key, tz_val in location_timezones.items():
                if loc_key.lower() == location_input.lower():
                    timezone_name = tz_val
                    break
            
            if not timezone_name:
                logging.warning(f"Timezone for '{location_input}' not found. Using local timezone.")
                local_tz_name = location_timezones.get("local", "UTC")
                try:
                    timezone = pytz.timezone(local_tz_name)
                    current_time_location = datetime.now(pytz.UTC).astimezone(timezone)
                    time_str = format_time_to_words(current_time_location)
                    replacement_value = f"{time_str} (local time, as '{location_input}' was not recognized)"
                except pytz.UnknownTimeZoneError:
                    replacement_value = f"[Unknown local timezone: {local_tz_name}]"
                except Exception as e:
                    replacement_value = f"[Error getting local time: {str(e)}]"
            else:
                try:
                    timezone = pytz.timezone(timezone_name)
                    current_time_location = datetime.now(pytz.UTC).astimezone(timezone)
                    replacement_value = format_time_to_words(current_time_location)
                except pytz.UnknownTimeZoneError:
                    replacement_value = f"[Unknown timezone: {timezone_name}]"
                except Exception as e:
                    replacement_value = f"[Error getting time for {location_input}: {str(e)}]"

        elif var_type == "weather":
            location_input = normalize_location(var_param)
            actual_location_for_api = weather_location_mapping.get(location_input.lower(), location_input)
            if location_input.lower() == "local": # Explicitly map "local"
                 actual_location_for_api = weather_location_mapping.get("local", "Detroit")
            logging.info(f"Weather processing: location_input='{location_input}', actual_location_for_api='{actual_location_for_api}'")


            api_key = os.getenv("OPENWEATHERMAP_API_KEY", OPENWEATHERMAP_API_KEY_FALLBACK)
            if not api_key or api_key == OPENWEATHERMAP_API_KEY_FALLBACK:
                 logging.warning("OPENWEATHERMAP_API_KEY not found in environment. Using fallback key.")
            
            url = f"http://api.openweathermap.org/data/2.5/weather?q={actual_location_for_api}&appid={api_key}&units=metric"
            try:
                weather_api_response = requests.get(url, timeout=10)
                weather_api_response.raise_for_status()
                weather_data = weather_api_response.json()
                if not weather_data.get("weather") or not weather_data.get("main"):
                    replacement_value = f"[Weather data unavailable for {actual_location_for_api}]"
                else:
                    weather_desc = weather_data["weather"][0].get("description", "N/A")
                    temp = weather_data["main"].get("temp", "N/A")
                    replacement_value = f"{weather_desc}, {temp}°C"
            except requests.exceptions.Timeout:
                replacement_value = f"[Weather API timeout for {actual_location_for_api}]"
            except requests.exceptions.HTTPError as e:
                replacement_value = f"[Weather API error for {actual_location_for_api}: {e.response.status_code}]"
            except requests.exceptions.RequestException as e:
                replacement_value = f"[Weather API connection error for {actual_location_for_api}: {str(e)}]"
            except Exception as e:
                replacement_value = f"[Error processing weather for {actual_location_for_api}: {str(e)}]"
            logging.info(f"Weather replacement value determined: '{replacement_value}' for tag '{full_placeholder_tag}'")
        
        elif var_type == "duration":
            minutes_str = normalize_location(var_param, preserve_numbers=True)
            if minutes_str.isdigit():
                replacement_value = f"{minutes_str} minutes"
            else:
                replacement_value = f"[Invalid duration: {var_param}]"
        else:
            logging.warning(f"Unknown placeholder type: {var_type} in {full_placeholder_tag}")
            replacement_value = f"[Unknown placeholder type: {var_type}]"
        
        logging.info(f"Attempting to replace '{full_placeholder_tag}' with '{replacement_value}' in text: '{modified_response}'")
        modified_response = modified_response.replace(full_placeholder_tag, replacement_value)
        logging.info(f"Text after replacement attempt for '{full_placeholder_tag}': '{modified_response}'")
    
    return modified_response
# --- End of placeholder logic ---


# --- Vertex AI Gemini Integration ---
GCP_PROJECT_ID = kc.GCP_PROJECT_ID
GCP_REGION = kc.GCP_REGION
MODEL_NAME = "gemini-2.0-flash-001"

generative_model_instance = None

try:
    if not GCP_PROJECT_ID or not GCP_REGION:
        logging.error("GCP_PROJECT_ID or GCP_REGION is not set in kokoro_config.py. Vertex AI client will not be initialized.")
    else:
        aiplatform.init(project=GCP_PROJECT_ID, location=GCP_REGION)
        generative_model_instance = GenerativeModel(MODEL_NAME)
        logging.info(f"Vertex AI initialized successfully. Model: {MODEL_NAME}, Project: {GCP_PROJECT_ID}, Region: {GCP_REGION}")
except Exception as e:
    logging.error(f"Failed to initialize Vertex AI or load model '{MODEL_NAME}': {e}", exc_info=True)

SYSTEM_INSTRUCTION_PROMPT = """You are an AI assistant. Your responses must be concise and use no markdown formatting (e.g., no asterisks for bolding, no backticks for code, no lists with hyphens or numbers). Your primary goal is to understand user queries and respond appropriately using specific formats for certain requests.

When the user asks for the current time:
- If no specific location is mentioned, use: 'The current time here is $(time:local).'
- If a specific location is mentioned (e.g., "New York"), use: 'The current time in [Location] is $(time:[Location]).'

When the user asks about the weather:
- If no specific location is mentioned, use: 'The weather here is $(weather:local).'
- If a specific location is mentioned (e.g., "Toronto"), use: 'The weather in [Location] is $(weather:[Location]).'

When the user asks to set a timer (e.g., "set a timer for 5 minutes"):
- Use the format: 'Setting a timer for $(duration:[minutes]).' where [minutes] is the number of minutes.

For all other queries, respond naturally and helpfully. ALWAYS formulate your answers in complete sentences. Avoid single-word or overly brief responses.

Examples of your expected output format:
User: What is the time in New York?
Assistant: The current time in New York is $(time:New York).

User: What time is it?
Assistant: The current time here is $(time:local).

User: What is the weather in Toronto?
Assistant: The weather in Toronto is $(weather:Toronto).

User: How's the weather today?
Assistant: The weather here is $(weather:local).

User: Set a timer for 10 minutes
Assistant: Setting a timer for $(duration:10).

User: Can you explain quantum physics?
Assistant: Quantum physics deals with phenomena at very small scales like atoms and subatomic particles.

User: What's up?
Assistant: Here to help. How can I assist?
"""

def generate_response(user_query: str) -> str:
    """
    Generates a raw response from the Vertex AI Gemini model.
    The user_query is combined with a system instruction prompt.
    Returns the model's direct text output, which may include placeholders.
    """
    if not generative_model_instance:
        logging.error("Vertex AI GenerativeModel is not initialized. Cannot generate response.")
        return "I'm sorry, the AI model is currently unavailable due to an initialization error."

    full_prompt = f"{SYSTEM_INSTRUCTION_PROMPT}\n\nUser: {user_query}\nAssistant:"
    
    logging.info(f"Sending prompt to Vertex AI Gemini ({MODEL_NAME}). User query: '{user_query}'")

    try:
        api_response = generative_model_instance.generate_content(full_prompt)
        
        if api_response.candidates and \
           len(api_response.candidates) > 0 and \
           api_response.candidates[0].content and \
           len(api_response.candidates[0].content.parts) > 0 and \
           hasattr(api_response.candidates[0].content.parts[0], 'text'):
            
            model_text_response = api_response.candidates[0].content.parts[0].text
            logging.info(f"Vertex AI Gemini raw response: '{model_text_response.strip()}'")
            return model_text_response.strip()
        else:
            # Log the actual response structure if it's not as expected
            logging.warning(f"Vertex AI Gemini response was not in the expected format. API Response: {api_response}")
            return "I'm sorry, I received an unexpected response from the AI model."

    except Exception as e:
        logging.error(f"Error calling Vertex AI Gemini API: {e}", exc_info=True)
        return "I encountered an error while trying to communicate with the AI model."

# --- End of Vertex AI Gemini Integration ---

# Example usage for direct testing of this module:
if __name__ == '__main__':
    logging.info("Running infer.py directly for testing...")
    if not generative_model_instance:
        logging.error("Generative model not initialized. Cannot run tests.")
    else:
        test_queries = [
            "What time is it?",
            "What is the time in London?",
            "What's the weather like in Paris?",
            "What's the weather like?",
            "Set a timer for 5 minutes",
            "Tell me a joke.",
            "What is the capital of France?"
        ]

        for query in test_queries:
            print(f"\n--- Testing Query: \"{query}\" ---")
            raw_llm_response = generate_response(query)
            print(f"  [LLM Raw]: {raw_llm_response}")

            if "I'm sorry" not in raw_llm_response and "I encountered an error" not in raw_llm_response and raw_llm_response:
                final_processed_response = replace_placeholders(raw_llm_response)
                print(f"  [Processed]: {final_processed_response}")
            else:
                print(f"  [Result]: Error or empty response from LLM.")
        logging.info("Direct testing of infer.py complete.")