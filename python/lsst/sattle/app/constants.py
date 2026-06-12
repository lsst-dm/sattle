# flake8: noqa
# https://gist.github.com/jbn/fc90e3ddbc5c60c698d07b3df30004c8
import os
import time
import inspect
import logging
import logging.config
import contextvars

BASE_DIR = os.path.dirname(os.path.abspath(inspect.getfile(
                inspect.currentframe()))) + '/'

TARGET_OUTPUT_DIR = BASE_DIR+'../'

visit_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar('visit_id', default='-')
detector_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar('detector_id', default='-')


class UTCFormatter(logging.Formatter):
    """Output logs in UTC"""
    converter = time.gmtime


class ContextFilter(logging.Filter):
    """Attach visit_id and detector_id from context vars to each log record."""
    def filter(self, record):
        record.visit_id = visit_id_ctx.get()
        record.detector_id = detector_id_ctx.get()
        return True


LOGGING = {
    'version': 1,
    'disable_existing_loggers': True,
    'formatters': {
        'utc': {
            '()': UTCFormatter,
            'format': '%(asctime)s %(levelname)s %(module)s [%(visit_id)s/%(detector_id)s] %(message)s'
        },
        'simple': {
            'format': '%(levelname)s [%(visit_id)s/%(detector_id)s] %(message)s'
        },
    },
    'filters': {
        'context': {
            '()': ContextFilter,
        }
    },
    'handlers': {
        'console':{
            'level':'INFO',
            'class':'logging.StreamHandler',
            'formatter': 'simple',
            'filters': ['context'],
            'stream'  : 'ext://sys.stdout'
        },
        'logfile': {
            'level': 'INFO',
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'filename': f'{BASE_DIR}/../logs/sattle.log',
            'formatter': 'utc',
            'filters': ['context'],
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
