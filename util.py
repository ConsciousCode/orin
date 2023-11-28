from functools import wraps
from typing import TYPE_CHECKING, Awaitable, Callable, Iterator, Optional, overload, reveal_type

import logging
import os
from prompt_toolkit import print_formatted_text
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.formatted_text import FormattedText

class ColorLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        fmt ='[%(levelname)s] [%(filename)s:%(lineno)d] %(message)s'
        self.formatter = logging.Formatter(fmt)

    def emit(self, record):
        try:
            with patch_stdout():
                msg = self.format(record)
                color = self.get_color(record.levelno)
                formatted_text = FormattedText([(color, msg)])
                print_formatted_text(formatted_text)
        except Exception:
            self.handleError(record)

    def get_color(self, levelno):
        if levelno >= logging.ERROR:
            return 'ansired'
        elif levelno >= logging.WARNING:
            return 'ansiyellow'
        elif levelno >= logging.INFO:
            return 'ansigreen'
        else:  # DEBUG and NOTSET
            return 'ansiblue'

logger = logging.getLogger("orin")
LOG_LEVEL = "INFO"
if LOG_LEVEL := os.getenv("LOG_LEVEL", LOG_LEVEL):
    logger.addHandler(ColorLogHandler())
    logger.setLevel(LOG_LEVEL.upper())
    logger.info(f"Set log level to {LOG_LEVEL}")

def read_file(filename):
    '''Open and read a text file.'''
    with open(filename, "rt") as f:
        return f.read()

def typename(value):
    '''Return the type name of the value.'''
    return type(value).__name__
