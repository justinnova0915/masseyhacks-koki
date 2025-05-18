# Save this as testScripts/testEnv.py
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Print the current working directory to confirm where .env should be
print("Current working directory:", os.getcwd())

# Check if .env file exists in the current directory
env_path = os.path.join(os.getcwd(), ".env")
print(".env file exists:", os.path.exists(env_path))

# Print the GOOGLE_APPLICATION_CREDENTIALS variable from .env
credential_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
print("GOOGLE_APPLICATION_CREDENTIALS from .env:", credential_path)

# Verify if the credential file exists at the specified path
if credential_path:
    print("Credential file exists at path:", os.path.exists(credential_path))
else:
    print("No GOOGLE_APPLICATION_CREDENTIALS found in .env")