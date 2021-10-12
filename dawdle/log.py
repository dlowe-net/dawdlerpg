import logging

logging.SPAMMY = 5
logging.addLevelName("SPAMMY", 5)


log = logging.getLogger()
log.setLevel(0)


def add_handler(loglevel, logfile, template):
    h = logging.FileHandler(logfile)
    h.setLevel(loglevel)
    h.setFormatter(logging.Formatter(template))
    log.addHandler(h)
