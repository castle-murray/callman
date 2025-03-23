import sys, os
import dotenv
from pathlib import Path 

BASE_DIR = Path(__file__).resolve().parent

INTERP = os.path.join(BASE_DIR, 'venv/bin/python')

#INTERP is present twice so that the new python interpreter
#knows the actual executable path
if sys.executable != INTERP: os.execl(INTERP, INTERP, *sys.argv)

cwd = os.getcwd()
sys.path.append(cwd)
sys.path.append(cwd + '')  #You must add your project here

#sys.path.insert(0,cwd+'/venv/bin')
#sys.path.insert(0,cwd+'/venv/lib/python3.6.8/site-packages')
dotenv.read_dotenv()
os.environ['DJANGO_SETTINGS_MODULE'] = "callman.settings"
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
