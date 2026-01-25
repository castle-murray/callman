# run_daphne.py (in project root)
import os
from dotenv import load_dotenv
from pathlib import Path

# Load .env
env_path = Path(__file__).parent / '.env'
load_dotenv()

# Set Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'callman.settings')

# Now import and run Daphne with auto-reload
from daphne.cli import CommandLineInterface
import hupper

def run_daphne():
    CommandLineInterface.entrypoint()

if __name__ == '__main__':
    reloader = hupper.start_reloader(run_daphne)
    run_daphne()
