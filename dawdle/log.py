import logging
import sys

logging.SPAMMY = 5
logging.addLevelName("SPAMMY", 5)


log = logging.getLogger()
log.setLevel(0)


def add_handler(loglevel, logfile, template):
    if logfile == "/dev/stdout":
        h = logging.StreamHandler(sys.stdout)
    elif logfile == "/dev/stderr":
        h = logging.StreamHandler(sys.stderr)
    else:
        h = logging.FileHandler(logfile)
    h.setLevel(loglevel)
    h.setFormatter(logging.Formatter(template))
    log.addHandler(h)
