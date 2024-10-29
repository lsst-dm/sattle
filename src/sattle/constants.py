# https://gist.github.com/jbn/fc90e3ddbc5c60c698d07b3df30004c8
import os
import time
import inspect
import logging
import logging.config

BASE_DIR = os.path.dirname(os.path.abspath(inspect.getfile(
                inspect.currentframe()))) + '/'

TARGET_OUTPUT_DIR = BASE_DIR+'../'

class UTCFormatter(logging.Formatter):
    """Output logs in UTC"""
    converter = time.gmtime


LOGGING = {
    'version': 1,
    'disable_existing_loggers': True,
    'formatters': {
        'utc': {
            '()': UTCFormatter,
            'format': '%(asctime)s %(levelname)s %(module)s %(message)s'
        },
        'simple': {
            'format': '%(levelname)s %(message)s'
        },
    },
    'handlers': {
        'console':{
            'level':'INFO',
            'class':'logging.StreamHandler',
            'formatter': 'simple',
            'stream'  : 'ext://sys.stdout'
        },
        'logfile': {
            'level': 'INFO',
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'filename': f'{BASE_DIR}/../logs/sattle.log',
            'formatter': 'utc',
            'when': 'midnight',
            'utc': 'True'
        }
    },
    'loggers': {
        '': { # this is the root logger; doesn't work if we call it root
            'handlers':['console','logfile'],
            'level':'INFO',
        },
        'aiohttp': {
            'handlers':['logfile'],
            'level':'INFO',
        },
        'gurobipy': {
            'handlers':['logfile'],
            'level':'INFO',
            'propagate':False,
        },
        'ztf_sim.field_selection_functions': {
            'handlers':['console','logfile'],
            'level':'INFO',
            'propagate':False,
        },
        'ztf_sim.optimize': {
            'handlers':['console','logfile'],
            'level':'INFO',
            'propagate':False,
        }
    }
}
