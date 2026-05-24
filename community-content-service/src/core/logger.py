import os


LOG_FORMAT = '%(asctime)s - %(levelname)-6s {%(filename)s:%(lineno)d} - %(message)s'
LOG_DEFAULT_HANDLERS = ['console']

LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()

LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': LOG_FORMAT,
            'datefmt': '%Y-%m-%dT%H:%M:%S',
        },
    },
    'handlers': {
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        '': {
            'handlers': LOG_DEFAULT_HANDLERS,
            'level': LOG_LEVEL,
            'propagate': True,
        },
        'src': {
            'handlers': LOG_DEFAULT_HANDLERS,
            'level': LOG_LEVEL,
            'propagate': False,
        },
    },
    'root': {
        'level': LOG_LEVEL,
        'handlers': LOG_DEFAULT_HANDLERS,
    },
}
