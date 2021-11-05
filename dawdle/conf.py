import argparse
import logging
import os.path
import re
import sys

from dawdle.log import log
from typing import cast, Any, Dict, List, Union, Tuple

DURATION_RE = re.compile(r"(\d+)([dhms])")
NUMERIC_RE = re.compile(r"[+-]?\d+(?:(\.)\d*)?")

_conf = dict()


def parse_val(s: str) -> Union[bool, float, str]:
    """Parse values used in the configuration file."""
    if s in ["on", "yes", "true"]:
        return True
    if s in ["off", "no", "false"]:
        return False
    istime = DURATION_RE.match(s)
    if istime:
        return int(istime[1]) * {"d":86400, "h": 3600, "m": 60, "s": 1}[istime[2]]

    isnum = NUMERIC_RE.match(s)
    if isnum:
        if isnum[1]:
            return float(s)
        return int(s)
    return s


def read_config(path: str) -> Dict[str, Any]:
    """Return dict with contents of configuration file."""
    newconf = {
        "setup": False,
        "servers": [],
        "okurls": [],
        "loggers": [],
        "localaddr": None,
        # Legacy idlerpg option
        "debug": False,
        # Non-idlerpg config needs defaults
        "confpath": os.path.realpath(path),
        "datadir": os.path.realpath(os.path.dirname(path)),
        "rpmaxexplvl": 60,
        "allylvlbase": 200,
        "allylvlstep": 1.16,
        "allymaxexplvl": 60,
        "backupdir": ".dbbackup",
        "store_format": "idlerpg",
        "daemonize": True,
        "loglevel": "DEBUG",
        "throttle": True,
        "throttle_rate": 4,
        "throttle_period": 1,
        "penquest": 15,
        "pennick": 30,
        "penmessage": 1,
        "penpart": 200,
        "penkick": 250,
        "penquit": 20,
        "pendropped": 20,
        "penlogout": 20,
        "good_battle_pct": 110,
        "evil_battle_pct": 90,
        "max_name_len": 16,
        "max_class_len": 30,
        "message_wrap_len": 400,
        "quest_interval_min": 12*3600,
        "quest_interval_max": 24*3600,
        "quest_min_level": 24,
        "color": False,
        "namecolor": "cyan",
        "durationcolor": "green",
        "itemcolor": "olive",
    }

    ignore_line_re = re.compile(r"^\s*(?:#|$)")
    config_line_re = re.compile(r"^\s*(\S+)\s*(.*)$")
    try:
        with open(path) as inf:
            for line in inf:
                if ignore_line_re.match(line):
                    continue
                match = config_line_re.match(line)
                if not match:
                    log.warning("Invalid config line: "+line)
                    continue
                key, val = match[1].lower(), match[2].rstrip()
                if key == "die":
                    log.critical(f"Please edit {path} to setup your bot's options.")
                    sys.exit(1)
                elif key == "server":
                    cast(List[str], newconf["servers"]).append(val)
                elif key == "okurl":
                    cast(List[str], newconf["okurls"]).append(val)
                elif key == "log":
                    cast(List[List[str]], newconf["loggers"]).append(val.split(" ", 2))
                else:
                    newconf[key] = parse_val(val)
    except OSError as err:
        log.critical(f"Unable to read {path}")
        sys.exit(1)
    return newconf


def init() -> None:
    global _conf
    parser = argparse.ArgumentParser(description="IdleRPG clone")
    parser.add_argument("-o", "--override", action='append', default=[], help="Override config option in k=v format.")
    parser.add_argument("--setup", default=False, action="store_true", help="Begin initial setup.")
    parser.add_argument("--migrate", help="Migrate game to slqite3 db at path.")
    parser.add_argument("config_file", help="Path to configuration file.  You must specify this.")

    args = parser.parse_args()
    _conf.update(read_config(args.config_file))

    _conf['setup'] = args.setup
    _conf['migrate'] = args.migrate

    # override configurations from command line
    server_overrides = []
    okurl_overrides = []
    for pair in args.override:
        if "=" not in pair:
            sys.stderr.write("Overrides must be in k=v format.\n")
            sys.exit(1)
        k,v = pair.split('=', 1)
        if k == "server":
            server_overrides.append(v)
        elif k == "okurl":
            okurl_overrides.append(v)
        else:
            _conf[k] = parse_val(v)
    if server_overrides:
        _conf["servers"] = server_overrides
    if okurl_overrides:
        _conf["okurls"] = okurl_overrides

    # Debug flag turns off daemonization, sets loglevel to debug, and logs to stderr
    if _conf["debug"]:
        _conf["daemonize"] = False
        _conf["loglevel"] = logging.DEBUG


def get(key: str) -> Any:
    return _conf[key]

def has(key: str) -> Any:
    return key in _conf
