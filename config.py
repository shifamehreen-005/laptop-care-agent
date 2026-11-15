"""Settings for the Laptop Care test run."""

# Sandbox only. This is not the real Downloads folder.
TEST_FOLDER = r"C:\LaptopCareTest\Downloads"

# A file bigger than this is listed under Large files. The box starts unticked.
LARGE_FILE_MB = 100

# Categories a file in the test folder can belong to.
CATEGORIES = [
    "Receipts",
    "School",
    "Work",
    "Screenshots",
    "Installers",
    "Archives",
    "Photos",
    "Other",
]

# Local Ollama models the eval can compare. The app uses DEFAULT_MODEL.
MODELS = ["llama3.2:1b", "llama3.2:3b", "qwen2.5:3b"]
DEFAULT_MODEL = "llama3.2:1b"
