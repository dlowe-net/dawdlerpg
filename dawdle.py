#!/usr/bin/python3

# Copyright 2021 Daniel Lowe
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio
import atexit
import logging
import os
import os.path
import resource
import signal
import sys
import termios

from dawdle import bot
from dawdle import conf
from dawdle import irc
from dawdle.log import log
import dawdle.log as dawdlelog


def first_setup(db):
    """Perform initialization of game."""
    if db.exists():
        return
    pname = input(f"{bot.datapath(conf.conf['dbfile'])} does not appear to exist.  I'm guessing this is your first time using DawdleRPG. Please give an account name that you would like to have admin access [{conf.conf['owner']}]: ")
    if pname == "":
        pname = conf.conf["owner"]
    pclass = input("Enter a character class for this account: ")
    pclass = pclass[:conf.conf["max_class_len"]]
    try:
        old = termios.tcgetattr(sys.stdin.fileno())
        new = old.copy()
        new[3] = new[3] & ~termios.ECHO
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, new)
        ppass = input("Password for this account: ")
    finally:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old)

    db.create()
    p = db.new_player(pname, pclass, ppass)
    p.isadmin = True
    db.write()

    print(f"OK, wrote you into {conf.datapath(conf.conf['dbfile'])}")


def check_pidfile(pidfile):
    """Exit if pid in pidfile is still active."""
    try:
        with open(pidfile) as inf:
            pid = int(inf.readline().rstrip())
            try:
                os.kill(pid, 0)
            except OSError:
                pass
            else:
                sys.stderr.write(f"The pidfile at {pidfile} indicates that dawdle is still running at pid {pid}.  Remove the file or kill the process.\n")
                sys.exit(1)
    except FileNotFoundError:
        pass


def daemonize():
    """Daemonize the process."""
    # python-daemon on pip would do this better.

    # set core limit to 0
    core_limit = (0, 0)
    resource.setrlimit(resource.RLIMIT_CORE, core_limit)
    os.umask(0)

    signal.signal(signal.SIGCHLD, signal.SIG_IGN)
    pid = os.fork()
    if pid > 0:
        os._exit(0)
    os.setsid()
    pid = os.fork()
    if pid > 0:
        os._exit(0)
    os.chdir("/")
    signal.signal(signal.SIGTSTP, signal.SIG_IGN)
    signal.signal(signal.SIGTTIN, signal.SIG_IGN)
    signal.signal(signal.SIGTTOU, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    os.dup2(os.open(os.devnull, os.O_RDWR), sys.stdin.fileno())
    os.dup2(os.open(os.devnull, os.O_RDWR), sys.stdout.fileno())
    os.dup2(os.open(os.devnull, os.O_RDWR), sys.stderr.fileno())


async def mainloop(client):
    """Connect to servers repeatedly."""
    while not client.quitting:
        addr, port = conf.conf['servers'][0].split(':')
        await client.connect(addr, port)
        if not conf.conf['reconnect']:
            break
        await asyncio.sleep(conf.conf['reconnect_wait'])


def start_bot():
    """Main entry point for bot."""
    conf.init()

    # debug mode turns off daemonization, sets log level to debug, and logs to stderr
    if conf.conf["debug"]:
        conf.conf["daemonize"] = False
        conf.conf["loglevel"] = logging.DEBUG
        dawdlelog.log_to_stderr()

    dawdlelog.init(conf.conf["loglevel"])

    if "logfile" in conf.conf:
        dawdlelog.log_to_file(conf.conf["loglevel"], conf.conf["logfile"])

    log.info("Bot %s starting.", bot.VERSION)

    if conf.conf["store_format"] == "idlerpg":
        store = bot.IdleRPGGameStorage(bot.datapath(conf.conf["dbfile"]))
    elif conf.conf["store_format"] == "sqlite3":
        store = bot.Sqlite3GameStorage(bot.datapath(conf.conf["dbfile"]))
    else:
        sys.stderr.write(f"Invalid configuration store_format={conf.conf['store_format']}.  Configuration must be idlerpg or sqlite3.")
        sys.exit(1)

    db = bot.GameDB(store)
    if db.exists():
        db.backup_store()
        db.load_players()
    else:
        first_setup(db)

    if 'pidfile' in conf.conf:
        check_pidfile(bot.datapath(conf.conf['pidfile']))

    if conf.conf['daemonize']:
        daemonize()

    if 'pidfile' in conf.conf:
        with open(bot.datapath(conf.conf['pidfile']), "w") as ouf:
            ouf.write(f"{os.getpid()}\n")
        atexit.register(os.remove, bot.datapath(conf.conf['pidfile']))

    mybot = bot.DawdleBot(db)
    client = irc.IRCClient(mybot)

    log.info("Starting main async loop.")
    asyncio.run(mainloop(client))


if __name__ == "__main__":
    start_bot()
