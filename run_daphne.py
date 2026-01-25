# run_daphne.py (in project root)
import os
from dotenv import load_dotenv
from pathlib import Path

# Load .env
env_path = Path(__file__).parent / '.env'
load_dotenv()

# Set Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'callman.settings')

# Now import and run Daphne
from daphne.cli import CommandLineInterface

if __name__ == '__main__':
    CommandLineInterface.entrypoint()
