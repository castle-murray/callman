# /home/autorigger/callman/gunicorn.conf.py

import os

# Logging configuration
loglevel = 'info'  # Options: debug, info, warning, error, critical
errorlog = '/home/autorigger/callman/logs/gunicorn_error.log'  # Error logs
accesslog = '/home/autorigger/callman/logs/gunicorn_access.log'  # Access logs
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# Ensure log directory exists
log_dir = '/home/autorigger/callman/logs'
if not os.path.exists(log_dir):
    os.makedirs(log_dir)
