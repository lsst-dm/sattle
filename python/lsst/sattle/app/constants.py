# flake8: noqa
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


SELFTEST_LINE1 = "1 28900U 05044B   24332.40839354  .00016856  00000-0  30171-2 0  9992"
SELFTEST_LINE2 = "2 28900   3.1618  27.4062 7009977 210.3167  77.0063  2.63739217169425"
SELFTEST_JD_START = 2460641.549147066
SELFTEST_JD_END = 2460641.550536177

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
