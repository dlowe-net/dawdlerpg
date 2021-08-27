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

import argparse
import asyncio
import atexit
import collections
import crypt
import itertools
import logging
import os
import os.path
import random
import re
import resource
import shutil
import signal
import sqlite3
import sys
import termios
import textwrap
import time

from hmac import compare_digest as compare_hash
from operator import attrgetter

logging.SPAMMY = 5
logging.addLevelName("SPAMMY", 5)
log = logging.getLogger()

VERSION = "1.0.0"

parser = argparse.ArgumentParser(description="IdleRPG clone")
parser.add_argument("-o", "--override", action='append', default=[], help="Override config option in k=v format.")
parser.add_argument("config_file", help="Path to configuration file.  You must specify this.")


args = None
conf = {}
start_time = int(time.time())

def plural(num, singlestr='', pluralstr='s'):
    """Return singlestr when num is 1, otherwise pluralstr."""
    if num == 1:
        return singlestr
    return pluralstr


def grouper(iterable, n):
    """Collect data into fixed-length chunks or blocks

    grouper('ABCDEFG', 3, 'x') --> ABC DEF Gxx
    """
    return [iterable[i:i+n] for i in range(0, len(iterable), n)]


def duration(secs):
    """Return description of duration marked in seconds."""
    d, secs = int(secs / 86400), secs % 86400
    h, secs = int(secs / 3600), secs % 3600
    m, secs = int(secs / 60), secs % 60
    return C("duration", f"{d} day{plural(d)}, {h:02d}:{m:02d}:{int(secs):02d}")


def datapath(path):
    """Return path relative to datadir unless path is absolute."""
    global conf
    if os.path.isabs(path):
        return path
    return os.path.join(conf["datadir"], path)


def CC(color):
    """Return color code if colors are enabled."""
    if "color" not in conf or not conf["color"]:
        return ""
    colors = {"white": 0, "black": 1, "navy": 2, "green": 3, "red": 4, "maroon": 5, "purple": 6, "olive": 7, "yellow": 8, "lgreen": 9, "teal": 10, "cyan": 11, "blue": 12, "magenta": 13, "gray": 14, "lgray": 15, "default": 99}
    if color not in colors:
        return f"[{color}?]"
    return f"\x03{colors[color]:02d},99"


def C(field='', text=''):
    """Return colorized version of text according to config field.

    If text is specified, returns the colorized version with a formatting reset.
    If text is not specified, returns just the color code.
    If field is not specified, returns just a formatting reset.
    """
    if "color" not in conf or not conf["color"]:
        return text
    if field == "":
        return "\x0f"
    conf_field = f"{field}color"
    if conf_field not in conf:
        return f"[{conf_field}?]" + text
    if text == "":
        return CC(conf[conf_field])
    return CC(conf[conf_field]) + text + "\x0f"


DURATION_RE = re.compile(r"(\d+)([dhms])")
NUMERIC_RE = re.compile(r"[+-]?\d+(?:(\.)\d*)?")


def parse_val(s):
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


def read_config(path):
    """Return dict with contents of configuration file."""
    newconf = {
        "servers": [],
        "okurls": [],
        # Non-idlerpg config needs defaults
        "datadir": os.path.realpath(os.path.dirname(path)),
        "backupdir": ".dbbackup",
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
        "itemcolor": "yellow",
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
                    newconf["servers"].append(val)
                elif key == "okurl":
                    newconf["okurls"].append(val)
                else:
                    newconf[key] = parse_val(val)
    except OSError as err:
        log.critical(f"Unable to read {path}")
        sys.exit(1)
    return newconf


class Player(object):
    """Represents a player of the dawdlerpg game."""


    ITEMS = ['ring', 'amulet', 'charm', 'weapon', 'helm', 'tunic', 'gloves', 'leggings', 'shield', 'boots']
    ITEMDESC = {
        'ring': 'ring',
        'amulet': 'amulet',
        'charm': 'charm',
        'weapon': 'weapon',
        'helm': 'helm',
        'tunic': 'tunic',
        'shield': 'shield',
        'gloves': 'pair of gloves',
        'leggings': 'set of leggings',
        'boots': 'pair of boots'
    }

    @classmethod
    def from_dict(cls, d):
        """Returns a player with its values set to the dict's."""
        p = cls()
        for k,v in d.items():
            setattr(p, k, v)
        return p

    @staticmethod
    def new_player(pname, pclass, ppass, nextlvl):
        """Initialize a new player."""
        now = int(time.time())
        p = Player()
        # name of account
        p.name = pname
        # name of character class - affects nothing
        p.cclass = pclass
        # hashed password
        p.set_password(ppass)
        # admin bit
        p.isadmin = False
        # level
        p.level = 0
        # time in seconds to next level
        p.nextlvl = nextlvl
        # whether or not the account is online
        p.online = False
        # IRC nick if online
        p.nick = ""
        # Userhost if online - used to automatically log players back in
        p.userhost = ""
        # total seconds idled
        p.idled = 0
        # X position on map
        p.posx = 0
        # Y position on map
        p.posy = 0
        # Total penalties from messaging
        p.penmessage = 0
        # Total penalties from changing nicks
        p.pennick = 0
        # Total penalties from leaving the channel
        p.penpart = 0
        # Total penalties from being kicked
        p.penkick = 0
        # Total penalties from quitting
        p.penquit = 0
        # Total penalties from dropping connection
        p.pendropped = 0
        # Total penalties from losing quests
        p.penquest = 0
        # Total penalties from using the logout command
        p.penlogout = 0
        # Time created
        p.created = now
        # Last time logged in
        p.lastlogin = now
        # Character alignment - should only be n, g, or e
        p.alignment = "n"
        # Items and their names.  Named items are only rarely granted.
        p.amulet = 0
        p.amuletname = ''
        p.charm = 0
        p.charmname = ''
        p.helm = 0
        p.helmname = ''
        p.boots = 0
        p.bootsname = ''
        p.gloves = 0
        p.glovesname = ''
        p.ring = 0
        p.ringname = ''
        p.leggings = 0
        p.leggingsname = ''
        p.shield = 0
        p.shieldname = ''
        p.tunic = 0
        p.tunicname = ''
        p.weapon = 0
        p.weaponname = ''
        return p


    def set_password(self, ppass):
        """Sets the password field with a hashed value."""
        self.pw = crypt.crypt(ppass, crypt.mksalt())


    def acquire_item(self, kind, level, name=''):
        """Acquire an item."""
        setattr(self, kind, level)
        setattr(self, kind+"name", name)


    def swap_items(self, o, kind):
        """Swap items of KIND with the other player O."""
        namefield = kind+"name"
        tmpitem = getattr(self, kind)
        tmpitemname = getattr(self, namefield)
        self.acquire_item(kind, getattr(o, kind), getattr(o, namefield))
        o.acquire_item(kind, tmpitem, tmpitemname)


    def itemsum(self):
        """Add up the power of all the player's items"""
        return sum([getattr(self, item) for item in Player.ITEMS])


    def battleitemsum(self):
        """
        Add up item power for battle.

        Good players get a boost, and evil players get a penalty.
        """
        sum = self.itemsum()
        if self.alignment == 'e':
            return int(sum * conf["evil_battle_pct"]/100)
        if self.alignment == 'g':
            return int(sum * conf["good_battle_pct"]/100)
        return sum


class PlayerStore(object):
    """Interface for a PlayerDB backend."""

    def create(self):
        pass

    def exists(self):
        pass

    def backup(self):
        pass

    def readall(self):
        pass

    def writeall(self, players):
        pass

    def close(self):
        pass

    def new(self, player):
        pass

    def rename(self, old, new):
        pass

    def delete(self, pname):
        pass


class IdleRPGPlayerStore(PlayerStore):
    """Implements a PlayerStore compatible with the IdleRPG db."""

    IRPG_FIELDS = ["username", "pass", "is admin", "level", "class", "next ttl", "nick", "userhost", "online", "idled", "x pos", "y pos", "pen_mesg", "pen_nick", "pen_part", "pen_kick", "pen_quit", "pen_quest", "pen_logout", "created", "last login", "amulet", "charm", "helm", "boots", "gloves", "ring", "leggings", "shield", "tunic", "weapon", "alignment"]
    IRPG_FIELD_COUNT = len(IRPG_FIELDS)

    # Instead of names, idlerpg decided to tack on codes to the number.
    ITEMCODES = {
        "Mattt's Omniscience Grand Crown":"a",
        "Juliet's Glorious Ring of Sparkliness":"h",
        "Res0's Protectorate Plate Mail":"b",
        "Dwyn's Storm Magic Amulet":"c",
        "Jotun's Fury Colossal Sword":"d",
        "Drdink's Cane of Blind Rage":"e",
        "Mrquick's Magical Boots of Swiftness":"f",
        "Jeff's Cluehammer of Doom":"g"
    }

    def _code_to_item(self, s):
        """Converts an IdleRPG item code to a tuple of (level, name)."""
        match = re.match(r"(\d+)(.?)", s)
        if not match:
            log.error(f"invalid item code: {s}")
        lvl = int(match[1])
        if match[2]:
            return (lvl, [k for k,v in IdleRPGPlayerStore.ITEMCODES.items() if v == match[2]][0])
        return (lvl, "")


    def _item_to_code(self, level, name):
        """Converts an item level and name to an IdleRPG item code."""
        return f"{level}{IdleRPGPlayerStore.ITEMCODES.get(name, '')}"


    def __init__(self, dbpath):
        self._dbpath = dbpath


    def create(self):
        """Creates a new IdleRPG db."""
        self.writeall({})


    def exists(self):
        """Returns true if the db file exists."""
        return os.path.exists(self._dbpath)


    def backup(self):
        """Backs up database to a directory."""
        os.makedirs(datapath(conf["backupdir"]), exist_ok=True)
        backup_path = os.path.join(datapath(conf["backupdir"]),
                                   f"{time.strftime('%Y-%m-%dT%H:%M:%S')}-{conf['dbfile']}")
        shutil.copyfile(self._dbpath, backup_path)


    def readall(self):
        """Reads all the players into memory."""
        players = {}
        with open(self._dbpath) as inf:
            for line in inf.readlines():
                if re.match(r'\s*(?:#|$)', line):
                    continue
                parts = line.rstrip().split("\t")
                if len(parts) != IdleRPGPlayerStore.IRPG_FIELD_COUNT:
                    log.critical("line corrupt in player db - %d fields: %s", len(parts), repr(line))
                    sys.exit(-1)

                # This makes a mapping from irpg field to player field.
                d = dict(zip(["name", "pw", "isadmin", "level", "cclass", "nextlvl", "nick", "userhost", "online", "idled", "posx", "posy", "penmessage", "pennick", "penpart", "penkick", "penquit", "penquest", "penlogout", "created", "lastlogin", "amulet", "charm", "helm", "boots", "gloves", "ring", "leggings", "shield", "tunic", "weapon", "alignment"], parts))
                # convert items
                for i in Player.ITEMS:
                    d[i], d[i+'name'] = self._code_to_item(d[i])
                # convert int fields
                for f in ["level", "nextlvl", "idled", "posx", "posy", "penmessage", "pennick", "penpart", "penkick", "penquit", "penquest", "penlogout", "created", "lastlogin"]:
                    d[f] = round(float(d[f]))
                # convert boolean fields
                for f in ["isadmin", "online"]:
                    d[f] = (d[f] == '1')

                d['pendropped'] = 0 # unsupported in saving
                p = Player.from_dict(d)
                players[p.name] = p
        return players


    def _player_to_record(self, p):
        """Converts the player to an IdleRPG db record."""
        return "\t".join([
            p.name,
            p.pw,
            "1" if p.isadmin else "0",
            str(p.level),
            p.cclass,
            str(p.nextlvl),
            p.nick,
            p.userhost,
            "1" if p.online else "0",
            str(p.idled),
            str(p.posx),
            str(p.posy),
            str(p.penmessage),
            str(p.pennick),
            str(p.penpart),
            str(p.penkick),
            str(p.penquit + p.pendropped),
            str(p.penquest),
            str(p.penlogout),
            str(int(p.created)),
            str(int(p.lastlogin)),
            self._item_to_code(p.amulet, p.amuletname),
            self._item_to_code(p.charm, p.charmname),
            self._item_to_code(p.helm, p.helmname),
            self._item_to_code(p.boots, p.bootsname),
            self._item_to_code(p.gloves, p.glovesname),
            self._item_to_code(p.ring, p.ringname),
            self._item_to_code(p.leggings, p.leggingsname),
            self._item_to_code(p.shield, p.shieldname),
            self._item_to_code(p.tunic, p.tunicname),
            self._item_to_code(p.weapon, p.weaponname),
            str(p.alignment)
        ]) + "\n"


    def writeall(self, players):
        """Writes all players to an IdleRPG db."""
        with open(self._dbpath, "w") as ouf:
            ouf.write("# " + "\t".join(IdleRPGPlayerStore.IRPG_FIELDS) + "\n")
            for p in players.values():
                ouf.write(self._player_to_record(p))


    def new(self, p):
        """Creates a new player in the db."""
        with open(self._dbpath, "a") as ouf:
            ouf.write(self._player_to_record(p))


    def rename(self, old_name, new_name):
        """Renames a player in the db."""
        players = self.readall()
        players[new_name] = players[old_name]
        del players[old_name]
        self.writeall(players)


    def delete(self, pname):
        """Removes a player from the db."""
        players = self.readall()
        players.pop(pname, None)
        self.writeall(players)


class Sqlite3PlayerStore(PlayerStore):
    """Player store using sqlite3."""

    FIELDS = ["name", "cclass", "pw", "isadmin", "level", "nextlvl", "nick", "userhost", "online", "idled", "posx", "posy", "penmessage", "pennick", "penpart", "penkick", "penquit", "pendropped", "penquest", "penlogout", "created", "lastlogin", "alignment", "amulet", "amuletname", "charm", "charmname", "helm", "helmname", "boots", "bootsname", "gloves", "glovesname", "ring", "ringname", "leggings", "leggingsname", "shield", "shieldname", "tunic", "tunicname", "weapon", "weaponname"]


    @staticmethod
    def dict_factory(cursor, row):
        """Converts a sqlite3 row into a dict."""
        d = {}
        for idx, col in enumerate(cursor.description):
            d[col[0]] = row[idx]
        return d


    def _connect(self):
        """Connects to the sqlite3 db if not already connected."""
        if self._db is None:
            self._db = sqlite3.connect(self._dbpath)
            self._db.row_factory = Sqlite3PlayerStore.dict_factory

        return self._db


    def __init__(self, dbpath):
        self._dbpath = dbpath
        self._db = None


    def create(self):
        """Initializes a new db."""
        with self._connect() as cur:
            cur.execute(f"create table players ({','.join(Sqlite3PlayerStore.FIELDS)})")


    def exists(self):
        """Returns True if the db exists."""
        return os.path.exists(self._dbpath)


    def backup(self):
        """Backs up database to a directory."""
        os.makedirs(datapath(conf["backupdir"]), exist_ok=True)
        with self._connect() as con:
            backup_path = os.path.join(datapath(conf["backupdir"]),
                                       f"{time.strftime('%Y-%m-%dT%H:%M:%S')}-{conf['dbfile']}")
            backup_db = sqlite3.connect(backup_path)
            with backup_db:
                self._db.backup(backup_db)
            backup_db.close()


    def readall(self):
        """Reads all the players from the db."""
        players = {}
        with self._connect() as con:
            cur = con.execute("select * from players")
            for d in cur.fetchall():
                players[d['name']] = Player.from_dict(d)
        return players


    def writeall(self, players):
        """Writes all player information into the db."""
        with self._connect() as cur:
            update_fields = ",".join(f"{k}=:{k}" for k in Sqlite3PlayerStore.FIELDS)
            cur.executemany(f"update players set {update_fields} where name=:name",
                            [vars(p) for p in players.values()])


    def close(self):
        """Finish using db."""
        self._db.close()


    def new(self, p):
        """Create new character in db."""
        with self._connect() as cur:
            d = vars(p)
            cur.execute(f"insert into players values ({('?, ' * len(d))[:-2]})",
                        [d[k] for k in Sqlite3PlayerStore.FIELDS])
            cur.commit()


    def rename(self):
        """Rename player in db."""
        with self._connect() as cur:
            cur.execute("update players set name = ? where name = ?", (new_name, old_name))
            cur.commit()


    def delete(self):
        """Remove player from db."""
        with self._connect() as cur:
            cur.execute("delete from players where name = ?", (pname,))
            cur.commit()


class PlayerDB(object):
    """Class to manage a collection of Players."""

    def __init__(self, store):
        self._store = store
        self._players = {}

    def __getitem__(self, pname):
        """Return a player by name."""
        return self._players[pname]


    def __contains__(self, pname):
        """Returns True if the player is in the db."""
        return pname in self._players


    def close(self):
        """Close the underlying db.  Used for testing."""
        self._store.close()


    def exists(self):
        """Returns True if the underlying store exists."""
        return self._store.exists()


    def backup_store(self):
        """Backup store into another file."""
        self._store.backup()


    def load(self):
        """Load all players from database into memory"""
        self._players = self._store.readall()


    def write(self):
        """Write all players into database"""
        self._store.writeall(self._players)


    def create(self):
        """Creates a new database from scratch."""
        self._store.create()


    def new_player(self, pname, pclass, ppass):
        """Create a new player with the name, class, and password."""
        global conf

        if pname in self._players:
            raise KeyError

        p = Player.new_player(pname, pclass, ppass, conf['rpbase'])
        self._players[pname] = p
        self._store.new(p)

        return p


    def rename_player(self, old_name, new_name):
        """Rename a player in the db."""
        self._players[new_name] = self._players[old_name]
        self._players[new_name].name = new_name
        self._players.pop(old_name, None)
        self._store.rename(old_name, new_name)


    def delete_player(self, pname):
        """Remove a player from the db."""
        self._players.pop(pname)
        self._store.delete(pname)


    def from_nick(self, nick):
        """Find the given online player with the nick."""
        for p in self._players.values():
            if p.online and p.nick == nick:
                return p
        return None


    def check_login(self, pname, ppass):
        """Return True if name and password are a valid login."""
        result = (pname in self._players)
        result = result and compare_hash(self._players[pname].pw, crypt.crypt(ppass, self._players[pname].pw))
        return result


    def count(self):
        """Return number of all players registered."""
        return len(self._players)


    def online(self):
        """Return all active, online players."""
        return [p for p in self._players.values() if p.online]


    def max_player_power(self):
        """Return the itemsum of the most powerful player."""
        return max([p.itemsum() for p in self._players.values()])


    def top_players(self):
        """Return the top three players."""
        s = sorted(self._players.values(), key=attrgetter('level'))
        return sorted(s, key=attrgetter('nextlvl'), reverse=True)[:3]


    def inactive_since(self, expire):
        """Return all players that have been inactive since a point in time."""
        return [p for p in self._players.values() if not p.online and p.lastlogin < expire]


def first_setup():
    """Perform initialization of game."""
    global conf
    global db

    if db.exists():
        return
    pname = input(f"{datapath(conf['dbfile'])} does not appear to exist.  I'm guessing this is your first time using DawdleRPG. Please give an account name that you would like to have admin access [{conf['owner']}]: ")
    if pname == "":
        pname = conf["owner"]
    pclass = input("Enter a character class for this account: ")
    pclass = pclass[:conf["max_class_len"]]
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

    print(f"OK, wrote you into {datapath(conf['dbfile'])}")


class IRCClient:
    """IRCClient acts as a layer between the IRC protocol and the bot protocol.

    This class has the following responsibilities:
    - Connection and disconnection
    - Nick recovery
    - Output throttling
    - NickServ authentication
    - IRC message decoding and parsing
    - Tracking users in the channel
    - Calling methods on the bot interface
 """
    MESSAGE_RE = re.compile(r'^(?:@(\S*) )?(?::([^ !]*)(?:!([^ @]*)(?:@([^ ]*))?)?\s+)?(\S+)\s*((?:[^:]\S*(?:\s+|$))*)(?::(.*))?')

    Message = collections.namedtuple('Message', ['tags', 'src', 'user', 'host', 'cmd', 'args', 'trailing', 'line', 'time'])


    class User:
        """An IRC user in the channel."""

        def __init__(self, nick, userhost, modes, joined):
            self.nick = nick
            self.userhost = userhost
            self.modes = set(modes)
            self.joined = joined


    def __init__(self, bot):
        self._bot = bot
        self._writer = None
        self._nick = conf['botnick']
        self._bytes_sent = 0
        self._bytes_received = 0
        self._caps = set()
        self.quitting = False


    async def connect(self, addr, port):
        """Connect to IRC network and handle messages."""
        reader, self._writer = await asyncio.open_connection(addr, port, ssl=True, local_addr=conf.get("localaddr"))
        self._server = addr
        self._connected = True
        self._messages_sent = 0
        self._writeq = []
        self._flushq_task = None
        self._prefixmodes = {}
        self._maxmodes = 3
        self._modetypes = {}
        self._users = {}
        self._caps = set()             # all enabled capabilities
        self.sendnow("CAP REQ :multi-prefix userhost-in-names")
        self.sendnow("CAP END")
        if 'BOTPASS' in os.environ:
            self.sendnow(f"PASS {os.environ['BOTPASS']}")
        self.sendnow(f"NICK {conf['botnick']}")
        self.sendnow(f"USER {conf['botuser']} 0 * :{conf['botrlnm']}")
        self._bot.connected(self)
        while True:
            line = await reader.readline()
            if not line:
                if self._flushq_task:
                    self._flushq_task.cancel()
                self._bot.disconnected()
                break
            self._bytes_received += len(line)
            # Assume utf-8 encoding, fall back to latin-1, which has no invalid encodings from bytes.
            try:
                line = str(line, encoding='utf8')
            except UnicodeDecodeError:
                line = str(line, encoding='latin-1')
            line = line.rstrip('\r\n')
            loglevel = logging.SPAMMY if re.match(r"^PING ", line) else logging.DEBUG
            log.log(loglevel, "<- %s", line)
            msg = self.parse_message(line)
            self.dispatch(msg)


    def send(self, s, loglevel=logging.DEBUG):
        """Send throttled messages."""
        b = bytes(s+"\r\n", encoding='utf8')

        if not conf["throttle"]:
            log.log(loglevel, "-> %s", s)
            self._writer.write(b)
            self._bytes_sent += len(b)
            return

        if self._messages_sent < conf["throttle_rate"]:
            log.log(loglevel, "(%d)-> %s", self._messages_sent, s)
            self._writer.write(b)
            self._messages_sent += 1
            self._bytes_sent += len(b)
        else:
            self._writeq.append(b)

        # The flushq task will reset messages_sent after the throttle period.
        if not self._flushq_task:
            self._flushq_task = asyncio.create_task(self.flushq_task())


    def sendnow(self, s, loglevel=logging.DEBUG):
        """Send messages ignoring throttle."""
        log.log(loglevel, "=> %s", s)
        b = bytes(s+"\r\n", encoding='utf8')
        self._writer.write(b)
        self._messages_sent += 1
        self._bytes_sent += len(b)
        if conf["throttle"] and not self._flushq_task:
            self._flushq_task = asyncio.create_task(self.flushq_task())


    async def flushq_task(self):
        """Flush send queue and release throttle."""
        await asyncio.sleep(THROTTLE_PERIOD)
        self._messages_sent = max(0, self._messages_sent - conf["throttle_rate"])
        while self._writeq:
            while self._writeq and self._messages_sent < conf["throttle_rate"]:
                log.debug("(%d)~> %s", self._messages_sent, str(self._writeq[0], encoding='utf8').rstrip())
                self._writer.write(self._writeq[0])
                self._messages_sent += 1
                self._bytes_sent += len(self._writeq[0])
                self._writeq = self._writeq[1:]
            if self._writeq:
                await asyncio.sleep(conf["throttle_period"])
                self._messages_sent = max(0, self._messages_sent - conf["throttle_rate"])

        self._flushq_task = None


    def parse_message(self, line):
        """Parse IRC line into a Message."""
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
        if trailing is not None:
            args.append(trailing)
        # Numeric responses specify a useless target afterwards
        if re.match(r'\d+', cmd):
            args = args[1:]
        # Support time tag, which allows servers and bouncers to send history
        if 'time' in tags:
            msgtime = time.mktime(time.strptime(tags['time'], "%Y-%m-%dT%H:%M:%S"))
        else:
            msgtime = time.time()
        return IRCClient.Message(tags, src, user, host, cmd, args, trailing, line, msgtime)


    def dispatch(self, msg):
        """Dispatch the IRC command to a handler method."""
        if hasattr(self, "handle_"+msg.cmd.lower()):
            getattr(self, "handle_"+msg.cmd.lower())(msg)


    def handle_ping(self, msg):
        """PING - sends PONG back to server for keepalive."""
        self.sendnow(f"PONG :{msg.trailing}", loglevel=logging.SPAMMY)


    def handle_005(self, msg):
        """RPL_ISUPPORT - server features and information"""
        self._server = msg.src
        params = dict([arg.split('=') if '=' in arg else (arg, arg) for arg in msg.args])
        if 'MODES' in params:
            self._maxmodes = int(params['MODES'])
        if 'PREFIX' in params:
            m = re.match(r'\(([^)]*)\)(.*)', params['PREFIX'])
            if m:
                self._prefixmodes.update(zip(m[2], m[1]))
                for mode in m[1]:
                    self._modetypes[mode] = 2
        if 'CHANMODES' in params:
            m = re.match(r'([^,]*),([^,]*),([^,]*),(.*)', params['CHANMODES'])
            if m:
                for mode in m[1]:
                    self._modetypes[mode] = 1 # adds to a list and always has a parameter
                for mode in m[2]:
                    self._modetypes[mode] = 2 # changes a setting and always has param
                for mode in m[3]:
                    self._modetypes[mode] = 3 # only has a parameter when set
                for mode in m[4]:
                    self._modetypes[mode] = 4 # never has a parameter


    def handle_376(self, msg):
        """RPL_ENDOFMOTD - server is ready"""
        self.mode(conf['botnick'], conf['botmodes'])
        self.join(conf['botchan'])


    def handle_422(self, msg):
        """ERR_NOTMOTD - server is ready, but without a MOTD"""
        self.mode(conf['botnick'], conf['botmodes'])
        self.join(conf['botchan'])


    def handle_352(self, msg):
        """RPL_WHOREPLY - Response to WHO command"""
        self.add_user(msg.args[4],
                      f"{msg.src}!{msg.args[1]}@{msg.args[2]}",
                      [self._prefixmodes[p] for p in msg.args[5][1:]], # Format is [GH]\S*
                      msg.time)


    def handle_315(self, msg):
        """RPL_ENDOFWHO - End of WHO command response"""
        self._bot.ready()


    def handle_353(self, msg):
        """RPL_NAMREPLY - names in the channel"""
        if 'userhost-in-names' not in self._caps:
            return
        prefixes=''.join(self._prefixmodes.keys())
        userhost_re = re.compile(f"([{prefixes}]*)" + r"((\S+)!\S+@\S+)")
        for u in msg.trailing.split(' '):
            m = userhost_re.match(u)
            if m:
                self.add_user(m[3], m[2], [self._prefixmodes[p] for p in m[1]], msg.time)


    def handle_366(self, msg):
        """RPL_ENDOFNAMES - the actual end of channel joining"""
        # We know who is in the channel now
        if 'botopcmd' in conf:
            self.sendnow(re.sub(r'%botnick%', self._nick, conf['botopcmd']))
        if 'userhost-in-names' in self._caps:
            self._bot.ready()
        else:
            self.send(f"WHO {conf['botchan']}")


    def handle_433(self, msg):
        """ERR_NICKNAME_IN_USE - try another nick"""
        self._nick = self._nick + "0"
        self.nick(self._nick)
        if 'botghostcmd' in conf:
            self.send(conf['botghostcmd'])


    def handle_cap(self, msg):
        """CAP - notification of capability"""
        # We only care about enabled capabilities.
        if msg.args[1] == "ACK":
            self._caps.update(msg.args[2].split(' '))


    def handle_join(self, msg):
        """JOIN - bot or user joined the channel."""
        self.add_user(msg.src, f"{msg.src}!{msg.user}@{msg.host}", [], msg.time)


    def handle_part(self, msg):
        """PART - bot or user left the channel."""
        self.remove_user(msg.src)
        self._bot.nick_parted(msg.src)


    def handle_kick(self, msg):
        """KICK - user was kicked from the channel."""
        self.remove_user(msg.args[1])
        self._bot.nick_kicked(msg.args[1])


    def handle_mode(self, msg):
        """MODE - bot or channel changed its mode."""
        # ignore mode changes to everything except the bot channel
        if msg.args[0] != conf['botchan']:
            return
        changes = []
        params = []
        for arg in msg.args[1:]:
            m = re.match(r'([-+])(.*)', arg)
            if m:
                changes.extend([(m[1], term) for term in m[2]])
            else:
                params.append(arg)
        for change in changes:
            # all this modetype machinery is required to accurately parse modelines
            modetype = self._modetypes[change[1]]
            if modetype == 1 or modetype == 2 or (modetype == 3 and change[0] == '+'):
                param = params.pop()
                if modetype != 2:
                    continue
                if change[0] == '+':
                    self._users[param].modes.add(change[1])
                    if param == self._nick and change[1] == 'o':
                        # Acquiring op is special to the bot
                        self._bot.acquired_ops()
                else:
                    self._users[param].modes.discard(change[1])


    def handle_nick(self, msg):
        """NICK - bot or user had its nick changed."""
        self._users[msg.args[0]] = self._users[msg.src]
        self._users[msg.args[0]].nick = msg.args[0]
        del self._users[msg.src]

        if msg.src == self._nick:
            # Update my nick
            self._nick = msg.args[0]
            return

        # Notify bot if another user's nick changed
        self._bot.nick_changed(self, msg.src, msg.args[0])

        if msg.src == conf['botnick']:
            # Grab my nick that someone left
            self.nick(conf['botnick'])


    def handle_quit(self, msg):
        """QUIT - bot or user was disconnected."""
        if msg.src == conf['botnick']:
            # Grab my nick that someone left
            self.nick(conf['botnick'])
        self.remove_user(msg.src)
        if conf['detectsplits'] and re.match(r'\S+\.\S+ \S+\.\S+', msg.trailing):
            # Don't penalize on netsplit
            self._bot.netsplit(msg.src)
        elif re.match(r"Read error|Ping timeout", msg.trailing):
            self._bot.nick_dropped(msg.src)
        else:
            self._bot.nick_quit(msg.src)


    def handle_notice(self, msg):
        """NOTICE - Message sent, used to prevent loops in bots."""
        if msg.args[0] != self._nick and self.user_is_ok(msg):
            # we ignore private notices
            self._bot.channel_notice(msg.src, msg.trailing)


    def handle_privmsg(self, msg):
        """PRIVMSG - Message sent."""
        if msg.args[0] == self._nick:
            self._bot.private_message(msg.src, msg.trailing)
        elif self.user_is_ok(msg):
            self._bot.channel_message(msg.src, msg.trailing)


    def add_user(self, nick, userhost, modes, joined):
        self._users[nick] = IRCClient.User(nick, userhost, modes, joined)


    def remove_user(self, nick):
        del self._users[nick]
        if len(self._users) == 1 and not self.bot_has_ops():
            # Try to acquire ops by leaving and joining
            self.sendnow(f"PART {conf['botchan']} :Acquiring ops")
            self.sendnow(f"JOIN {conf['botchan']}")


    def user_is_ok(self, msg):
        """Check to see if msg should cause user to be kickbanned."""
        if not conf["doban"]:
            # Bot doesn't do bans
            return True
        if not self.bot_has_ops():
            # Bot can't do bans
            return True
        if msg.src == self._nick:
            # Bot is always ok
            return True
        if msg.src not in self._users:
            # Not in channel - maybe channel could use mode +n
            return False
        if msg.time > self._users[msg.src].joined + conf["bannable_time"]:
            # Been in channel for a while, prob ok?
            return True

        for host in re.findall(r"https?://([^/]+)/", msg.trailing):
            if host not in conf["okurls"]:
                # User not okay
                self.kickban(msg.src)
                return False
        return True


    def match_user(self, nick, userhost):
        """Return True if the nick and userhost match an existing user."""
        return (nick in self._users and userhost == self._users[nick].userhost)


    def bot_has_ops(self):
        """Return True if the bot has ops in the channel."""
        return (self._nick in self._users and 'o' in self._users[self._nick].modes)


    def kickban(self, nick):
        """Kick a nick from the channel and ban them."""
        self.sendnow(f"MODE {conf['botchan']} +b {nick}")
        self.sendnow(f"KICK {conf['botchan']} {nick} :No advertising")


    def nick(self, nick):
        """Send nick change request."""
        self.sendnow(f"NICK {nick}")


    def join(self, channel):
        """Send channel join request."""
        self.sendnow(f"JOIN {channel}")


    def notice(self, target, text):
        """Send notice text to target."""
        for line in textwrap.wrap(text, width=conf["message_wrap_len"]):
            self.send(f"NOTICE {target} :{line}")


    def grant_voice(self, *targets):
        for subset in grouper(targets, self._maxmodes):
            self.send(f"MODE {conf['botchan']} +{'v' * len(subset)} {' '.join(subset)}")


    def revoke_voice(self, *targets):
        for subset in grouper(targets, self._maxmodes):
            self.send(f"MODE {conf['botchan']} -{'v' * len(subset)} {' '.join(subset)}")


    def mode(self, target, *modeinfo):
        """Send mode change request."""
        for modes in grouper(modeinfo, self._maxmodes):
            self.send(f"MODE {target} {' '.join(modes)}")


    def chanmsg(self, text):
        """Send message text to bot channel."""
        for line in textwrap.wrap(text, width=conf["message_wrap_len"]):
            self.send(f"PRIVMSG {conf['botchan']} :{line}")


    def quit(self, *text):
        """Send quit request to server."""
        self.quitting = True
        if text:
            self.sendnow(f"QUIT :{text}")
        else:
            self.sendnow("QUIT")


# SpecialItem is a configuration tuple for specifying special items.
SpecialItem = collections.namedtuple('SpecialItem', ['minlvl', 'itemlvl', 'lvlspread', 'kind', 'name', 'flavor'])


class Quest(object):
    """Class for tracking quests."""
    def __init__(self, qp):
        self.questors = qp
        self.mode = None
        self.text = None
        self.qtime = None
        self.dests = []


class DawdleBot(object):
    """Class implementing the game."""

    # Commands in ALLOWALL can be used by anyone.
    # Commands in ALLOWPLAYERS can only be used by logged-in players
    # All other commands are admin-only
    ALLOWALL = ["help", "info", "login", "register", "quest", "version"]
    ALLOWPLAYERS = ["align", "logout", "newpass", "removeme", "status", "whoami"]
    CMDHELP = {
        "help": "help [<command>] - Display help on commands.",
        "login": "login <account> <password> - Login to your account.",
        "register": "register <account> <password> <character class> - Create a new character.",
        "quest": "quest - Display the current quest, if any.",
        "version": "Display the version of the bot.",
        "align": "align good|neutral|evil - Change your character's alignment.",
        "logout": "logout - Log out of your account.  You will be penalized!",
        "newpass": "newpass <old password> <new password> - Change your account's password.",
        "removeme": "removeme <password> - Delete your character.",
        "status": "status - Show bot status.",
        "whoami": "whoami - Shows who you are logged in as.",
        "announce": "announce - Sends a message to the channel.",
        "backup": "backup - Backup the player db.",
        "chclass": "chclass <account> <new class> - Change the character class of the account.",
        "chpass": "chpass <account> <new password> - Change the password of the account.",
        "chuser": "chuser <account> <new name> - Change the name of the account.",
        "clearq": "clearq - Clear the sending queue of the bot.",
        "del": "del <account> - Delete the account.",
        "deladmin": "deladmin <account> - Remove admin privileges from account.",
        "delold": "delold <# of days> - Remove all accounts older than a number of days.",
        "die": "die - Shut down the bot.",
        "jump": "jump <server> - Switch to a different IRC server.",
        "mkadmin": "mkadmin <account> - Grant admin privileges to the account.",
        "pause": "pause - Toggle pause mode.",
        "rehash": "rehash - Not sure.",
        "reloaddb": "reloaddb - Reload the player database.",
        "restart": "restart - Restarts the bot.",
        "silent": "silent <mode> - Sets silentmode to the given mode.",
        "hog": "hog - Triggers the Hand of God.",
        "push": "push <account> <seconds> - Adds seconds to the next level of account.",
        "trigger": "trigger calamity|godsend|hog|teambattle|evilness|goodness|battle: Triggers the event."
    }

    def __init__(self, db):
        self._irc = None             # irc connection
        self._players = db           # the player database
        self._state = 'disconnected' # connected, disconnected, or ready
        self._quest = None           # quest if any
        self._qtimer = 0             # time until next quest
        self._silence = set() # can have 'chanmsg' or 'notice' to silence them
        self._pause = False # prevents game events from happening when True
        self._last_reg_time = 0
        self._events = {}       # pre-parsed contents of events file
        self._events_loaded = 0 # time the events file was loaded, to detect file changes
        self._new_accounts = 0  # number of new accounts created since startup
        self._overrides = {}


    def randomly(self, key, odds):
        """Overrideable random func which returns true at 1:ODDS odds."""
        if key in self._overrides:
            return self._overrides[key]
        return random.randint(0, odds-1) < 1


    def randint(self, key, bottom, top):
        """Overrideable random func which returns an integer bottom <= i <= top."""
        if key in self._overrides:
            return self._overrides[key]
        return random.randint(bottom, top)


    def randsample(self, key, seq, count):
        """Overrideable random func which returns random COUNT elements of SEQ."""
        if key in self._overrides:
            return self._overrides[key]
        return random.sample(seq, count)


    def randchoice(self, key, seq):
        """Overrideable random func which returns one random element of SEQ."""
        if key in self._overrides:
            return self._overrides[key]
        return random.choice(seq)


    def randshuffle(self, key, seq):
        """Overrideable random func which does an in-place shuffle of SEQ."""
        if key in self._overrides:
            return self._overrides[key]
        random.shuffle(seq)


    def connected(self, irc):
        """Called when connected to IRC."""
        self._irc = irc
        self._state = 'connected'


    def chanmsg(self, text):
        """Send a message to the bot channel."""
        if 'chanmsgs' in self._silence:
            return
        self._irc.chanmsg(text)


    def logchanmsg(self, text):
        """Send a message to the bot channel and log it to the modsfile."""
        if 'chanmsgs' in self._silence:
            return
        self._irc.chanmsg(text)
        # strip color codes for saving to file.
        text = re.sub(r"\x0f|\x03\d\d?(?:,\d\d?)?", "", text)
        with open(datapath(conf['modsfile']), "a") as ouf:
            ouf.write(f"[{time.strftime('%m/%d/%y %H:%M:%S')}] {text}\n")


    def notice(self, nick, text):
        """Send a notice to a given nick."""
        if 'notices' in self._silence:
            return
        self._irc.notice(nick, text)


    def ready(self):
        """Called when bot has finished joining channel."""
        self._state = 'ready'
        self.refresh_events()
        autologin = []
        for p in self._players.online():
            if self._irc.match_user(p.nick, p.userhost):
                autologin.append(p.name)
            else:
                p.online = False
                p.lastlogin = time.time()
        self._players.write()
        if autologin:
            self.chanmsg(f"{len(autologin)} user{plural(len(autologin))} automatically logged in; accounts: {', '.join(autologin)}")
            if self._irc.bot_has_ops():
                self.acquired_ops()
        else:
            self.chanmsg("0 users qualified for auto login.")
        self._gametick_task = asyncio.create_task(self.gametick_loop())
        self._qtimer = time.time() + self.randint('qtimer_init',
                                                  conf["quest_interval_min"],
                                                  conf["quest_interval_max"])


    def acquired_ops(self):
        """Called when the bot has acquired ops status on the channel."""
        if not conf['voiceonlogin'] or self._state != 'ready':
            return

        online_nicks = set([p.nick for p in self._players.online()])
        add_voice = []
        remove_voice = []
        for u in self._irc._users.keys():
            if 'v' in self._irc._users[u].modes:
                if u not in online_nicks:
                    remove_voice.append(u)
            else:
                if u in online_nicks:
                    add_voice.append(u)
        if add_voice:
            self._irc.grant_voice(*add_voice)
        if remove_voice:
            self._irc.revoke_voice(*remove_voice)


    def disconnected(self):
        """Called when the bot has been disconnected."""
        self._irc = None
        self._state = 'disconnected'
        if self._gametick_task:
            self._gametick_task.cancel()
            self._gametick_task = None


    def private_message(self, src, text):
        """Called when private message received."""
        if text == '':
            return
        if self._state != "ready":
            self.notice(src, "The bot isn't ready yet.")
            return

        parts = text.split(' ', 1)
        cmd = parts[0].lower()
        if len(parts) == 2:
            args = parts[1]
        else:
            args = ''
        player = self._players.from_nick(src)
        if cmd in DawdleBot.ALLOWPLAYERS:
            if not player:
                self.notice(src, "You are not logged in.")
                return
        elif cmd not in DawdleBot.ALLOWALL:
            if player is None or not player.isadmin:
                self.notice(src, f"You cannot do '{cmd}'.")
                return
        if hasattr(self, f'cmd_{cmd}'):
            getattr(self, f'cmd_{cmd}')(player, src, args)
        else:
            self.notice(src, f"'{cmd} isn't actually a command.")


    def channel_message(self, src, text):
        """Called when channel message received."""
        player = self._players.from_nick(src)
        if player:
            self.penalize(player, "message", text)


    def channel_notice(self, src, text):
        """Called when channel notice received."""
        player = self._players.from_nick(src)
        if player:
            self.penalize(player, "message", text)


    def nick_changed(self, old_nick, new_nick):
        """Called when someone on channel changed nick."""
        player = self._players.from_nick(old_nick)
        if player:
            player.nick = new_nick
            self.penalize(player, "nick")


    def nick_parted(self, src):
        """Called when someone left the channel."""
        player = self._players.from_nick(src)
        if player:
            self.penalize(player, "part")
            player.online = False
            player.lastlogin = time.time()
            self._players.write()


    def netsplit(self, src):
        """Called when someone was netsplit."""
        player = self._players.from_nick(src)
        if player:
            player.lastlogin = time.time()


    def nick_dropped(self, src):
        """Called when someone was disconnected."""
        player = self._players.from_nick(src)
        if player:
            player.lastlogin = time.time()


    def nick_quit(self, src):
        """Called when someone quit IRC intentionally."""
        player = self._players.from_nick(src)
        if player:
            self.penalize(player, "quit")
            player.online = False
            player.lastlogin = time.time()
            self._players.write()


    def nick_kicked(self, target):
        """Called when someone was kicked."""
        player = self._players.from_nick(target)
        if player:
            self.penalize(player, "kick")
            player.online = False
            player.lastlogin = time.time()
            self._players.write()


    def cmd_align(self, player, nick, args):
        """change alignment of character."""
        if args not in ["good", "neutral", "evil"]:
            self.notice(nick, "Try: ALIGN good|neutral|evil")
            return
        player.alignment = args[0]
        self.notice(nick, f"You have converted to {args}")
        self._players.write()


    def cmd_help(self, player, nick, args):
        """get help."""
        if args:
            if args in DawdleBot.CMDHELP:
                self.notice(nick, DawdleBot.CMDHELP[args])
            else:
                self.notice(nick, f"{args} is not a command you can get help on.")
            return
        if not player:
            self.notice(nick, f"Available commands: {','.join(DawdleBot.ALLOWALL)}")
            self.notice(nick, f"For more information, see {conf['helpurl']}.")
        elif not player.isadmin:
            self.notice(nick, f"Available commands: {','.join(DawdleBot.ALLOWALL + DawdleBot.ALLOWPLAYERS)}")
            self.notice(nick, f"For more information, see {conf['helpurl']}.")
        else:
            self.notice(nick, f"Available commands: {','.join(sorted(DawdleBot.CMDHELP.keys()))}")
            self.notice(nick, f"Player help is at {conf['helpurl']} ; admin help is at {conf['admincommurl']}")


    def cmd_version(self, player, nick, args):
        """display version information."""
        self.notice(nick, f"DawdleRPG v{VERSION} by Daniel Lowe")


    def cmd_info(self, player, nick, args):
        """display bot information and admin list."""
        if not player.isadmin:
            if conf['allowuserinfo']:
                self.notice(nick, f"DawdleRPG v{VERSION} by Daniel Lowe, "
                        f"On via server: {self._irc.server}. Admins online: "
                        f"{', '.join([C('name', p.name) for p in self._players.online() if p.isadmin])}")
            else:
                self.notice(nick, "You cannot do 'info'.")
            return

        online_count = len(self._players.online())
        q_bytes = sum([len(b) for b in self._irc._writeq])
        online_admins = [CC("name", p.name) for p in self._players.online() if p.isadmin]
        if self._silence:
            silent_mode = ','.join(self._silence)
        else:
            silent_mode = 'off'
        self.notice(nick,
                    f"{self._irc._bytes_sent / 1024:.2f}kiB sent, "
                    f"{self._irc._bytes_received / 1024:.2f}kiB received "
                    f"in {duration(time.time() - start_time)}. "
                    f"{online_count} player{plural(online_count)} online of "
                    f"{self._players.count()} total users. "
                    f"{self._new_accounts} account{plural(self._new_accounts)} created since startup. "
                    f"PAUSE_MODE is {'on' if self._pause else 'off'}, "
                    f"SILENT_MODE is {silent_mode}. "
                    f"Outgoing queue is {q_bytes} byte{plural(q_bytes)} "
                    f"in {len(self._irc._writeq)} item{plural(len(self._irc._writeq))}. "
                    f"On via: {self._irc._server}. "
                    f"Admin{plural(len(online_admins))} online: {', '.join(online_admins)}")


    def cmd_whoami(self, player, nick, args):
        """display game character information."""
        self.notice(nick, f"You are {C('name', player.name)}, the level {player.level} {player.cclass}. Next level in {duration(player.nextlvl)}.")


    def cmd_announce(self, player, nick, args):
        """Send a message to the channel via the bot."""
        self.chanmsg(args)


    def cmd_status(self, player, nick, args):
        """get status on player."""
        if not conf['statuscmd']:
            self.notice(nick, "You cannot do 'status'.")
            return
        if args == '':
            t = player
        elif args not in self._players:
            self.notice(nick, f"No such player '{args}'.")
            return
        else:
            t = self._players[args]
        self.notice(nick,
                    f"{C('name', t.name)}: Level {t.level} {t.cclass}; "
                    f"Status: {'Online' if t.online else 'Offline'}; "
                    f"TTL: {duration(t.nextlvl)}; "
                    f"Idled: {duration(t.idled)}; "
                    f"Item sum: {t.itemsum()}")


    def cmd_login(self, player, nick, args):
        """start playing as existing character."""
        if player:
            self.notice(nick, f"Sorry, you are already online as {C('name', player.name)}")
            return
        if nick not in self._irc._users:
            self.notice(nick, f"Sorry, you aren't on {conf['botchan']}")
            return

        parts = args.split(' ', 1)
        if len(parts) != 2:
            self.notice(nick, "Try: LOGIN <username> <password>")
            return
        pname, ppass = parts
        if pname not in self._players:
            self.notice(nick, f"Sorry, no such account name.  Note that account names are case sensitive.")
            return
        if not self._players.check_login(pname, ppass):
            self.notice(nick, f"Wrong password.")
            return
        # Success!
        if conf['voiceonlogin'] and self._irc.bot_has_ops():
            self._irc.grant_voice(nick)
        player = self._players[pname]
        player.online = True
        player.nick = nick
        player.userhost = self._irc._users[nick].userhost
        player.lastlogin = time.time()
        self._players.write()
        self.chanmsg(f"{C('name', player.name)}, the level {player.level} {player.cclass}, is now online from nickname {nick}. Next level in {duration(player.nextlvl)}.")
        self.notice(nick, f"Logon successful. Next level in {duration(player.nextlvl)}.")


    def cmd_register(self, player, nick, args):
        """start game as new player."""
        if player:
            self.notice(nick, f"Sorry, you are already online as {C('name', player.name)}")
            return
        if nick not in self._irc._users:
            self.notice(nick, f"Sorry, you aren't on {conf['botchan']}")
            return
        if self._pause:
            self.notice(nick,
                        "Sorry, new accounts may not be registered while the "
                        "bot is in pause mode; please wait a few minutes and "
                        "try again.")
            return
        now = time.time()
        if now - self._last_reg_time < 1:
            self.notice(nick, "Sorry, there have been too many registrations. Try again in a minute.")
            return
        self._last_reg_time = now

        parts = args.split(' ', 2)
        if len(parts) != 3:
            self.notice(nick, "Try: REGISTER <username> <password> <char class>")
            self.notice(nick, "i.e. REGISTER Artemis MyPassword Goddess of the Hunt")
            return
        pname, ppass, pclass = parts
        if pname in self._players:
            self.notice(nick, "Sorry, that character name is already in use.")
        elif pname == self._irc._nick or pname == conf['botnick']:
            self.notice(nick, "That character name cannot be registered.")
        elif len(parts[1]) < 1 or len(pname) > conf["max_name_len"]:
            self.notice(nick, f"Sorry, character names must be between 1 and {conf['max_name_len']} characters long.")
        elif len(parts[1]) < 1 or len(pclass) > conf["max_class_len"]:
            self.notice(nick, f"Sorry, character classes must be between 1 and {conf['max_class_len']} characters long.")
        elif pname[0] == "#":
            self.notice(nick, "Sorry, character names may not start with #.")
        elif not pname.isprintable():
            self.notice(nick, "Sorry, character names may not include control codes.")
        elif not pclass.isprintable():
            self.notice(nick, "Sorry, character classes may not include control codes.")
        else:
            player = self._players.new_player(pname, pclass, ppass)
            player.online = True
            player.nick = nick
            player.userhost = self._irc._users[nick].userhost
            if conf['voiceonlogin'] and self._irc.bot_has_ops():
                self._irc.grant_voice(nick)
            self.chanmsg(f"Welcome {nick}'s new player {C('name', pname)}, the {pclass}!  Next level in {duration(player.nextlvl)}.")
            self.notice(nick, f"Success! Account {C('name', pname)} created. You have {duration(player.nextlvl)} seconds of idleness until you reach level 1.")
            self.notice(nick, "NOTE: The point of the game is to see who can idle the longest. As such, talking in the channel, parting, quitting, and changing nicks all penalize you.")
            self._new_accounts += 1


    def cmd_removeme(self, player, nick, args):
        """Delete own character."""
        if args == "":
            self.notice(nick, "Try: REMOVEME <password>")
        elif not self._players.check_login(player.name, args):
            self.notice(nick, "Wrong password.")
        else:
            self.notice(nick, f"Account {C('name', player.name)} removed.")
            self.chanmsg(f"{nick} removed their account. {C('name', player.name)}, the level {player.level} {player.cclass} is no more.")
            self._players.delete_player(player.name)
            if conf['voiceonlogin'] and self._irc.bot_has_ops():
                self._irc.revoke_voice(nick)


    def cmd_newpass(self, player, nick, args):
        """change own password."""
        parts = args.split(' ', 1)
        if len(parts) != 2:
            self.notice(nick, "Try: NEWPASS <old password> <new password>")
        elif not self._players.check_login(player.name, parts[0]):
            self.notice(nick, "Wrong password.")
        else:
            player.set_password(parts[1])
            self._players.write()
            self.notice(nick, "Your password was changed.")


    def cmd_logout(self, player, nick, args):
        """stop playing as character."""
        self.notice(nick, "You have been logged out.")
        player.online = False
        player.lastlogin = time.time()
        self._players.write()
        if conf['voiceonlogin'] and self._irc.bot_has_ops():
                self._irc.revoke_voice(nick)
        self.penalize(player, "logout")


    def cmd_backup(self, player, nick, args):
        """copy database file to a backup directory."""
        self._player.backup_store()
        self.notice(nick, "Player database backed up.")


    def cmd_chclass(self, player, nick, args):
        """change another player's character class."""
        parts = args.split(' ', 1)
        if len(parts) != 2:
            self.notice(nick, "Try: CHCLASS <account> <new class>")
        elif parts[0] not in self._players:
            self.notice(nick, f"{parts[0]} is not a valid account.")
        elif len(parts[1]) < 1 or len(parts[1]) > conf["max_class_len"]:
            self.notice(nick, f"Character classes must be between 1 and {conf['max_class_len']} characters long.")
        elif not parts[1].isprintable():
            self.notice(nick, "Character classes may not include control codes.")
        else:
            self._players[parts[0]].cclass = parts[1]
            self.notice(nick, f"{parts[0]}'s character class is now '{parts[1]}'.")


    def cmd_chpass(self, player, nick, args):
        """change another player's password."""
        parts = args.split(' ', 1)
        if len(parts) != 2:
            self.notice(nick, "Try: CHPASS <account> <new password>")
        elif parts[0] not in self._players:
            self.notice(nick, f"{parts[0]} is not a valid account.")
        else:
            self._players[parts[0]].set_password(parts[1])
            self.notice(nick, f"{parts[0]}'s password changed.")


    def cmd_chuser(self, player, nick, args):
        """Change someone's username."""
        parts = args.split(' ', 1)
        if len(parts) != 2:
            self.notice(nick, "Try: CHPASS <account> <new account name>")
        elif parts[0] not in self._players:
            self.notice(nick, f"{parts[0]} is not a valid account.")
        elif parts[1] in self._players:
            self.notice(nick, f"{parts[1]} is already taken.")
        elif len(parts[1]) < 1 or len(parts[1]) > conf["max_name_len"]:
            self.notice(nick, f"Character names must be between 1 and {conf['max_name_len']} characters long.")
        elif parts[1][0] == "#":
            self.notice(nick, "Character names may not start with a #.")
        elif not parts[1].isprintable():
            self.notice(nick, "Character names may not include control codes.")
        else:
            self._players.rename_player(parts[0], parts[1])
            self.notice(nick, f"{parts[0]} is now known as {parts[1]}.")


    def cmd_config(self, player, nick, args):
        """View/set a configuration setting."""
        if args == "":
            self.notice(nick, "Try: CONFIG <key search> or CONFIG <key> <value>")
            return
        
        parts = args.split(' ', 2)
        if len(parts) == 1:
            if parts[0] in conf:
                self.notice(nick, f"{parts[0]} {conf[parts[0]]}")
            else:
                self.notice(nick, f"Matching config keys: {', '.join([k for k in conf if parts[0] in k])}")
            return
        if parts[0] not in conf:
            self.notice(nick, f"{parts[0]} is not a config key.")
            return
        val = parse_val(parts[1])
        conf[parts[0]] = val
        self.notice(nick, f"{parts[0]} set to {val}.")


    def cmd_clearq(self, player, nick, args):
        """Clear outgoing message queue."""
        self._irc._writeq = []
        self.notice(nick, "Output queue cleared.")


    def cmd_del(self, player, nick, args):
        """Delete another player's account."""
        if args not in self._players:
            self.notice(nick, f"{args} is not a valid account.")
        else:
            self._players.delete_player(args)
            self.notice(nick, f"{args} has been deleted.")


    def cmd_deladmin(self, player, nick, args):
        """Remove admin authority."""
        if args not in self._players:
            self.notice(nick, f"{args} is not a valid account.")
        elif not self._players[args].isadmin:
            self.notice(nick, f"{args} is already not an admin.")
        elif args == conf['owner']:
            self.notice(nick, f"You can't do that.")
        else:
            self._players[args].isadmin = False
            self._db.write()
            self.notice(nick, f"{args} is no longer an admin.")


    def cmd_delold(self, player, nick, args):
        """Remove players not accessed in a number of days."""
        if not re.match(r"\d+", args):
            self.notice(nick, "Try DELOLD <# of days>")
            return
        days = int(args)
        if days < 7:
            self.notice(nick, "That seems a bit low.")
            return
        expire_time = int(time.time()) - days * 86400
        old = [p.name for p in self._players.inactive_since(expire_time)]
        for pname in old:
            self._players.delete_player(pname)
        self.chanmsg(f"{len(old)} account{plural(len(old))} not accessed "
                     f"in the last {days} days removed by {C('name', player.name)}.")


    def cmd_die(self, player, nick, args):
        """Shut down the bot."""
        self.notice(nick, "Shutting down.")
        self._irc.quit()
        sys.exit(0)


    def cmd_jump(self, player, nick, args):
        """Switch to new IRC server."""
        # Not implemented.
        pass


    def cmd_mkadmin(self, player, nick, args):
        """Grant admin authority to player."""
        if args not in self._players:
            self.notice(nick, f"{args} is not a valid account.")
        elif self._players[args].isadmin:
            self.notice(nick, f"{args} is already an admin.")
        else:
            self._players[args].isadmin = True
            self._db.write()
            self.notice(nick, f"{args} is now an admin.")


    def cmd_pause(self, player, nick, args):
        """Toggle pause mode."""
        self._pause = not self._pause
        if self._pause:
            self.notice(nick, "Pause mode enabled.")
        else:
            self.notice(nick, "Pause mode disabled.")


    def cmd_rehash(self, player, nick, args):
        """Re-read configuration file."""
        global conf
        conf = read_config(args.config_file)
        self.notice(nick, "Configuration reloaded.")


    def cmd_reloaddb(self, player, nick, args):
        """Reload the player database."""
        if not self._pause:
            self.notice(nick, "ERROR: can only use RELOADDB while in PAUSE mode.")
            return
        self._db.load()


    def cmd_restart(self, player, nick, args):
        """Restart from scratch."""
        # Not implemented.
        pass


    def cmd_silent(self, player, nick, args):
        """Set silent mode."""
        old_silence = self._silence
        self._silence = set()
        if args == "0":
            self.notice(nick, "Silent mode set to 0.  Channels and notices are enabled.")
        elif args == "1":
            self.notice(nick, "Silent mode set to 1.  Channel output is silenced.")
            self._silence = set(["chanmsg"])
        elif args == "2":
            self.notice(nick, "Silent mode set to 2.  Private notices are silenced.")
            self._silence = set(["notices"])
        elif args == "3":
            self.notice(nick, "Silent mode set to 3.  Channel and private notice output are silenced.")
            self._silence = set(["chanmsg", "notices"])
        else:
            self.notice(nick, "Try: SILENT 0|1|2|3")
            self._silence = old_silence


    def cmd_hog(self, player, nick, args):
        """Trigger Hand of God."""
        self.chanmsg(f"{C('name', player.name)} has summoned the Hand of God.")
        self.hand_of_god(self._players.online())


    def cmd_push(self, player, nick, args):
        """Push someone toward or away from their next level."""
        parts = args.split(' ')
        if len(parts) != 2 or not re.match(r'[+-]?\d+', parts[1]):
            self.notice(nick, "Try: PUSH <char name> <seconds>")
            return
        if parts[0] not in self._players:
            self.notice(nick, f"No such username {parts[0]}.")
            return
        target = self._players[parts[0]]
        amount = int(parts[1])
        if amount == 0:
            self.notice(nick, "That would not be interesting.")
            return

        if amount > target.nextlvl:
            self.notice(nick,
                        f"Time to level for {C('name', target.name)} ({target.nextlvl}s) "
                        f"is lower than {amount}; setting TTL to 0.")
            amount = target.nextlvl
        target.nextlvl -= amount
        direction = 'towards' if amount > 0 else 'away from'
        self.notice(nick, f"{C('name', target.name)} now reaches level {target.level + 1} in {duration(target.nextlvl)}.")
        self.logchanmsg(f"{C('name', player.name)} has pushed {C('name', target.name)} {abs(amount)} seconds {direction} "
                        f"level {target.level + 1}.  {C('name', target.name)} reaches next level "
                        f"in {duration(target.nextlvl)}.")


    def cmd_trigger(self, player, nick, args):
        """Trigger in-game events"""
        if args == 'calamity':
            self.chanmsg(f"{C('name', player.name)} brings down ruin upon the land.")
            self.calamity()
        elif args == 'godsend':
            self.chanmsg(f"{C('name', player.name)} rains blessings upon the people.")
            self.godsend()
        elif args == 'hog':
            self.chanmsg(f"{C('name', player.name)} has summoned the Hand of God.")
            self.hand_of_god(self._players.online())
        elif args == 'teambattle':
            self.chanmsg(f"{C('name', player.name)} has decreed violence.")
            self.team_battle(self._players.online())
        elif args == 'evilness':
            self.chanmsg(f"{C('name', player.name)} has swept the lands with evil.")
            self.evilness(self._players.online())
        elif args == 'goodness':
            self.chanmsg(f"{C('name', player.name)} has drawn down light from the heavens.")
            self.goodness(self._players.online())
        elif args == 'battle':
            self.chanmsg(f"{C('name', player.name)} has called forth a gladitorial arena.")
            self.challenge_opp(self.randchoice('triggered_battle', self._players.online()))
        elif args == 'quest':
            self.chanmsg(f"{C('name', player.name)} has called heroes to a quest.")
            if self._quest:
                self.notice(nick, "There's already a quest on.")
                return
            qp = [p for p in self._players.online() if p.level > conf["quest_min_level"]]
            if len(qp) < 4:
                self.notice(nick, "There's not enough eligible players.")
                return
            self.notice(nick, "Starting quest.")
            self.quest_start(int(time.time()))


    def cmd_quest(self, player, nick, args):
        """Get information on current quest."""
        if self._quest is None:
            self.notice(nick, "There is no active quest.")
        elif self._quest.mode == 1:
            qp = self._quest.questors
            self.notice(nick,
                        f"{C('name', qp[0].name)}, {C('name', qp[1].name)}, {C('name', qp[2].name)}, and {C('name', qp[3].name)} "
                        f"are on a quest to {self._quest.text}. Quest to complete in "
                        f"{duration(self._quest.qtime - time.time())}.")
        elif self._quest.mode == 2:
            qp = self._quest.questors
            mapnotice = ''
            if 'mapurl' in conf:
                mapnotice = f" See {conf['mapurl']} to monitor their journey's progress."
            self.notice(nick,
                        f"{C('name', qp[0].name)}, {C('name', qp[1].name)}, {C('name', qp[2].name)}, and {C('name', qp[3].name)} "
                        f"are on a quest to {self._quest.text}. Participants must first reach "
                        f"({self._quest.dests[0][0]}, {self._quest.dests[0][1]}), then "
                        f"({self._quest.dests[1][0]}, {self._quest.dests[1][1]}).{mapnotice}")


    def penalize(self, player, kind, text=None):
        """Exact penalities on a transgressing player."""
        penalty = conf["pen"+kind]
        if penalty == 0:
            return

        if self._quest and player in self._quest.questors:
            self.logchanmsg(f"{C('name')}{player.name}'s{C()} insolence has brought the wrath of "
                            f"the gods down upon them.  Your great wickedness "
                            f"burdens you like lead, drawing you downwards with "
                            f"great force towards hell. Thereby have you plunged "
                            f"{conf['penquest']} steps closer to that gaping maw.")
            for p in self._players.online():
                gain = int(conf["penquest"] * (conf['rppenstep'] ** p.level))
                p.penquest += gain
                p.nextlvl += gain

            self._quest = None
            self._qtimer = time.time() + conf["quest_interval_min"]

        if text:
            penalty *= len(text)
        penalty *= int(conf['rppenstep'] ** player.level)
        if 'limitpen' in conf and penalty > conf['limitpen']:
            penalty = conf['limitpen']
        setattr(player, "pen"+kind, getattr(player, "pen"+kind) + penalty)
        player.nextlvl += penalty
        if kind not in ['dropped', 'quit']:
            pendesc = {"quit": "quitting",
                       "dropped": "dropped connection",
                       "nick": "changing nicks",
                       "message": "messaging",
                       "part": "parting",
                       "kick": "being kicked",
                       "logout": "LOGOUT command"}[kind]
            self.notice(player.nick, f"Penalty of {duration(penalty)} added to your timer for {pendesc}.")

    def refresh_events(self):
        """Read events file if it has changed."""
        if self._events_loaded == os.path.getmtime(datapath(conf['eventsfile'])):
            return

        self._events = {}
        with open(datapath(conf['eventsfile'])) as inf:
            for line in inf.readlines():
                line = line.rstrip()
                if line != "":
                    self._events.setdefault(line[0], []).append(line[1:].lstrip())


    def expire_splits(self):
        """Kick players offline if they were disconnected for too long."""
        expiration = time.time() - conf['splitwait']
        for p in self._players.online():
            if p.nick not in self._irc._users and p.lastlogin < expiration:
                log.info("Expiring %s who was logged in as %s but was lost in a netsplit.", p.nick, p.name)
                self.penalize(p, "dropped")
                p.online = False
        self._players.write()

    async def gametick_loop(self):
        """Main gameplay loop to manage timing."""
        try:
            last_time = time.time() - 1
            while self._state == 'ready':
                await asyncio.sleep(conf['self_clock'])
                now = time.time()
                self.gametick(int(now), int(now - last_time))
                last_time = now
        except Exception as err:
            log.exception(err)
            sys.exit(2)


    def gametick(self, now, passed):
        """Main gameplay routine."""
        if conf['detectsplits']:
            self.expire_splits()
        self.refresh_events()

        op = self._players.online()
        online_count = 0
        evil_count = 0
        good_count = 0
        for player in op:
            online_count += 1
            if player.alignment == 'e':
                evil_count += 1
            elif player.alignment == 'g':
                good_count += 1

        day_ticks = 86400/conf['self_clock']
        if self.randint('hog_trigger', 0, 20 * day_ticks) < online_count:
            self.hand_of_god(op)
        if self.randint('team_battle_trigger', 0, 24 * day_ticks) < online_count:
            self.team_battle(op)
        if self.randint('calamity_trigger', 0, 8 * day_ticks) < online_count:
            self.calamity()
        if self.randint('godsend_trigger', 0, 4 * day_ticks) < online_count:
            self.godsend()
        if self.randint('evilness_trigger', 0, 8 * day_ticks) < evil_count:
            self.evilness(op)
        if self.randint('goodness_trigger', 0, 12 * day_ticks) < good_count:
            self.goodness(op)

        self.move_players()
        self.quest_check(now)

        if not self._pause:
            self._players.write()

        if now % 120 == 0 and self._quest:
            self.write_quest_file()
        if now % 36000 == 0:
            top = self._players.top_players()
            if top:
                self.chanmsg("Idle RPG Top Players:")
                for i, p in zip(itertools.count(), top):
                    self.chanmsg(f"{C('name', p.name)}, the level {p.level} {p.cclass}, is #{i+1}! "
                                 f"Next level in {duration(p.nextlvl)}.")
            self._players.backup_store()
        # high level players fight each other randomly
        hlp = [p for p in op if p.level >= 45]
        if now % 3600 == 0 and len(hlp) > len(op) * 0.15:
            self.challenge_opp(self.randchoice('pvp_combat', hlp))

        # periodic warning about pause mode
        if now % 600 == 0 and self._pause:
            self.chanmsg("WARNING: Cannot write database in PAUSE mode!")

        for player in op:
            player.nextlvl -= passed
            player.idled += passed
            if player.nextlvl < 1:
                player.level += 1
                if player.level > 60:
                    # linear after level 60
                    player.nextlvl = int(conf['rpbase'] * (conf['rpstep'] ** 60 + (86400 * (player.level - 60))))
                else:
                    player.nextlvl = int(conf['rpbase'] * (conf['rpstep'] ** player.level))

                self.chanmsg(f"{C('name', player.name)}, the {player.cclass}, has attained level {player.level}! Next level in {duration(player.nextlvl)}.")
                self.find_item(player)
                # Players below level 25 have fewer battles.
                if player.level >= 25 or self.randomly('lowlevel_battle', 4):
                    self.challenge_opp(player)


    def hand_of_god(self, op):
        """Hand of God that pushes a random player forword or back."""
        player = self.randchoice('hog_player', op)
        amount = int(player.nextlvl * (5 + self.randint('hog_amount', 0, 71))/100)
        if self.randomly('hog_effect', 5):
            self.logchanmsg(f"Verily I say unto thee, the Heavens have burst forth, and the blessed hand of God carried {C('name', player.name)} {duration(amount)} toward level {player.level + 1}.")
            player.nextlvl -= amount
        else:
            self.logchanmsg(f"Thereupon He stretched out His little finger among them and consumed {C('name', player.name)} with fire, slowing the heathen {duration(amount)} from level {player.level + 1}.")
            player.nextlvl += amount
        self.chanmsg(f"{C('name', player.name)} reaches next level in {duration(player.nextlvl)}.")
        self._players.write()


    def find_item(self, player):
        """Find a random item and add to player if higher level."""
        # TODO: Convert to configuration
        # Note that order is important here - each item is less likely to be picked than the previous.
        special_items = [SpecialItem(25, 50, 25, 'helm', "Mattt's Omniscience Grand Crown",
                                     "Your enemies fall before you as you anticipate their every move."),
                         SpecialItem(25, 50, 25, 'ring', "Juliet's Glorious Ring of Sparkliness",
                                     "Your enemies are blinded by both its glory and their greed as you "
                                     "bring desolation upon them."),
                         SpecialItem(30, 75, 25, 'tunic', "Res0's Protectorate Plate Mail",
                                     "Your enemies cower in fear as their attacks have no effect on you."),
                         SpecialItem(35, 100, 25, 'amulet', "Dwyn's Storm Magic Amulet",
                                     "Your enemies are swept away by an elemental fury before the war "
                                     "has even begun."),
                         SpecialItem(40, 150, 25, 'weapon', "Jotun's Fury Colossal Sword",
                                     "Your enemies' hatred is brought to a quick end as you arc your "
                                     "wrist, dealing the crushing blow."),
                         SpecialItem(45, 175, 26, 'weapon', "Drdink's Cane of Blind Rage",
                                     "Your enemies are tossed aside as you blindly swing your arm "
                                     "around hitting stuff."),
                         SpecialItem(48, 250, 51, 'boots', "Mrquick's Magical Boots of Swiftness",
                                     "Your enemies are left choking on your dust as you run from them "
                                     "very, very quickly."),
                         SpecialItem(25, 300, 51, 'weapon', "Jeff's Cluehammer of Doom",
                                     "Your enemies are left with a sudden and intense clarity of "
                                     "mind... even as you relieve them of it.")]

        for si in special_items:
            if player.level >= si.minlvl and self.randomly('specitem_find', 40):
                ilvl = si.itemlvl + self.randint('specitem_level', 0, si.lvlspread)
                player.acquire_item(si.kind, ilvl, si.name)
                self.notice(player.nick,
                                 f"The light of the gods shines down upon you! You have "
                                 f"found the {C('item')}level {ilvl} {si.name}{C()}!  {si.flavor}")
                return

        item = self.randchoice('find_item_itemtype', Player.ITEMS)
        level = 0
        if 'find_item_level' in self._overrides:
            level = self._overrides['find_item_level']
        else:
            level = 0
            for num in range(1, int(player.level * 1.5)):
                if self.randomly('find_item_level_ok', int(1.4**(num / 4))):
                    level = num
        old_level = int(getattr(player, item))
        if level > old_level:
            self.notice(player.nick,
                             f"You found a {C('item')}level {level} {Player.ITEMDESC[item]}{C()}! "
                             f"Your current {C('item')}{Player.ITEMDESC[item]}{C()} is only "
                             f"level {old_level}, so it seems Luck is with you!")
            player.acquire_item(item, level)
            self._players.write()
        else:
            self.notice(player.nick,
                             f"You found a {C('item')}level {level} {Player.ITEMDESC[item]}{C()}. "
                             f"Your current {C('item', Player.ITEMDESC[item])} is level {old_level}, "
                             f"so it seems Luck is against you.  You toss the {C('item', Player.ITEMDESC[item])}.")


    def pvp_battle(self, player, opp, flavor_start, flavor_win, flavor_loss):
        """Enact a powerful player-vs-player battle."""
        if opp is None:
            oppname = conf['botnick']
            oppsum = self._players.max_player_power()+1
        else:
            oppname = opp.name
            oppsum = opp.battleitemsum()

        playersum = player.battleitemsum()
        playerroll = self.randint('pvp_player_roll', 0, playersum)
        opproll = self.randint('pvp_opp_roll', 0, oppsum)
        if playerroll >= opproll:
            gain = 20 if opp is None else max(7, int(opp.level / 4))
            amount = int((gain / 100)*player.nextlvl)
            self.logchanmsg(f"{C('name', player.name)} [{playerroll}/{playersum}] has {flavor_start} "
                            f"{C('name', oppname)} [{opproll}/{oppsum}] {flavor_win}! "
                            f"{duration(amount)} is removed from {C('name')}{player.name}'s{C()} clock.")
            player.nextlvl -= amount
            if player.nextlvl > 0:
                self.chanmsg(f"{C('name', player.name)} reaches next level in {duration(player.nextlvl)}.")
            if opp is not None:
                if self.randomly('pvp_critical', {'g': 50, 'n': 35, 'e': 20}[player.alignment]):
                    penalty = int(((5 + self.randint('pvp_cs_penalty_pct', 0, 20))/100 * opp.nextlvl))
                    self.logchanmsg(f"{C('name', player.name)} has dealt {C('name', opp.name)} a {CC('red')}Critical Strike{C()}! "
                                    f"{duration(penalty)} is added to {C('name', opp.name)}'s clock.")
                    opp.nextlvl += penalty
                    self.chanmsg(f"{C('name', opp.name)} reaches next level in {duration(opp.nextlvl)}.")
                elif player.level > 19 and self.randomly('pvp_swap_item', 25):
                    item = self.randchoice('pvp_swap_itemtype', Player.ITEMS)
                    playeritem = getattr(player, item)
                    oppitem = getattr(opp, item)
                    if oppitem > playeritem:
                        self.logchanmsg(f"In the fierce battle, {C('name', opp.name)} dropped their {C('item')}level "
                                        f"{oppitem} {Player.ITEMDESC[item]}{C()}! {C('name', player.name)} picks it up, tossing "
                                        f"their old {C('item')}level {playeritem} {Player.ITEMDESC[item]}{C()} to {C('name', opp.name)}.")
                        player.swap_items(opp, item)
        else:
            # Losing
            loss = 10 if opp is None else max(7, int(opp.level / 7))
            amount = int((loss / 100)*player.nextlvl)
            self.logchanmsg(f"{C('name', player.name)} [{playerroll}/{playersum}] has {flavor_start} "
                            f"{oppname} [{opproll}/{oppsum}] {flavor_loss}! {duration(amount)} is "
                            f"added to {C('name')}{player.name}'s{C()} clock.")
            player.nextlvl += amount
            self.chanmsg(f"{C('name', player.name)} reaches next level in {duration(player.nextlvl)}.")

        if self.randomly('pvp_find_item', {'g': 50, 'n': 67, 'e': 100}[player.alignment]):
            self.chanmsg(f"While recovering from battle, {C('name', player.name)} notices a glint "
                         f"in the mud. Upon investigation, they find an old lost item!")
            self.find_item(player)


    def challenge_opp(self, player):
        """Pit player against another random player."""
        op = self._players.online()
        op.remove(player)       # Let's not fight ourselves
        op.append(None)         # This is the bot opponent
        self.pvp_battle(player, self.randchoice('challenge_opp_choice', op), 'challenged', 'and won', 'and lost')


    def team_battle(self, op):
        """Have a 3-vs-3 battle between teams."""
        if len(op) < 6:
            return
        op = self.randsample('team_battle_members', op, 6)
        team_a = sum([p.battleitemsum() for p in op[0:3]])
        team_b = sum([p.battleitemsum() for p in op[3:6]])
        gain = min([p.nextlvl for p in op[0:6]]) * 0.2
        roll_a = self.randint('team_a_roll', 0, team_a)
        roll_b = self.randint('team_b_roll', 0, team_b)
        if roll_a >= roll_b:
            self.logchanmsg(f"{C('name', op[0].name)}, {C('name', op[1].name)}, and {C('name', op[2].name)} [{roll_a}/{team_a}] "
                            f"have team battled {C('name', op[3].name)}, {C('name', op[4].name)}, and {C('name', op[5].name)} "
                            f"[{roll_b}/{team_b}] and won!  {duration(gain)} is removed from their clocks.")
            for p in op[0:3]:
                p.nextlvl -= gain
        else:
            self.logchanmsg(f"{C('name', op[0].name)}, {C('name', op[1].name)}, and {C('name', op[2].name)} [{roll_a}/{team_a}] "
                            f"have team battled {C('name', op[3].name)}, {C('name', op[4].name)}, and {C('name', op[5].name)} "
                            f"[{roll_b}/{team_b}] and lost!  {duration(gain)} is added to their clocks.")
            for p in op[0:3]:
                p.nextlvl += gain


    def calamity(self):
        """Bring bad things to a random player."""
        player = self.randchoice('calamity_target', self._players.online())
        if not player:
            return

        if self.randomly('calamity_item_damage', 10):
            # Item damaging calamity
            item = self.randchoice('calamity_item', Player.ITEMS)
            if item == "ring":
                msg = f"{C('name', player.name)} accidentally smashed their {C('item', 'ring')} with a hammer!"
            elif item == "amulet":
                msg = f"{C('name', player.name)} fell, chipping the stone in their {C('item', 'amulet')}!"
            elif item == "charm":
                msg = f"{C('name', player.name)} slipped and dropped their {C('item', 'charm')} in a dirty bog!"
            elif item == "weapon":
                msg = f"{C('name', player.name)} left their {C('item', 'weapon')} out in the rain to rust!"
            elif item == "helm":
                msg = f"{C('name')}{player.name}'s{C()} {C('item', 'helm')} was touched by a rust monster!"
            elif item == "tunic":
                msg = f"{C('name', player.name)} spilled a level 7 shrinking potion on their {C('item', 'tunic')}!"
            elif item == "gloves":
                msg = f"{C('name', player.name)} dipped their gloved fingers in a pool of acid!"
            elif item == "leggings":
                msg = f"{C('name', player.name)} burned a hole through their {C('item', 'leggings')} while ironing them!"
            elif item == "shield":
                msg = f"{C('name')}{player.name}'s{C()} {C('item', 'shield')} was damaged by a dragon's fiery breath!"
            elif item == "boots":
                msg = f"{C('name', player.name)} stepped in some hot lava!"
            self.logchanmsg(msg + f" {C('name')}{player.name}'s{C()} {C('item', Player.ITEMDESC[item])} loses 10% of its effectiveness.")
            setattr(player, item, int(getattr(player, item) * 0.9))
            return

        # Level setback calamity
        amount = int(self.randint('calamity_setback_pct', 5, 13) / 100 * player.nextlvl)
        player.nextlvl += amount
        action = self.randchoice('calamity_action', self._events["C"])
        self.logchanmsg(f"{C('name', player.name)} {action}! This terrible calamity has slowed them "
                        f"{duration(amount)} from level {player.level + 1}.")
        if player.nextlvl > 0:
            self.chanmsg(f"{C('name', player.name)} reaches next level in {duration(player.nextlvl)}.")


    def godsend(self):
        """Bring good things to a random player."""
        player = self.randchoice('godsend_target', self._players.online())
        if not player:
            return

        if self.randomly('godsend_item_improve', 10):
            # Item improving godsend
            item = self.randchoice('godsend_item', Player.ITEMS)
            if item == "ring":
                msg = f"{C('name', player.name)} dipped their {C('item', 'ring')} into a sacred fountain!"
            elif item == "amulet":
                msg = f"{C('name')}{player.name}'s{C()} {C('item', 'amulet')} was blessed by a passing cleric!"
            elif item == "charm":
                msg = f"{C('name')}{player.name}'s{C()} {C('item', 'charm')} ate a bolt of lightning!"
            elif item == "weapon":
                msg = f"{C('name', player.name)} sharpened the edge of their {C('item', 'weapon')}!"
            elif item == "helm":
                msg = f"{C('name', player.name)} polished their {C('item', 'helm')} to a mirror shine."
            elif item == "tunic":
                msg = f"A magician cast a spell of Rigidity on {C('name')}{player.name}'s{C()} {C('item', 'tunic')}!"
            elif item == "gloves":
                msg = f"{C('name', player.name)} lined their {C('item', 'gloves')} with a magical cloth!"
            elif item == "leggings":
                msg = f"The local wizard imbued {C('name')}{player.name}'s{C()} {C('item', 'pants')} with a Spirit of Fortitude!"
            elif item == "shield":
                msg = f"{C('name', player.name)} reinforced their {C('item', 'shield')} with a dragon's scale!"
            elif item == "boots":
                msg = f"A sorceror enchanted {C('name')}{player.name}'s{C()} {C('item', 'boots')} with Swiftness!"

            self.logchanmsg(msg + f" {C('name')}{player.name}'s{C()} {C('item', Player.ITEMDESC[item])} gains 10% effectiveness.")
            setattr(player, item, int(getattr(player, item) * 1.1))
            return

        # Level godsend
        amount = int(self.randint('godsend_amount_pct', 5, 13) / 100 * player.nextlvl)
        player.nextlvl -= amount
        action = self.randchoice('godsend_action', self._events["G"])
        self.logchanmsg(f"{C('name', player.name)} {action}! This wondrous godsend has accelerated them "
                        f"{duration(amount)} towards level {player.level + 1}.")
        if player.nextlvl > 0:
            self.chanmsg(f"{C('name', player.name)} reaches next level in {duration(player.nextlvl)}.")


    def evilness(self, op):
        """Bring evil or an item to a random evil player."""
        evil_p = [p for p in op if p.alignment == 'e']
        if not evil_p:
            return
        player = self.randchoice('evilness_player', evil_p)
        if self.randomly('evilness_theft', 2):
            target = self.randchoice('evilness_target', [p for p in op if p.alignment == 'g'])
            if not target:
                return
            item = self.randchoice('evilness_item', Player.ITEMS)
            if getattr(player, item) < getattr(target, item):
                player.swap_items(target, item)
                self.logchanmsg(f"{C('name', player.name)} stole {target.name}'s {C('item')}level {getattr(player, item)} "
                                f"{Player.ITEMDESC[item]}{C()} while they were sleeping!  {C('name', player.name)} "
                                f"leaves their old {C('item')}level {getattr(target, item)} {Player.ITEMDESC[item]}{C()} "
                                f"behind, which {C('name', target.name)} then takes.")
            else:
                self.notice(player.nick,
                            f"You made to steal {C('name', target.name)}'s {C('item', Player.ITEMDESC[item])}, "
                            f"but realized it was lower level than your own.  You creep "
                            f"back into the shadows.")
        else:
            amount = int(player.nextlvl * self.randint('evilness_penalty_pct', 1,6) / 100)
            player.nextlvl += amount
            self.logchanmsg(f"{C('name', player.name)} is forsaken by their evil god. {duration(amount)} is "
                              f"added to their clock.")
            if player.nextlvl > 0:
                self.chanmsg(f"{C('name', player.name)} reaches next level in {duration(player.nextlvl)}.")

    def goodness(self, op):
        """Bring two good players closer to their next level."""
        good_p = [p for p in op if p.alignment == 'g']
        if len(good_p) < 2:
            return
        players = self.randsample('goodness_players', good_p, 2)
        gain = self.randint('goodness_gain_pct', 5, 13)
        self.logchanmsg(f"{C('name', players[0].name)} and {C('name', players[1].name)} have not let the iniquities "
                        f"of evil people poison them. Together have they prayed to their god, "
                        f"and light now shines down upon them. {gain}% of their time is removed "
                        f"from their clocks.")
        for player in players:
            player.nextlvl = int(player.nextlvl * (1 - gain / 100))
            if player.nextlvl > 0:
                self.chanmsg(f"{C('name', player.name)} reaches next level in {duration(player.nextlvl)}.")


    def move_players(self):
        """Move players around the map."""
        op = self._players.online()
        if not op:
            return
        self.randshuffle('move_players_order', op)
        mapx = conf['mapx']
        mapy = conf['mapy']
        combatants = dict()
        if self._quest and self._quest.mode == 2:
            destx = self._quest.dests[self._quest.stage-1][0]
            desty = self._quest.dests[self._quest.stage-1][1]
            for p in self._quest.questors:
                # mode 2 questors always move towards the next goal
                xmove = 0
                ymove = 0
                distx = destx - p.posx
                if distx != 0:
                    if abs(distx) > mapx/2:
                        distx = -distx
                    xmove = distx / abs(distx) # normalize to -1/0/1

                disty = desty - p.posy
                if disty != 0:
                    if abs(disty) > mapy/2:
                        disty = -disty
                    ymove = disty / abs(disty) # normalize to -1/0/1

                p.posx = (p.posx + xmove) % mapx
                p.posy = (p.posy + ymove) % mapy
                # take questors out of rotation for movement and pvp
                op.remove(p)

        for p in op:
            # everyone else wanders aimlessly
            p.posx = (p.posx + self.randint('move_player_x',-1,1)) % mapx
            p.posy = (p.posy + self.randint('move_player_y',-1,1)) % mapy

            if (p.posx, p.posy) in combatants:
                combatant = combatants[(p.posx, p.posy)]
                if combatant.isadmin and self.randomly('move_player_bow', 100):
                    self.chanmsg(f"{C('name', p.name)} encounters {C('name', combatant.name)} and bows humbly.")
                elif self.randomly('move_player_combat', len(op)):
                    self.pvp_battle(p, combatant,
                                    'come upon',
                                    'and taken them in combat',
                                    'and been defeated in combat')
                    del combatants[(p.posx, p.posy)]
            else:
                combatants[(p.posx, p.posy)] = p


    def quest_start(self, now):
        """Start a random quest with four random players."""
        latest_login_time = now - 36000
        qp = [p for p in self._players.online() if p.level > conf["quest_min_level"] and p.lastlogin < latest_login_time]
        if len(qp) < 4:
            return
        qp = self.randsample('quest_members', qp, 4)
        questconf = self.randchoice('quest_selection', self._events["Q"])
        match = (re.match(r'(1) (.*)', questconf) or
                 re.match(r'(2) (\d+) (\d+) (\d+) (\d+) (.*)', questconf))
        if not match:
            return
        self._quest = Quest(qp)
        if match[1] == '1':
            quest_time = self.randint('quest_time', 6, 12)*3600
            self._quest.mode = 1
            self._quest.text = match[2]
            self._quest.qtime = time.time() + quest_time
            self.chanmsg(f"{C('name', qp[0].name)}, {C('name', qp[1].name)}, {C('name', qp[2].name)}, and {C('name', qp[3].name)} have "
                              f"been chosen by the gods to {self._quest.text}.  Quest to end in "
                              f"{duration(quest_time)}.")
        elif match[1] == '2':
            self._quest.mode = 2
            self._quest.stage = 1
            self._quest.dests = [(int(match[2]), int(match[3])), (int(match[4]), int(match[5]))]
            self._quest.text = match[6]
            mapnotice = ''
            if 'mapurl' in conf:
                mapnotice = f" See {conf['mapurl']} to monitor their journey's progress."
            self.chanmsg(f"{C('name', qp[0].name)}, {C('name', qp[1].name)}, {C('name', qp[2].name)}, and {C('name', qp[3].name)} have "
                         f"been chosen by the gods to {self._quest.text}.  Participants must first "
                         f"reach ({self._quest.dests[0][0]},{self._quest.dests[0][1]}), "
                         f"then ({self._quest.dests[1][0]},{self._quest.dests[1][1]}).{mapnotice}")


    def quest_check(self, now):
        """Complete quest if criteria are met."""
        if self._quest is None:
            if now >= self._qtimer:
                self.quest_start(now)
        elif self._quest.mode == 1:
            if now >= self._quest.qtime:
                qp = self._quest.questors
                self.logchanmsg(f"{C('name', qp[0].name)}, {C('name', qp[1].name)}, {C('name', qp[2].name)}, and {C('name', qp[3].name)} "
                                f"have blessed the realm by completing their quest! 25% of "
                                f"their burden is eliminated.")
                for q in qp:
                    q.nextlvl = int(q.nextlvl * 0.75)
                self._quest = None
                self._qtimer = now + conf["quest_interval_min"]
                self.write_quest_file()
        elif self._quest.mode == 2:
            destx = self._quest.dests[self._quest.stage-1][0]
            desty = self._quest.dests[self._quest.stage-1][1]
            done = True
            for q in self._quest.questors:
                if q.posx != destx or q.posy != desty:
                    done = False
                    break
            if done:
                self._quest.stage += 1
                qp = self._quest.questors
                dests_left = len(self._quest.dests) - self._quest.stage + 1
                if dests_left > 0:
                    self.chanmsg(f"{C('name', qp[0].name)}, {C('name', qp[1].name)}, {C('name', qp[2].name)}, and {C('name', qp[3].name)} "
                                 f"have reached a landmark on their journey! {dests_left} "
                                 f"landmark{plural(dests_left)} "
                                 f"remain{plural(dests_left, 's', '')}.")
                else:
                    self.logchanmsg(f"{C('name', qp[0].name)}, {C('name', qp[1].name)}, {C('name', qp[2].name)}, and {C('name', qp[3].name)} "
                                    f"have completed their journey! 25% of "
                                    f"their burden is eliminated.")
                    for q in qp:
                        q.nextlvl = int(q.nextlvl * 0.75)
                    self._quest = None
                    self._qtimer = now + conf["quest_interval_min"]
                self.write_quest_file()


    def write_quest_file(self):
        """Write a descriptive quest file for the web interface."""
        if not conf['writequestfile']:
            return
        with open(datapath(conf['questfilename']), 'w') as ouf:
            if not self._quest:
                # leave behind an empty quest file
                return

            ouf.write(f"T {self._quest.text}\n"
                      f"Y {self._quest.mode}\n")

            if self._quest.mode == 1:
                ouf.write(f"S {self._quest.qtime}\n")
            elif self._quest.mode == 2:
                ouf.write(f"S {self._quest.stage:2d}\n"
                          f"P {' '.join([' '.join(str(p)) for p in self._quest.dests])}\n")

            ouf.write(f"P1 {self._quest.questors[0].name}\n"
                      f"P2 {self._quest.questors[1].name}\n"
                      f"P3 {self._quest.questors[2].name}\n"
                      f"P4 {self._quest.questors[3].name}\n")


async def mainloop(client):
    """Connect to servers repeatedly."""
    while not client.quitting:
        addr, port = conf['servers'][0].split(':')
        await client.connect(addr, port)
        if not conf['reconnect']:
            break
        await asyncio.sleep(conf['reconnect_wait'])


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


def check_pidfile(pidfile):
    """Exit if pid in pidfile is still active."""
    if os.path.exists(pidfile):
        with open(pidfile) as inf:
            pid = int(inf.readline().rstrip())
            try:
                os.kill(pid, 0)
            except OSError:
                pass
            else:
                sys.stderr.write(f"The pidfile at {pidfile} indicates that dawdle is still running at pid {pid}.  Remove the file or kill the process.\n")
                sys.exit(1)


def start_bot():
    """Main entry point for bot."""
    global args
    global conf
    args = parser.parse_args()
    conf = read_config(args.config_file)

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
            conf[k] = parse_val(v)
    if server_overrides:
        conf["servers"] = server_overrides
    if okurl_overrides:
        conf["okurls"] = okurl_overrides

    log.setLevel(logging.INFO)
    if "logfile" in conf:
        h = logging.FileHandler(conf["logfile"])
        h.setLevel(conf["loglevel"])
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        log.addHandler(h)

    # debug mode turns off daemonization and sets the log level to debug.
    if conf["debug"]:
        conf["daemonize"] = False
        log.setLevel(logging.DEBUG)
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        log.addHandler(h)

    global db
    db = PlayerDB(IdleRPGPlayerStore(datapath(conf["dbfile"])))
    if db.exists():
        db.backup_store()
        db.load()
    else:
        first_setup()

    if 'pidfile' in conf:
        check_pidfile(datapath(conf['pidfile']))

    if conf['daemonize']:
        daemonize()

    if 'pidfile' in conf:
        with open(datapath(conf['pidfile']), "w") as ouf:
            ouf.write(f"{os.getpid()}\n")
        atexit.register(os.remove, datapath(conf['pidfile']))

    bot = DawdleBot(db)
    client = IRCClient(bot)
    asyncio.run(mainloop(client))


if __name__ == "__main__":
    start_bot()
