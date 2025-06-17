# /home/autorigger/callman/gunicorn.conf.py

from pathlib import Path
import os 

cwd = Path(os.getcwd())

logdir = cwd.parent.parent / 'logs'


# Logging configuration
if os.environ.get('DEBUG'):
    loglevel = 'debug'
else:
    loglevel = 'info'
accesslog = logdir / 'access.log'
errorlog = logdir / 'error.log'
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# Ensure log directory exists

if not logdir.exists():
    logdir.mkdir(parents=True)
