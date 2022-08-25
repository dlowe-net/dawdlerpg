import logging
import sys

from typing import Union

logging.addLevelName(5, "SPAMMY")


log = logging.getLogger()
log.setLevel(0)


def add_handler(loglevel:Union[str, int] , logfile: str, template: str) -> None:
    h: Union[logging.StreamHandler, logging.FileHandler]
    if logfile == "/dev/stdout":
        h = logging.StreamHandler(sys.stdout)
    elif logfile == "/dev/stderr":
        h = logging.StreamHandler(sys.stderr)
    else:
        h = logging.FileHandler(logfile)
    h.setLevel(loglevel)
    h.setFormatter(logging.Formatter(template))
    log.addHandler(h)
