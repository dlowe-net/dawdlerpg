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
import re
import resource
import signal
import sys
import termios
import time

from dawdle import bot
from dawdle import conf
from dawdle import irc
from dawdle.log import log
import dawdle.log as dawdlelog


def first_setup(db: bot.GameDB) -> None:
    """Perform initialization of game."""
    pname = input(f"Initializing dbfile {bot.datapath(conf.get('dbfile'))}.  Give an account name that you would like to have admin access [{conf.get('owner')}]: ")
    if pname == "":
        pname = conf.get("owner")
    pclass = input("Enter a character class for this account: ")
    pclass = pclass[:conf.get("max_class_len")]
    try:
        old = termios.tcgetattr(sys.stdin.fileno())
        new = old.copy()
        new[3] = new[3] & ~termios.ECHO
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, new)
        ppass = input("Password for this account: ")
    finally:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old)

    if db.exists():
        db.clear()
    else:
        db.create()
    p = db.new_player(pname, pclass, ppass)
    p.isadmin = True
    db.write_players()

    print(f"\n\nOK, wrote you into {bot.datapath(conf.get('dbfile'))}\n")


def check_pidfile(pidfile: str) -> None:
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


def daemonize() -> None:
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


async def mainloop(client: irc.IRCClient) -> None:
    """Connect to servers repeatedly."""
    while not client.quitting:
        addr, port = conf.get("servers")[0].split(':')
        await client.connect(addr, port)
        if client.quitting or not conf.get("reconnect"):
            break
        await asyncio.sleep(conf.get("reconnect_wait"))


def start_bot() -> None:
    """Main entry point for bot."""
    conf.init()

    # Legacy IdleRPG logging config
    if conf.get("debug"):
        dawdlelog.add_handler("DEBUG", "/dev/stderr", "%(asctime)s %(message)s")

    if conf.has("logfile"):
        dawdlelog.add_handler(conf.get("loglevel"),
                              bot.datapath(conf.get("logfile")),
                              "%(asctime)s %(message)s")

    # DawdleRPG logging config
    for logger in conf.get("loggers"):
        if len(logger) != 3:
            sys.stderr.write(f"Invalid log configuration {logger}.")
            sys.exit(2)
        dawdlelog.add_handler(logger[0], bot.datapath(logger[1]), logger[2])

    log.info("Bot %s starting.", bot.VERSION)

    store: bot.GameStorage
    if conf.get("store_format") == "idlerpg":
        store = bot.IdleRPGGameStorage(bot.datapath(conf.get("dbfile")))
    elif conf.get("store_format") == "sqlite3":
        store = bot.Sqlite3GameStorage(bot.datapath(conf.get("dbfile")))
    else:
        sys.stderr.write(f"Invalid configuration store_format={conf.get('store_format')}.  Configuration must be idlerpg or sqlite3.")
        sys.exit(2)

    if conf.get("setup"):
        if store.exists():
            store.clear()
        first_setup(bot.GameDB(store))
        sys.exit(0)

    db = bot.GameDB(store)
    if not db.exists():
        sys.stderr.write("Game db doesn't exist.  Run with --setup.")
        sys.exit(6)

    db.backup_store()
    db.load_state()

    if conf.get("migrate"):
        new_store = bot.Sqlite3GameStorage(conf.get("migrate"))
        if new_store.exists():
            new_store.clear()
        else:
            new_store.create()
        print(f"Writing {db.count_players()} players.")
        new_store.write(db._players.values())
        print(f"Writing quest.")
        new_store.update_quest(db._quest)
        # Update history from modsfile.
        print(f"Writing history.")
        names = set(db._players.keys())
        history = []
        with open(bot.datapath(conf.get("modsfile")), "rb") as inf:
            for linebytes in inf.readlines():
                try:
                    line = str(linebytes, encoding='utf8')
                except UnicodeDecodeError:
                    line = str(linebytes, encoding='latin-1')

                match = re.match(r'\[(\d\d)/(\d\d)/(\d\d) (.*?)\] (.*)', line)
                if not match:
                    print(f"Line didn't parse: {line}")
                    continue
                mon, day, year, timeofday, text = match.groups()
                for word in re.findall(r"\w+", text):
                    if word in names:
                        history.append((word, f"20{year}-{mon}-{day} {timeofday}", text))
            if len(history) > 10000:
                new_store.bulk_history_insert(history)
                history = []
        new_store.bulk_history_insert(history)
        print("Done.")
        sys.exit(0)

    if db.count_players() == 0:
        sys.stderr.write(f"Zero players in {conf.get('dbfile')}.  Do you need to run with --setup?\n")
        sys.exit(6)

    if conf.has("pidfile"):
        check_pidfile(bot.datapath(conf.get("pidfile")))

    if conf.get("daemonize"):
        daemonize()

    if conf.has("pidfile"):
        with open(bot.datapath(conf.get("pidfile")), "w") as ouf:
            ouf.write(f"{os.getpid()}\n")
        atexit.register(os.remove, bot.datapath(conf.get("pidfile")))

    mybot = bot.DawdleBot(db)
    client = irc.IRCClient(mybot)

    log.info("Starting main async loop.")
    asyncio.run(mainloop(client))


if __name__ == "__main__":
    start_bot()
