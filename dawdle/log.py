import logging

logging.SPAMMY = 5
logging.addLevelName("SPAMMY", 5)


log = logging.getLogger()


def init(loglevel):
    log.setLevel(loglevel)


def log_to_file(loglevel, logfile):
    h = logging.FileHandler(logfile)
    h.setLevel(loglevel)
    h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    log.addHandler(h)


def log_to_stderr():
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    log.addHandler(h)
