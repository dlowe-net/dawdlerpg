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

# This bot is structured in layers.
# - IRCClient   : Networking and IRC protocol
#     -> IRCEvents ->
# - BotCommands : commands, identity, authentication, access
#     -> BotEvents ->
# - DawdleBot   : Actual game
#
# IRCEvents wrap IRCMessages, and BotEvents wrap IRCEvents.

import argparse
import asyncio
import collections
import crypt
import logging
import os
import os.path
import random
import re
import sqlite3
import sys
import time

log = logging.getLogger()

VERSION = "1.0.0"

# Commands in ALLOWALL can be used by anyone.
# Commands in ALLOWUSERS can only be used by logged-in users
# All other commands are admin-only
ALLOWALL = ["help", "login", "register", "quest", "version", "eval"]
ALLOWUSERS = ["align", "logout", "newpass", "removeme", "status", "whoami"]

# Penalties and their description
PENALTIES = {"quit": 20, "nick": 30, "message": 1, "part": 200, "kick": 250, "logout": 20}
PENDESC = {"quit": "quitting", "nick": "changing nicks", "message": "messaging", "part": "parting", "kick": "being kicked", "logout": "LOGOUT command"}

# command line overrides .irpg.conf
parser = argparse.ArgumentParser(description="IdleRPG clone")
parser.add_argument("-v", "--verbose")
parser.add_argument("--debug")
parser.add_argument("--debugfile")
parser.add_argument("-s", "--server", action="append")
parser.add_argument("-n", "--botnick")
parser.add_argument("-u", "--botuser")
parser.add_argument("-r", "--botrlnm")
parser.add_argument("-c", "--botchan")
parser.add_argument("-p", "--botident")
parser.add_argument("-m", "--botmodes")
parser.add_argument("-o", "--botopcmd")
parser.add_argument("--localaddr")
parser.add_argument("-g", "--botghostcmd")
parser.add_argument("--helpurl")
parser.add_argument("--admincommurl")
parser.add_argument("--doban")
parser.add_argument("--silentmode", type=int)
parser.add_argument("--writequestfile")
parser.add_argument("--questfilename")
parser.add_argument("--voiceonlogin")
parser.add_argument("--noccodes")
parser.add_argument("--nononp")
parser.add_argument("--mapurl")
parser.add_argument("--statuscmd")
parser.add_argument("--pidfile")
parser.add_argument("--reconnect")
parser.add_argument("--reconnect_wait", type=int)
parser.add_argument("--self_clock", type=int)
parser.add_argument("--modsfile")
parser.add_argument("--casematters")
parser.add_argument("--detectsplits")
parser.add_argument("--splitwait", type=int)
parser.add_argument("--allowuserinfo")
parser.add_argument("--noscale")
parser.add_argument("--owner")
parser.add_argument("--owneraddonly")
parser.add_argument("--ownerdelonly")
parser.add_argument("--ownerpevalonly")
parser.add_argument("--senduserlist")
parser.add_argument("--limitpen", type=int)
parser.add_argument("--mapx", type=int)
parser.add_argument("--mapy", type=int)
parser.add_argument("--modesperline", type=int)
parser.add_argument("-k", "--okurl", action="append")
parser.add_argument("--eventsfile")
parser.add_argument("--rpstep", type=float)
parser.add_argument("--rpbase", type=int)
parser.add_argument("--rppenstep", type=float)
parser.add_argument("-d", "--dbfile", "--irpgdb", "--db")

args = parser.parse_args()
rps = dict()
preferred_nick = ""
silent_mode = False
pause_mode = False

NUMERIC_RE = re.compile(r"[+-]?\d+(?:(\.)\d*)?")


def parse_val(s):
    if s in ["on", "yes", "true"]:
        return True
    if s in ["off", "no", "false"]:
        return False
    isnum = NUMERIC_RE.match(s)
    if isnum:
        if isnum[1]:
            return float(s)
        return int(s)
    return s


def read_config(path):
    newconf = {"servers": [], "okurls": []}
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
                key, val = match[1].lower(), match[2]
                if key == "die":
                    log.critical(f"Please edit {path} to setup your bot's options.")
                    sys.exit(1)
                elif key == "server":
                    newconf["servers"].append(val)
                elif key == "okurl":
                    newconf["servers"].append(val)
                else:
                    newconf[key] = parse_val(val)
    except OSError as err:
        log.critical(f"Unable to read {path}")
        sys.exit(1)
    return newconf


class User(object):
    def __init__(self, d):
        for k,v in d.items():
            setattr(self, k, v)


class UserDB(object):

    FIELDS = ["name", "cclass", "pw", "isadmin", "level", "nextlvl", "nick", "userhost", "online", "idled", "posx", "posy", "penmesg", "pennick", "penpart", "penkick", "penquit", "penquest", "penlogout", "created", "lastlogin", "amulet", "charm", "helm", "boots", "gloves", "ring", "leggings", "shield", "tunic", "weapon", "alignment"]


    @classmethod
    def dict_factory(cls, cursor, row):
        d = {}
        for idx, col in enumerate(cursor.description):
            d[col[0]] = row[idx]
        return d


    def __init__(self, dbpath):
        self._dbpath = dbpath
        self._db = None
        self._users = {}

    def __getitem__(self, uname):
        return self._users[uname]


    def _connect(self):
        if self._db is None:
            self._db = sqlite3.connect(self._dbpath)
            self._db.row_factory = UserDB.dict_factory

        return self._db


    def exists(self):
        return os.path.exists(self._dbpath)


    def load(self):
        """Load all users from database into memory"""
        self._users = {}
        with self._connect() as con:
            cur = con.execute("select * from users")
            for d in cur.fetchall():
                self._users[d['name']] = User(d)


    def write(self):
        """Write all users into database"""
        with self._connect() as cur:
            update_fields = ",".join(f"{k}=:{k}" for k in UserDB.FIELDS)
            cur.executemany(f"update users set {update_fields} where name=:name",
                            [vars(u) for u in self._users.values()])


    def create(self):
        with self._connect() as cur:
            cur.execute(f"create table users ({','.join(UserDB.FIELDS)})")


    def new_user(self, uname, uclass, upass):
        global conf

        if uname in self._users:
            raise KeyError

        uclass = uclass[:30]
        upass = crypt.crypt(upass, crypt.mksalt())
        d = {
            'name': uname,
            'cclass': uclass,
            'pw': upass,
            'isadmin': False,
            'level': 0,
            'nextlvl': 0,
            'nick': "",
            'userhost': "",
            'online': False,
            'idled': 0,
            'posx': 0,
            'posy': 0,
            'penmesg': 0,
            'pennick': 0,
            'penpart': 0,
            'penkick': 0,
            'penquit': 0,
            'penquest': 0,
            'penlogout': 0,
            'created': time.time(),
            'lastlogin': time.time(),
            'amulet': 0,
            'charm': 0,
            'helm': 0,
            'boots': 0,
            'gloves': 0,
            'ring': 0,
            'leggings': 0,
            'shield': 0,
            'tunic': 0,
            'weapon': 0,
            'alignment': "n"
        }
        with self._connect() as cur:
            cur.execute(f"insert into users values ({('?, ' * len(d))[:-2]})",
                        [d[k] for k in UserDB.FIELDS])
            cur.commit()

        u = User(d)
        self._users[uname] = u

        return u

    def pw_check(self, uname, upass):
        return crypt.crypt(upass, _users[uname].pw) == _users[uname].pw


def first_setup():
    global conf
    global db

    if db.exists():
        return
    uname = input(f"{conf['dbfile']} does not appear to exist.  I'm guessing this is your first time using DawdleRPG. Please give an account name that you would like to have admin access [{conf['owner']}]: ")
    if uname == "":
        uname = conf["owner"]
    uclass = input("Enter a character class for this account: ")
    uclass = uclass[:30]
    upass = input("Enter a password for this account: ")

    db.create()
    u = db.new_user(uname, uclass, upass)
    u.isadmin = True
    db.write()

    print(f"OK, wrote you into {conf['dbfile']}")


class IRCClient:
    """IRCClient acts as a layer between the IRC protocol and the bot protocol.

    This class has the following responsibilities:
    - Connection and disconnection
    - Nick recovery
    - Output throttling
    - NickServ authentication
    - IRC message decoding and parsing
    - Calling methods on the bot interface
 """
    MESSAGE_RE = re.compile(r'^(?:@(\S*) )?(?::([^ !]*)(?:!([^ @]*)(?:@([^ ]*))?)?\s+)?(\S+)\s*((?:[^:]\S*(?:\s+|$))*)(?::(.*))?')

    Message = collections.namedtuple('Message', ['tags', 'src', 'user', 'host', 'cmd', 'args', 'trailing', 'line', 'time'])


    def __init__(self):
        _writer = None


    async def connect(self, addr, port):
        reader, self._writer = await asyncio.open_connection(addr, port, ssl=True)
        self.send(f"NICK {conf['botnick']}")
        self.send(f"USER {conf['botuser']} 0 * :{conf['botrlnm']}")
        while True:
            line = await reader.readline()
            if not line:
                break
            if conf["debug"]:
                print("<- ", line)
            msg = self.parse_message(line)
            self.dispatch(msg)


    def send(self, s):
        if conf["debug"]:
            print("-> ", s)
        self._writer.write(bytes(s+"\r\n", encoding='utf8'))


    def parse_message(self, line):
        # Assume utf-8 encoding, fall back to latin-1, which has no invalid encodings from bytes.
        try:
            line = str(line, encoding='utf8')
        except UnicodeDecodeError:
            line = str(line, encoding='latin-1')

        # Parse IRC message with a regular expression
        match = IRCClient.MESSAGE_RE.match(line)
        if not match:
            return None
        rawtags, src, user, host, cmd, args, trailing = match.groups()
        # IRCv3 supports tags
        tags = dict()
        if rawtags is not None and rawtags != "":
            for pairstr in rawtags.split(','):
                pair = pairstr.split('=')
                if len(pair) == 2:
                    tags[pair[0]] = pair[1]
                else:
                    tags[pair[0]] = None
        # Arguments before the trailing argument (after the colon) are space-delimited
        args = args.rstrip().split(' ')
        # There's nothing special about the trailing argument except it can have spaces.
        if trailing != "":
            args.append(trailing)
        # Numeric responses specify a useless target afterwards
        if re.match(r'^\d$', cmd):
            args = args[1:]
        # Support time tag, which allows servers and bouncers to send history
        if 'time' in tags:
            msgtime = time.mktime(time.strptime(tags['time'], "%Y-%m-%dT%H:%M:%S"))
        else:
            msgtime = time.time()
        return IRCClient.Message(tags, src, user, host, cmd, args, trailing, line, msgtime)


    def handle_ping(self, msg):
        self.send(f"PONG {msg.trailing}")


    def handle_376(self, msg):
        self.send(f"MODE {conf['botnick']} {conf['botmodes']}")
        self.send(f"JOIN {conf['botchan']}")


    def handle_433(self, msg):
        """Nick collision - stow our nick and try to get it back"""
        pass

    def handle_join(self, msg):
        pass


    def handle_part(self, msg):
        pass


    def handle_nick(self, msg):
        pass


    def handle_quit(self, msg):
        pass


    def handle_notice(self, msg):
        pass


    def handle_privmsg(self, msg):
        pass


    def dispatch(self, msg):
        if hasattr(self, "handle_"+msg.cmd.lower()):
            getattr(self, "handle_"+msg.cmd.lower())(msg)


async def main():
    client = IRCClient()
    while True:
        addr, port = conf['servers'][0].split(':')
        await client.connect(addr, port)


def start_bot():
    global conf
    conf = read_config("irpg.conf")

    # override configurations from command line
    for k,v in vars(args).items():
        if v is not None and k in conf:
            conf[k] = parse_val(v)
    if args.server:
        conf["servers"] = args.server
    if args.okurl:
        conf["okurls"] = args.okurl

    global db
    db = UserDB(conf["dbfile"])
    if db.exists():
        db.load()
    else:
        first_setup()

    asyncio.run(main())


if __name__ == "__main__":
    start_bot()
