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
import collections
import crypt
import itertools
import logging
import os
import os.path
import random
import re
import sqlite3
import sys
import textwrap
import time

from hmac import compare_digest as compare_hash
from operator import attrgetter

log = logging.getLogger()

VERSION = "1.0.0"

# Penalties and their description
PENALTIES = {"quit": 20, "nick": 30, "message": 1, "part": 200, "kick": 250, "logout": 20}
PENDESC = {"quit": "quitting", "nick": "changing nicks", "message": "messaging", "part": "parting", "kick": "being kicked", "logout": "LOGOUT command"}


# Output throttling - handle bursts of 5 messages every ten seconds
THROTTLE_RATE = 5
THROTTLE_PERIOD = 10

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
conf = {}
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


def plural(num, singlestr, pluralstr):
    if num == 1:
        return singlestr
    return pluralstr


def grouper(iterable, n, fillvalue=None):
    """Collect data into fixed-length chunks or blocks

    grouper('ABCDEFG', 3, 'x') --> ABC DEF Gxx
    From python itertools recipes"""
    args = [iter(iterable)] * n
    return itertools.zip_longest(fillvalue=fillvalue, *args)


def duration(secs):
    d, secs = int(secs / 86400), secs % 86400
    h, secs = int(secs / 3600), secs % 3600
    m, secs = int(secs / 60), secs % 60
    return f"{d} day{plural(d, '', 's')}, {h:02d}:{m:02d}:{int(secs):02d}"


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


class Player(object):
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
        p = cls()
        for k,v in d.items():
            setattr(p, k, v)
        return p

    @staticmethod
    def new_player(pname, pclass, ppass):
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
        p.nextlvl = conf['rpbase']
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
        # Total penalties from losing quests
        p.penquest = 0
        # Total penalties from using the logout command
        p.penlogout = 0
        # Time created
        p.created = time.time()
        # Last time logged in
        p.lastlogin = time.time()
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
        self.pw = crypt.crypt(ppass, crypt.mksalt())

    def acquire_item(self, kind, level, name=''):
        setattr(self, kind, level)
        setattr(self, kind+"name", name)

    def swap_items(self, o, kind):
        namefield = kind+"name"
        tmpitem = getattr(self, kind)
        tmpitemname = getattr(self, namefield)
        self.acquire_item(kind, getattr(o, kind), getattr(o, namefield))
        o.acquire_item(kind, tmpitem, tmpitemname)

    def itemsum(self):
        """Add up the power of all the player's items"""
        sum = 0
        for item in Player.ITEMS:
            sum += getattr(self, item)
        return sum

    def battleitemsum(self):
        """
        Add up item power for battle.

        Good players get a 10% boost, and evil players get a 10% penalty.
        """
        sum = self.itemsum()
        if self.alignment == 'e':
            return int(sum * 0.9)
        if self.alignment == 'g':
            return int(sum * 1.1)
        return sum


class PlayerStore(object):
    """Interface for a PlayerDB backend."""

    def create(self):
        pass

    def readall(self):
        pass

    def writeall(self):
        pass

    def close(self):
        pass

    def new(self):
        pass

    def rename(self):
        pass

    def delete(self):
        pass

class IdleRPGPlayerStore(PlayerStore):

    IRPG_FIELDS = ["username", "pass", "is admin", "level", "class", "next ttl", "nick", "userhost", "online", "idled", "x pos", "y pos", "pen_mesg", "pen_nick", "pen_part", "pen_kick", "pen_quit", "pen_quest", "pen_logout", "created", "last login", "amulet", "charm", "helm", "boots", "gloves", "ring", "leggings", "shield", "tunic", "weapon", "alignment"]

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

    def code_to_item(self, s):
        match = re.match(r"^(\d+)(.?)", s)
        if not match:
            print(f"wtf not matched: {s}")
        lvl = int(match[1])
        if match[2]:
            return (lvl, [k for k,v in IdleRPGPlayerStore.ITEMCODES.items() if v == match[2]][0])
        return (lvl, "")

    def __init__(self, dbpath):
        self._dbpath = dbpath


    def create(self):
        self.writeall({})


    def exists(self):
        return os.path.exists(self._dbpath)


    def readall(self):
        players = {}
        with open(self._dbpath) as inf:
            for line in inf.readlines():
                if re.match(r'^\s*(?:#|$)', line):
                    continue
                parts = line.rstrip().split("\t")
                if len(parts) != 32:
                    print(f"omg line corrupt {len(parts)} fields:", repr(line))
                    sys.exit(-1)

                d = dict(zip(["name", "pw", "isadmin", "level", "cclass", "nextlvl", "nick", "userhost", "online", "idled", "posx", "posy", "penmessage", "pennick", "penpart", "penkick", "penquit", "penquest", "penlogout", "created", "lastlogin", "amulet", "charm", "helm", "boots", "gloves", "ring", "leggings", "shield", "tunic", "weapon", "alignment"], parts))
                # convert items
                for i in Player.ITEMS:
                    d[i], d[i+'name'] = self.code_to_item(d[i])
                # convert int fields
                for f in ["nextlvl", "idled", "posx", "posy", "penmessage", "pennick", "penpart", "penkick", "penquit", "penquest", "penlogout", "created", "lastlogin"]:
                    d[f] = int(d[f])
                # convert boolean fields
                for f in ["isadmin", "online"]:
                    d[f] = (d[f] == '1')

                p = Player.from_dict(d)
                players[p.name] = p
        return players


    def _player_to_record(self, p):
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
            str(p.penquit),
            str(p.penquest),
            str(p.penlogout),
            str(int(p.created)),
            str(int(p.lastlogin)),
            f"{p.amulet}{IdleRPGPlayerStore.ITEMCODES.get(p.amuletname, '')}",
            f"{p.charm}{IdleRPGPlayerStore.ITEMCODES.get(p.charmname, '')}",
            f"{p.helm}{IdleRPGPlayerStore.ITEMCODES.get(p.helmname, '')}",
            f"{p.boots}{IdleRPGPlayerStore.ITEMCODES.get(p.bootsname, '')}",
            f"{p.gloves}{IdleRPGPlayerStore.ITEMCODES.get(p.glovesname, '')}",
            f"{p.ring}{IdleRPGPlayerStore.ITEMCODES.get(p.ringname, '')}",
            f"{p.leggings}{IdleRPGPlayerStore.ITEMCODES.get(p.leggingsname, '')}",
            f"{p.shield}{IdleRPGPlayerStore.ITEMCODES.get(p.shieldname, '')}",
            f"{p.tunic}{IdleRPGPlayerStore.ITEMCODES.get(p.tunicname, '')}",
            f"{p.weapon}{IdleRPGPlayerStore.ITEMCODES.get(p.weaponname, '')}",
            str(p.alignment)
        ]) + "\n"

    def writeall(self, players):
        with open(self._dbpath, "w") as ouf:
            ouf.write("# " + "\t".join(IdleRPGPlayerStore.IRPG_FIELDS) + "\n")
            for p in players.values():
                ouf.write(self._player_to_record(p))


    def new(self, p):
        with open(self._dbpath, "a") as ouf:
            ouf.write(self._player_to_record(p))


    def rename(self, old_name, new_name):
        players = self.readall()
        players[new_name] = players[old_name]
        del players[old_name]
        self.writeall(players)


    def delete(self, pname):
        players = self.readall()
        players.pop(pname, None)
        self.writeall(players)


class Sqlite3PlayerStore(PlayerStore):


    @staticmethod
    def dict_factory(cursor, row):
        d = {}
        for idx, col in enumerate(cursor.description):
            d[col[0]] = row[idx]
        return d


    def _connect(self):
        if self._db is None:
            self._db = sqlite3.connect(self._dbpath)
            self._db.row_factory = Sqlite3PlayerStore.dict_factory

        return self._db


    def __init__(self, dbpath):
        self._dbpath = dbpath
        self._db = None


    def create(self):
        with self._connect() as cur:
            cur.execute(f"create table players ({','.join(PlayerDB.FIELDS)})")


    def exists(self):
        return os.path.exists(self._dbpath)


    def readall(self):
        players = {}
        with self._connect() as con:
            cur = con.execute("select * from players")
            for d in cur.fetchall():
                players[d['name']] = Player.from_dict(d)
        return players


    def writeall(self, players):
        with self._connect() as cur:
            update_fields = ",".join(f"{k}=:{k}" for k in PlayerDB.FIELDS)
            cur.executemany(f"update players set {update_fields} where name=:name",
                            [vars(p) for p in players.values()])


    def close(self):
        self._db.close()


    def new(self, p):
        with self._connect() as cur:
            d = vars(p)
            cur.execute(f"insert into players values ({('?, ' * len(d))[:-2]})",
                        [d[k] for k in PlayerDB.FIELDS])
            cur.commit()


    def rename(self):
        with self._connect() as cur:
            cur.execute("update players set name = ? where name = ?", (new_name, old_name))
            cur.commit()


    def delete(self):
        with self._connect() as cur:
            cur.execute("delete from players where name = ?", (pname,))
            cur.commit()


class PlayerDB(object):

    FIELDS = ["name", "cclass", "pw", "isadmin", "level", "nextlvl", "nick", "userhost", "online", "idled", "posx", "posy", "penmessage", "pennick", "penpart", "penkick", "penquit", "penquest", "penlogout", "created", "lastlogin", "alignment", "amulet", "amuletname", "charm", "charmname", "helm", "helmname", "boots", "bootsname", "gloves", "glovesname", "ring", "ringname", "leggings", "leggingsname", "shield", "shieldname", "tunic", "tunicname", "weapon", "weaponname"]


    def __init__(self, store):
        self._store = store
        self._players = {}

    def __getitem__(self, pname):
        return self._players[pname]


    def __contains__(self, pname):
        return pname in self._players


    def close(self):
        """Close the underlying db.  Used for testing."""
        self._store.close()

    def exists(self):
        return self._store.exists()


    def load(self):
        """Load all players from database into memory"""
        self._players = self._store.readall()


    def write(self):
        """Write all players into database"""
        self._store.writeall(self._players)


    def create(self):
        self._store.create()


    def new_player(self, pname, pclass, ppass):
        global conf

        if pname in self._players:
            raise KeyError

        pclass = pclass[:30]

        p = Player.new_player(pname, pclass, ppass)
        self._players[pname] = p
        self._store.new(p)

        return p


    def rename_player(self, old_name, new_name):
        self._players[new_name] = self._players[old_name]
        self._players[new_name].name = new_name
        self._players.pop(old_name, None)
        self._store.rename(old_name, new_name)


    def delete_player(self, pname):
        self._players.pop(pname)
        self._store.delete(pname)


    def from_nick(self, nick):
        for p in self._players.values():
            if p.online and p.nick == nick:
                return p
        return None


    def check_login(self, pname, ppass):
        result = (pname in self._players)
        result = result and compare_hash(self._players[pname].pw, crypt.crypt(ppass, self._players[pname].pw))
        return result


    def online(self):
        return [p for p in self._players.values() if p.online]


    def max_player_power(self):
        return max([p.itemsum() for p in self._players.values()])


    def top_players(self):
        s = sorted(self._players.values(), key=attrgetter('level'))
        return sorted(s, key=attrgetter('nextlvl'), reverse=True)[:3]


def first_setup():
    global conf
    global db

    if db.exists():
        return
    pname = input(f"{conf['dbfile']} does not appear to exist.  I'm guessing this is your first time using DawdleRPG. Please give an account name that you would like to have admin access [{conf['owner']}]: ")
    if pname == "":
        pname = conf["owner"]
    pclass = input("Enter a character class for this account: ")
    pclass = pclass[:30]
    ppass = input("Enter a password for this account: ")

    db.create()
    p = db.new_player(pname, pclass, ppass)
    p.isadmin = True
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
    - Tracking users in the channel
    - Calling methods on the bot interface
 """
    MESSAGE_RE = re.compile(r'^(?:@(\S*) )?(?::([^ !]*)(?:!([^ @]*)(?:@([^ ]*))?)?\s+)?(\S+)\s*((?:[^:]\S*(?:\s+|$))*)(?::(.*))?')

    Message = collections.namedtuple('Message', ['tags', 'src', 'user', 'host', 'cmd', 'args', 'trailing', 'line', 'time'])


    def __init__(self, bot):
        self._bot = bot
        self._writer = None
        self._nick = conf['botnick']


    async def connect(self, addr, port):
        reader, self._writer = await asyncio.open_connection(addr, port, ssl=True)
        self._connected = True
        self._messages_sent = 0
        self._writeq = []
        self._flushq_task = None
        self._prefixmodes = {}
        self._maxmodes = 3
        self._modetypes = {}
        self.userhosts = {}            # all players in the channel and their userhost
        self.usermodes = {}            # all players in the channel and their modes
        self.sendnow("CAP REQ :multi-prefix")
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
            # Assume utf-8 encoding, fall back to latin-1, which has no invalid encodings from bytes.
            try:
                line = str(line, encoding='utf8')
            except UnicodeDecodeError:
                line = str(line, encoding='latin-1')
            line = line.rstrip('\r\n')
            if conf["debug"]:
                print(int(time.time()), "<-", line)
            msg = self.parse_message(line)
            self.dispatch(msg)


    def send(self, s):
        b = bytes(s+"\r\n", encoding='utf8')
        if self._messages_sent < THROTTLE_RATE:
            if conf["debug"]:
                print(int(time.time()), f"({self._messages_sent})->", s)
            self._messages_sent += 1
            self._writer.write(b)
        else:
            self._writeq.append(b)

        # The flushq task will reset messages_sent after the throttle period.
        if not self._flushq_task:
            self._flushq_task = asyncio.create_task(self.flushq_task())


    def sendnow(self, s):
        if conf["debug"]:
            print(int(time.time()), "=>", s)
        b = bytes(s+"\r\n", encoding='utf8')
        self._messages_sent += 1
        self._writer.write(b)
        if not self._flushq_task:
            self._flushq_task = asyncio.create_task(self.flushq_task())


    async def flushq_task(self):
        await asyncio.sleep(THROTTLE_PERIOD)
        self._messages_sent = max(0, self._messages_sent - THROTTLE_RATE)
        while self._writeq:
            while self._writeq and self._messages_sent < THROTTLE_RATE:
                if conf["debug"]:
                    print(int(time.time()), f"({self._messages_sent})~>", str(self._writeq[0], encoding='utf8'))
                self._messages_sent += 1
                self._writer.write(self._writeq[0])
                self._writeq = self._writeq[1:]
            if self._writeq:
                await asyncio.sleep(THROTTLE_PERIOD)
                self._messages_sent = max(0, self._messages_sent - THROTTLE_RATE)

        self._flushq_task = None


    def parse_message(self, line):
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
        if hasattr(self, "handle_"+msg.cmd.lower()):
            getattr(self, "handle_"+msg.cmd.lower())(msg)


    def handle_ping(self, msg):
        self.sendnow(f"PONG :{msg.trailing}")


    def handle_005(self, msg):
        """RPL_ISUPPORT - server features and information"""
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
        self.userhosts[msg.args[4]] = f"{msg.args[1]}@{msg.args[2]}"
        self.usermodes[msg.args[4]] = set([self._prefixmodes[p] for p in msg.args[5][1:]]) # Format is [GH]\S*


    def handle_315(self, msg):
        """RPL_ENDOFWHO - End of WHO command response"""
        self._bot.ready()


    def handle_353(self, msg):
        """RPL_NAMREPLY - names in the channel"""
        # We ignore this for now, since the userhost-in-names cap
        # isn't widely supported.
        pass


    def handle_366(self, msg):
        """RPL_ENDOFNAMES - the actual end of channel joining"""
        # We know who is in the channel now
        if 'botopcmd' in conf:
            self.sendnow(re.sub(r'%botnick%', self._nick, conf['botopcmd']))
        self._bot.self_joined()


    def handle_433(self, msg):
        """ERR_NICKNAME_IN_USE - try another nick"""
        self._nick = self._nick + "0"
        self.nick(self._nick)
        if 'botghostcmd' in conf:
            self.send(conf['botghostcmd'])


    def handle_join(self, msg):
        if msg.src != self._nick:
            self.userhosts[msg.src] = f"{msg.user}@{msg.host}"
            self.usermodes[msg.src] = set()

    def handle_part(self, msg):
        del self.userhosts[msg.src]
        del self.usermodes[msg.src]
        self._bot.nick_parted(msg.src)


    def handle_kick(self, msg):
        del self.userhosts[msg.args[0]]
        del self.usermodes[msg.args[0]]
        self._bot.nick_kicked(msg.args[0])


    def handle_mode(self, msg):
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
                    self.usermodes[param].add(change[1])
                    if param == self._nick and change[1] == 'o':
                        # Acquiring op is special to the bot
                        self._bot.acquired_ops()
                else:
                    self.usermodes[param].discard(change[1])


    def handle_nick(self, msg):
        self.userhosts[new_nick] = self.userhosts[old_nick]
        del self.userhosts[old_nick]
        self.usermodes[new_nick] = self.usermodes[old_nick]
        del self.usermodes[old_nick]

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
        if msg.src == conf['botnick']:
            # Grab my nick that someone left
            self.nick(conf['botnick'])
        del self.userhosts[msg.src]
        del self.usermodes[msg.src]
        if conf['detectsplits'] and re.match(r'\S+\.\S+ \S+\.\S+', msg.trailing):
            # Don't penalize on netsplit
            self._bot.netsplit(msg.src)
        else:
            self._bot.nick_quit(msg.src)


    def handle_notice(self, msg):
        if msg.args[0] != self._nick:
            # we ignore private notices
            self._bot.channel_notice(msg.src, msg.trailing)


    def handle_privmsg(self, msg):
        if msg.args[0] == self._nick:
            self._bot.private_message(msg.src, msg.trailing)
        else:
            self._bot.channel_message(msg.src, msg.trailing)


    def nick(self, nick):
        self.sendnow(f"NICK {nick}")


    def join(self, channel):
        self.sendnow(f"JOIN {channel}")


    def notice(self, target, text):
        for line in textwrap.wrap(text, width=400):
            self.send(f"NOTICE {target} :{line}")


    def mode(self, target, *modeinfo):
        for modes in grouper(modeinfo, self._maxmodes * 2):
            self.send(f"MODE {target} {' '.join([m for m in modes if m is not None])}")


    def chanmsg(self, text):
        for line in textwrap.wrap(text, width=400):
            self.send(f"PRIVMSG {conf['botchan']} :{line}")


    def who(self, chan):
        self.send(f"WHO {chan}")


SpecialItem = collections.namedtuple('SpecialItem', ['minlvl', 'itemlvl', 'lvlspread', 'kind', 'name', 'flavor'])


class Quest(object):
    def __init__(self, qp):
        self.questors = qp
        self.mode = None
        self.text = None
        self.qtime = None
        self.dests = []


class DawdleBot(object):
    # Commands in ALLOWALL can be used by anyone.
    # Commands in ALLOWPLAYERS can only be used by logged-in players
    # All other commands are admin-only
    ALLOWALL = ["help", "login", "register", "quest", "version"]
    ALLOWPLAYERS = ["align", "logout", "newpass", "removeme", "status", "whoami"]

    def __init__(self, db):
        self._irc = None             # irc connection
        self._players = db           # the player database
        self._state = 'disconnected' # connected, disconnected, or ready
        self._quest = None      # quest if any
        self._qtimer = 0        # time until next quest
        self._overrides = {}


    def randomly(self, key, odds):
        if key in self._overrides:
            return self._overrides[key]
        return random.randint(0, odds-1) < 1


    def randint(self, key, bottom, top):
        if key in self._overrides:
            return self._overrides[key]
        return random.randint(bottom, top)


    def randsample(self, key, seq, count):
        if key in self._overrides:
            return self._overrides[key]
        return random.sample(seq, count)


    def randchoice(self, key, seq):
        if key in self._overrides:
            return self._overrides[key]
        return random.choice(seq)


    def randshuffle(self, key, seq):
        if key in self._overrides:
            return self._overrides[key]
        random.shuffle(seq)


    def connected(self, irc):
        self._irc = irc
        self._state = 'connected'


    def chanmsg(self, text):
        self._irc.chanmsg(text)


    def logchanmsg(self, text):
        self._irc.chanmsg(text)
        with open(conf['modsfile'], "a") as ouf:
            ouf.write(f"[{time.strftime('%m/%d/%y %H:%M:%S')}] {text}\n")


    def notice(self, nick, text):
        self._irc.notice(nick, text)


    def ready(self):
        self._state = 'ready'
        autologin = []
        for p in self._players.online():
            if p.nick in self._irc.userhosts and p.userhost == self._irc.userhosts[p.nick]:
                autologin.append(p.name)
            else:
                p.online = False
                p.lastlogin = time.time()
        self._players.write()
        if autologin:
            self.chanmsg(f"{len(autologin)} user{plural(len(autologin), '', 's')} automatically logged in; accounts: {', '.join(autologin)}")
            if 'o' in self._irc.usermodes[self._irc._nick]:
                self.acquired_ops()
        else:
            self.chanmsg("0 users qualified for auto login.")
        self._rpcheck_task = asyncio.create_task(self.rpcheck_loop())
        self._qtimer = time.time() + self.randint('qtimer_init', 12, 24)*3600


    def acquired_ops(self):
        if not conf['voiceonlogin'] or self._state != 'ready':
            return

        online_nicks = set([p.nick for p in self._players.online()])
        add_voice = []
        remove_voice = []
        for u in self._irc.usermodes.keys():
            if 'v' in self._irc.usermodes[u]:
                if u not in online_nicks:
                    remove_voice.append(u)
            else:
                if u in online_nicks:
                    add_voice.append(u)
        if add_voice:
            self._irc.mode(conf['botchan'], *itertools.chain.from_iterable(zip(itertools.repeat('+v'), add_voice)))
        if remove_voice:
            self._irc.mode(conf['botchan'], *itertools.chain.from_iterable(zip(itertools.repeat('-v'), remove_voice)))


    def disconnected(self):
        self._irc = None
        self._state = 'disconnected'
        if self._rpcheck_task:
            self._rpcheck_task.cancel()
            self._rpcheck_task = None


    def self_joined(self):
        self._irc.who(conf['botchan'])


    def private_message(self, src, text):
        """Private message - handle as a command"""
        if text == '':
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
        player = self._players.from_nick(src)
        if player:
            self.penalize(player, "message", text)


    def channel_notice(self, src, text):
        player = self._players.from_nick(src)
        if player:
            self.penalize(player, "message", text)


    def nick_changed(self, old_nick, new_nick):
        player = self._players.from_nick(old_nick)
        if player:
            player.nick = new_nick
            self.penalize(player, "nick")


    def nick_parted(self, src):
        player = self._players.from_nick(src)
        if player:
            self.penalize(player, "part")
            player.online = False
            player.lastlogin = time.time()
            self._players.write()


    def netsplit(self, src):
        player = self._players.from_nick(src)
        if player:
            player.lastlogin = time.time()


    def nick_quit(self, src):
        player = self._players.from_nick(src)
        if player:
            self.penalize(player, "quit")
            player.online = False
            player.lastlogin = time.time()
            self._players.write()


    def nick_kicked(self, target):
        player = self._players.from_nick(src)
        if player:
            self.penalize(player, "kick")
            player.online = False
            player.lastlogin = time.time()
            self._players.write()


    def cmd_align(self, player, nick, args):
        if args not in ["good", "neutral", "evil"]:
            self.notice(nick, "Try: ALIGN good|neutral|evil")
            return
        player.alignment = args[0]
        self.notice(nick, f"You have converted to {args}")
        self._players.write()


    def cmd_help(self, player, nick, args):
        self.notice(nick, "Help?  But we are dawdling!")


    def cmd_version(self, player, nick, args):
        self.notice(nick, f"DawdleRPG v{VERSION} by Daniel Lowe")


    def cmd_whoami(self, player, nick, args):
        self.notice(nick, f"You are {player.name}, the level {player.level} {player.cclass}. Next level in {duration(player.nextlvl)}.")


    def cmd_status(self, player, nick, args):
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
                         f"{t.name}: Level {t.level} {t.cclass}; "
                         f"Status: {'Online' if t.online else 'Offline'}; "
                         f"TTL: {duration(t.nextlvl)}; "
                         f"Idled: {duration(t.idled)}; "
                         f"Item sum: {t.itemsum()}")


    def cmd_login(self, player, nick, args):
        if player:
            self.notice(nick, f"Sorry, you are already online as {player.name}")
            return
        if nick not in self._irc.userhosts:
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
        if conf['voiceonlogin'] and 'o' in self._irc.usermodes[self._irc._nick]:
            self._irc.mode(conf['botchan'], "+v", nick)
        player = self._players[pname]
        player.online = True
        player.nick = nick
        player.userhost = self._irc.userhosts[nick]
        player.lastlogin = time.time()
        self._players.write()
        self.chanmsg(f"{player.name}, the level {player.level} {player.cclass}, is now online from nickname {nick}. Next level in {duration(player.nextlvl)}.")
        self.notice(nick, f"Logon successful. Next level in {duration(player.nextlvl)}.")


    def cmd_register(self, player, nick, args):
        if player:
            self.notice(nick, f"Sorry, you are already online as {player.name}")
            return
        if nick not in self._irc.userhosts:
            self.notice(nick, f"Sorry, you aren't on {conf['botchan']}")
            return

        parts = args.split(' ', 2)
        if len(parts) != 3:
            self.notice(nick, "Try: REGISTER <username> <password> <char class>")
            self.notice(nick, "i.e. REGISTER Poseidon MyPassword God of the Sea")
            return
        pname, ppass, pclass = parts
        if pname in self._players:
            self.notice(nick, "Sorry, that character name is already in use.")
        elif pname == self._irc._nick or pname == conf['botnick']:
            self.notice(nick, "That character name cannot be registered.")
        elif len(pname) > 16:
            self.notice(nick, "Sorry, character names must be between 1 and 16 characters long.")
        elif len(pclass) > 30:
            self.notice(nick, "Sorry, character classes must be between 1 and 30 characters long.")
        elif '\001' in pname:
            self.notice(nick, "Sorry, character names may not include \\001.")
        else:
            player = self._players.new_player(pname, pclass, ppass)
            player.online = True
            player.nick = nick
            player.userhost = self._irc.userhosts[nick]
            if conf['voiceonlogin'] and 'o' in self._irc.usermodes[self._irc._nick]:
                self._irc.mode(conf['botchan'], "+v", nick)
            self.chanmsg(f"Welcome {nick}'s new player {pname}, the {pclass}!  Next level in {duration(player.nextlvl)}.")
            self.notice(nick, f"Success! Account {pname} created. You have {duration(player.nextlvl)} seconds of idleness until you reach level 1.")
            self.notice(nick, "NOTE: The point of the game is to see who can idle the longest. As such, talking in the channel, parting, quitting, and changing nicks all penalize you.")


    def cmd_removeme(self, player, nick, args):
        if args == "":
            self.notice(nick, "Try: REMOVEME <password>")
        elif not self._players.check_login(player.name, args):
            self.notice(nick, "Wrong password.")
        else:
            self.notice(nick, f"Account {player.name} removed.")
            self.chanmsg(f"{nick} removed their account, {player.name}, the {player.cclass}.")
            self._players.delete_player(player.name)
            if conf['voiceonlogin'] and 'o' in self._irc.usermodes[self._irc._nick]:
                self._irc.mode(conf['botchan'], "-v", nick)


    def cmd_newpass(self, player, nick, args):
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
        self.notice(nick, "You have been logged out.")
        player.online = False
        player.lastlogin = time.time()
        self._players.write()
        if conf['voiceonlogin'] and 'o' in self._irc.usermodes[self._irc._nick]:
                self._irc.mode(conf['botchan'], "-v", nick)
        self.penalize(player, "logout")


    def cmd_backup(self, player, nick, args):
        """Copy database file to a backup directory."""
        pass


    def cmd_chclass(self, player, nick, args):
        """Change another player's character class."""
        parts = args.split(' ', 1)
        if len(parts) != 2:
            self.notice(nick, "Try: CHCLASS <account> <new class>")
        elif parts[0] not in self._players:
            self.notice(nick, f"{parts[0]} is not a valid account.")
        else:
            self._players[parts[0]].cclass = parts[1]
            self.notice(nick, f"{parts[0]}'s character class is now '{parts[1]}'.")


    def cmd_chpass(self, player, nick, args):
        """Change another player's password."""
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
        else:
            self._players.rename_player(parts[0], parts[1])
            self.notice(nick, f"{parts[0]} is now known as {parts[1]}.")


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
        pass


    def cmd_die(self, player, nick, args):
        """Shut down the bot."""
        self.notice(nick, "Shutting down.")
        sys.exit(0)


    def cmd_info(self, player, nick, args):
        """Info on bot internals."""
        pass


    def cmd_jump(self, player, nick, args):
        """Switch to new IRC server."""
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
        pause_mode = not pause_mode
        if pause_mode:
            self.notice(nick, "Pause mode enabled.")
        else:
            self.notice(nick, "Pause mode disabled.")


    def cmd_rehash(self, player, nick, args):
        """Re-read configuration file."""
        pass


    def cmd_reloaddb(self, player, nick, args):
        """Reload the player database."""
        self._db.load()


    def cmd_restart(self, player, nick, args):
        """Restart from scratch."""
        pass


    def cmd_silent(self, player, nick, args):
        """Set silent mode."""
        silent_mode = not silent_mode
        if silent_mode:
            self.notice(nick, "Silent mode enabled.")
        else:
            self.notice(nick, "Silent mode disabled.")


    def cmd_hog(self, player, nick, args):
        self.hand_of_god(self._players.online())


    def cmd_push(self, player, nick, args):
        parts = args.split(' ')
        if len(parts) != 2 or not re.match(r'[+-]?\d+', parts[1]):
            self.notice(nick, "Try: PUSH <char name> <seconds>")
            return
        if parts[0] not in self._players:
            self.notice(nick, f"No such username {parts[0]}.")
            return
        player = self._players[parts[0]]
        amount = int(parts[1])
        if amount == 0:
            self.notice(nick, "That would not be interesting.")
            return

        if amount > player.nextlvl:
            self.notice(nick,
                        f"Time to level for {player.name} ({player.nextlvl}s) "
                        f"is lower than {amount}; setting TTL to 0.")
            amount = player.nextlvl
        player.nextlvl -= amount
        direction = 'towards' if amount > 0 else 'away from'
        self.notice(nick, f"{player.name} now reaches level {player.level + 1} in {duration(player.nextlvl)}.")
        self.logchanmsg(f"{nick} has pushed {player.name} {abs(amount)} seconds {direction} "
                        f"level {player.level + 1}.  {player.name} reaches next level "
                        f"in {duration(player.nextlvl)}.")


    def cmd_trigger(self, player, nick, args):
        """Trigger in-game events"""
        if args == 'calamity':
            self.calamity()
        elif args == 'godsend':
            self.godsend()
        elif args == 'hog':
            self.hand_of_god()
        elif args == 'teambattle':
            self.team_battle()
        elif args == 'evilness':
            self.evilness(self._players.online())
        elif args == 'goodness':
            self.goodness(self._players.online())
        elif args == 'battle':
            self.challenge_opp(player)


    def cmd_quest(self, player, nick, args):
        if self._quest is None:
            self.notice(nick, "There is no active quest.")
        elif self._quest.mode == 1:
            qp = self._quest.questors
            self.notice(nick,
                             f"{qp[0].name}, {qp[1].name}, {qp[2].name}, and {qp[3].name} "
                             f"are on a quest to {self._quest.text}. Quest to complete in "
                             f"{duration(self._quest.qtime - time.time())}.")
        elif self._quest.mode == 2:
            qp = self._quest.questors
            mapnotice = ''
            if 'mapurl' in conf:
                mapnotice = f" See {conf['mapurl']} to monitor their journey's progress."
            self.notice(nick,
                             f"{qp[0].name}, {qp[1].name}, {qp[2].name}, and {qp[3].name} "
                             f"are on a quest to {self._quest.text}. Participants must first reach "
                             f"({self._quest.dests[0][0]}, {self._quest.dests[0][1]}), then "
                             f"({self._quest.dests[1][0]}, {self._quest.dests[1][1]}).{mapnotice}")


    def penalize(self, player, kind, text=None):
        if self._quest and player in self._quest.questors:
            self.logchanmsg(player.name + "'s insolence has brought the wrath of "
                            "the gods down upon them.  Your great wickedness "
                            "burdens you like lead, drawing you downwards with "
                            "great force towards hell. Thereby have you plunged "
                            "15 steps closer to that gaping maw.")
            for p in self._players.online():
                gain = int(15 * (conf['rppenstep'] ** p.level))
                p.penquest += gain
                p.nextlvl += gain

            self._quest = None
            self._qtimer = time.time() + 12 * 3600

        penalty = PENALTIES[kind]
        if text:
            penalty *= len(text)
        penalty *= int(conf['rppenstep'] ** player.level)
        if 'limitpen' in conf and penalty > conf['limitpen']:
            penalty = conf['limitpen']
        setattr(player, "pen"+kind, getattr(player, "pen"+kind) + penalty)
        player.nextlvl += penalty
        if kind != 'quit':
            self.notice(player.nick, f"Penalty of {duration(penalty)} added to your timer for {PENDESC[kind]}.")

    def expire_splits(self):
        expiration = time.time() - conf['splitwait']
        for p in self._players.online():
            if p.nick not in self._irc.userhosts and p.lastlogin < expiration:
                print(f"Expiring {p.nick} who was logged in as {p.nick} but was lost in a netsplit.")
                p.online = False
        self._players.write()

    async def rpcheck_loop(self):
        try:
            last_time = time.time() - 1
            while self._state == 'ready':
                await asyncio.sleep(conf['self_clock'])
                now = time.time()
                self.rpcheck(now, int(now - last_time))
                last_time = now
        except Exception as err:
            print(err)
            sys.exit(2)


    def rpcheck(self, now, passed):
        if conf['detectsplits']:
            self.expire_splits()

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

        if not pause_mode:
            self._players.write()

        if now % 120 == 0 and self._quest:
            self.write_quest_file()
        if now % 36000 == 0:
            top = self._players.top_players()
            if top:
                self.chanmsg("Idle RPG Top Players:")
                for i, p in zip(itertools.count(), top):
                    self.chanmsg(f"{p.name}, the level {p.level} {p.cclass}, is #{i}! "
                                 f"Next level in {duration(p.nextlvl)}.")
        if now % 3600 == 0 and len([p for p in op if p.level >= 45]) > len(op) * 0.15:
            self.challenge_op()
        if now % 600 == 0 and pause_mode:
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

                self.chanmsg(f"{player.name}, the {player.cclass}, has attained level {player.level}! Next level in {duration(player.nextlvl)}.")
                self.find_item(player)
                # Players below level 25 have fewer battles.
                if player.level >= 25 or self.randomly('lowlevel_battle', 4):
                    self.challenge_opp(player)


    def hand_of_god(self, op):
        player = self.randchoice('hog_player', op)
        amount = int(player.nextlvl * (5 + self.randint('hog_amount', 0, 71))/100)
        if self.randomly('hog_effect', 5):
            self.logchanmsg(f"Verily I say unto thee, the Heavens have burst forth, and the blessed hand of God carried {player.name} {duration(amount)} toward level {player.level + 1}.")
            player.nextlvl -= amount
        else:
            self.logchanmsg(f"Thereupon He stretched out His little finger among them and consumed {player.name} with fire, slowing the heathen {duration(amount)} from level {player.level + 1}.")
            player.nextlvl += amount
        self.chanmsg(f"{player.name} reaches next level in {duration(player.nextlvl)}.")
        self._players.write()


    def find_item(self, player):
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
                                 f"found the level {ilvl} {si.name}!  {si.flavor}")
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
                             f"You found a level {level} {Player.ITEMDESC[item]}! "
                             f"Your current {Player.ITEMDESC[item]} is only "
                             f"level {old_level}, so it seems Luck is with you!")
            player.acquire_item(item, level)
            self._players.write()
        else:
            self.notice(player.nick,
                             f"You found a level {level} {Player.ITEMDESC[item]}. "
                             f"Your current {Player.ITEMDESC[item]} is level {old_level}, "
                             f"so it seems Luck is against you.  You toss the {Player.ITEMDESC[item]}.")


    def pvp_battle(self, player, opp, flavor_start, flavor_win, flavor_loss):
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
            self.logchanmsg(f"{player.name} [{playerroll}/{playersum}] has {flavor_start} "
                            f"{oppname} [{opproll}/{oppsum}] {flavor_win}! "
                            f"{duration(amount)} is removed from {player.name}'s clock.")
            player.nextlvl -= amount
            if player.nextlvl > 0:
                self.chanmsg(f"{player.name} reaches next level in {duration(player.nextlvl)}.")
            if opp is not None:
                if self.randomly('pvp_critical', {'g': 50, 'n': 35, 'e': 20}[player.alignment]):
                    penalty = int(((5 + self.randint('pvp_cs_penalty_pct', 0, 20))/100 * opp.nextlvl))
                    self.logchanmsg(f"{player.name} has dealt {opp.name} a Critical Strike! "
                                    f"{duration(penalty)} is added to {opp.name}'s clock.")
                    opp.nextlvl += penalty
                    self.chanmsg(f"{opp.name} reaches next level in {duration(opp.nextlvl)}.")
                elif player.level > 19 and self.randomly('pvp_swap_item', 25):
                    item = self.randchoice('pvp_swap_itemtype', Player.ITEMS)
                    playeritem = getattr(player, item)
                    oppitem = getattr(opp, item)
                    if oppitem > playeritem:
                        self.logchanmsg(f"In the fierce battle, {opp.name} dropped their level "
                                        f"{oppitem} {Player.ITEMDESC[item]}! {player.name} picks it up, tossing "
                                        f"their old level {playeritem} {Player.ITEMDESC[item]} to {opp.name}.")
                        player.swap_items(opp, item)
        else:
            # Losing
            loss = 10 if opp is None else max(7, int(opp.level / 7))
            amount = int((loss / 100)*player.nextlvl)
            self.logchanmsg(f"{player.name} [{playerroll}/{playersum}] has {flavor_start} "
                            f"{oppname} [{opproll}/{oppsum}] {flavor_loss}! {duration(amount)} is "
                            f"added to {player.name}'s clock.")
            player.nextlvl += amount
            self.chanmsg(f"{player.name} reaches next level in {duration(player.nextlvl)}.")

        if self.randomly('pvp_find_item', {'g': 50, 'n': 67, 'e': 100}[player.alignment]):
            self.chanmsg(f"While recovering from battle, {player.name} notices a glint "
                         f"in the mud. Upon investigation, they find an old lost item!")
            self.find_item(player)


    def challenge_opp(self, player):
        """Pit player against another random player."""
        op = self._players.online()
        op.remove(player)       # Let's not fight ourselves
        op.append(None)         # This is the bot opponent
        self.pvp_battle(player, self.randchoice('challenge_opp_choice', op), 'challenged', 'and won', 'and lost')


    def team_battle(self, op):
        if len(op) < 6:
            return
        op = self.randsample('team_battle_members', op, 6)
        team_a = sum([p.battleitemsum() for p in op[0:3]])
        team_b = sum([p.battleitemsum() for p in op[3:6]])
        gain = min([p.nextlvl for p in op[0:6]]) * 0.2
        roll_a = self.randint('team_a_roll', 0, team_a)
        roll_b = self.randint('team_b_roll', 0, team_b)
        if roll_a >= roll_b:
            self.logchanmsg(f"{op[0].name}, {op[1].name}, and {op[2].name} [{roll_a}/{team_a}] "
                            f"have team battled {op[3].name}, {op[4].name}, and {op[5].name} "
                            f"[{roll_b}/{team_b}] and won!  {duration(gain)} is removed from their clocks.")
            for p in op[0:3]:
                p.nextlvl -= gain
        else:
            self.logchanmsg(f"{op[0].name}, {op[1].name}, and {op[2].name} [{roll_a}/{team_a}] "
                            f"have team battled {op[3].name}, {op[4].name}, and {op[5].name} "
                            f"[{roll_b}/{team_b}] and lost!  {duration(gain)} is added to their clocks.")
            for p in op[0:3]:
                p.nextlvl += gain


    def calamity(self):
        player = self.randchoice('calamity_target', self._players.online())
        if not player:
            return

        if self.randomly('calamity_item_damage', 10):
            # Item damaging calamity
            item = self.randchoice('calamity_item', Player.ITEMS)
            if item == "ring":
                msg = f"{player.name} accidentally smashed their ring with a hammer!"
            elif item == "amulet":
                msg = f"{player.name} fell, chipping the stone in their amulet!"
            elif item == "charm":
                msg = f"{player.name} slipped and dropped their charm in a dirty bog!"
            elif item == "weapon":
                msg = f"{player.name} left their weapon out in the rain to rust!"
            elif item == "helm":
                msg = f"{player.name}'s helm was touched by a rust monster!"
            elif item == "tunic":
                msg = f"{player.name} spilled a level 7 shrinking potion on their tunic!"
            elif item == "gloves":
                msg = f"{player.name} dipped their gloved fingers in a pool of acid!"
            elif item == "leggings":
                msg = f"{player.name} burned a hole through their leggings while ironing them!"
            elif item == "shield":
                msg = f"{player.name}'s shield was damaged by a dragon's fiery breath!"
            elif item == "boots":
                msg = f"{player.name} stepped in some hot lava!"
            self.logchanmsg(msg + f" {player.name}'s {Player.ITEMDESC[item]} loses 10% of its effectiveness.")
            setattr(player, item, int(getattr(player, item) * 0.9))
            return

        # Level setback calamity
        amount = int(self.randint('calamity_setback_pct', 5, 13) / 100 * player.nextlvl)
        player.nextlvl += amount
        # TODO: reading this file every time is silly
        with open(conf['eventsfile']) as inf:
            lines = [line.rstrip() for line in inf.readlines() if line.startswith("C ")]
        action = self.randchoice('calamity_action', lines)[2:]
        self.logchanmsg(f"{player.name} {action}! This terrible calamity has slowed them "
                        f"{duration(amount)} from level {player.level + 1}.")
        if player.nextlvl > 0:
            self.chanmsg(f"{player.name} reaches next level in {duration(player.nextlvl)}.")


    def godsend(self):
        player = self.randchoice('godsend_target', self._players.online())
        if not player:
            return

        if self.randomly('godsend_item_improve', 10):
            # Item improving godsend
            item = self.randchoice('godsend_item', Player.ITEMS)
            if item == "ring":
                msg = f"{player.name} dipped their ring into a sacred fountain!"
            elif item == "amulet":
                msg = f"{player.name}'s amulet was blessed by a passing cleric!"
            elif item == "charm":
                msg = f"{player.name}'s charm ate a bolt of lightning!"
            elif item == "weapon":
                msg = f"{player.name} sharpened the edge of their weapon!"
            elif item == "helm":
                msg = f"{player.name} polished their helm to a mirror shine."
            elif item == "tunic":
                msg = f"A magician cast a spell of Rigidity on {player.name}'s tunic!"
            elif item == "gloves":
                msg = f"{player.name} lined their gloves with a magical cloth!"
            elif item == "leggings":
                msg = f"The local wizard imbued {player.name}'s pants with a Spirit of Fortitude!"
            elif item == "shield":
                msg = f"{player.name} reinforced their shield with a dragon's scale!"
            elif item == "boots":
                msg = f"A sorceror enchanted {player.name}'s boots with Swiftness!"

            self.logchanmsg(msg + f" {player.name}'s {Player.ITEMDESC[item]} gains 10% effectiveness.")
            setattr(player, item, int(getattr(player, item) * 1.1))
            return

        # Level godsend
        amount = int(self.randint('godsend_amount_pct', 5, 13) / 100 * player.nextlvl)
        player.nextlvl -= amount
        # TODO: reading this file every time is silly
        with open(conf['eventsfile']) as inf:
            lines = [line.rstrip() for line in inf.readlines() if line.startswith("G ")]
        action = self.randchoice('godsend_action', lines)[2:]
        self.logchanmsg(f"{player.name} {action}! This wondrous godsend has accelerated them "
                        f"{duration(amount)} towards level {player.level + 1}.")
        if player.nextlvl > 0:
            self.chanmsg(f"{player.name} reaches next level in {duration(player.nextlvl)}.")


    def evilness(self, op):
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
                self.logchanmsg(f"{player.name} stole {target.name}'s level {getattr(player, item)} "
                                f"{Player.ITEMDESC[item]} while they were sleeping!  {player.name} "
                                f"leaves their old level {getattr(target, item)} {Player.ITEMDESC[item]} "
                                f"behind, which {target.name} then takes.")
            else:
                self.notice(player.nick,
                            f"You made to steal {target.name}'s {Player.ITEMDESC[item]}, "
                            f"but realized it was lower level than your own.  You creep "
                            f"back into the shadows.")
        else:
            amount = int(player.nextlvl * self.randint('evilness_penalty_pct', 1,6) / 100)
            player.nextlvl += amount
            self.logchanmsg(f"{player.name} is forsaken by their evil god. {duration(amount)} is "
                              f"added to their clock.")
            if player.nextlvl > 0:
                self.chanmsg(f"{player.name} reaches next level in {duration(player.nextlvl)}.")

    def goodness(self, op):
        good_p = [p for p in op if p.alignment == 'g']
        if len(good_p) < 2:
            return
        players = self.randsample('goodness_players', good_p, 2)
        gain = self.randint('goodness_gain_pct', 5, 13)
        self.logchanmsg(f"{players[0].name} and {players[1].name} have not let the iniquities "
                        f"of evil people poison them. Together have they prayed to their god, "
                        f"and light now shines down upon them. {gain}% of their time is removed "
                        f"from their clocks.")
        for player in players:
            player.nextlvl = int(player.nextlvl * (1 - gain / 100))
            if player.nextlvl > 0:
                self.chanmsg(f"{player.name} reaches next level in {duration(player.nextlvl)}.")


    def move_players(self):
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
                    self.chanmsg(f"{p.name} encounters {combatant.name} and bows humbly.")
                elif self.randomly('move_player_combat', len(op)):
                    self.pvp_battle(p, combatant,
                                    'come upon',
                                    'and taken them in combat',
                                    'and been defeated in combat')
                    del combatants[(p.posx, p.posy)]
            else:
                combatants[(p.posx, p.posy)] = p


    def quest_start(self, now):
        latest_login_time = now - 36000
        qp = [p for p in self._players.online() if p.level > 24 and p.lastlogin < latest_login_time]
        if len(qp) < 4:
            return
        qp = self.randsample('quest_members', qp, 4)
        # TODO: reading this file every time is silly
        with open(conf['eventsfile']) as inf:
            lines = [line.rstrip() for line in inf.readlines() if line.startswith("Q")]
        questconf = self.randchoice('quest_selection', lines)
        match = (re.match(r'^Q(1) (.*)', questconf) or
                 re.match(r'^Q(2) (\d+) (\d+) (\d+) (\d+) (.*)', questconf))
        if not match:
            return
        self._quest = Quest(qp)
        if match[1] == '1':
            quest_time = self.randint('quest_time', 12, 24)*3600
            self._quest.mode = 1
            self._quest.text = match[2]
            self._quest.qtime = time.time() + quest_time
            self.chanmsg(f"{qp[0].name}, {qp[1].name}, {qp[2].name}, and {qp[3].name} have "
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
            self.chanmsg(f"{qp[0].name}, {qp[1].name}, {qp[2].name}, and {qp[3].name} have "
                         f"been chosen by the gods to {self._quest.text}.  Participants must first "
                         f"reach ({self._quest.dests[0][0]},{self._quest.dests[0][1]}), "
                         f"then ({self._quest.dests[1][0]},{self._quest.dests[1][1]}).{mapnotice}")


    def quest_check(self, now):
        if self._quest is None:
            if now >= self._qtimer:
                self.quest_start(now)
        elif self._quest.mode == 1:
            if now >= self._quest.qtime:
                qp = self._quest.questors
                self.logchanmsg(f"{qp[0].name}, {qp[1].name}, {qp[2].name}, and {qp[3].name} "
                                f"have blessed the realm by completing their quest! 25% of "
                                f"their burden is eliminated.")
                for q in qp:
                    q.nextlvl = int(q.nextlvl * 0.75)
                self._quest = None
                self._qtimer = now + 6*3600
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
                    self.chanmsg(f"{qp[0].name}, {qp[1].name}, {qp[2].name}, and {qp[3].name} "
                                 f"have reached a landmark on their journey! {dests_left} "
                                 f"landmark{plural(dests_left, '', 's')} "
                                 f"remain{plural(dests_left, 's', '')}.")
                else:
                    self.logchanmsg(f"{qp[0].name}, {qp[1].name}, {qp[2].name}, and {qp[3].name} "
                                    f"have completed their journey! 25% of "
                                    f"their burden is eliminated.")
                    for q in qp:
                        q.nextlvl = int(q.nextlvl * 0.75)
                    self._quest = None
                    self._qtimer = now + 6*3600
                self.write_quest_file()


    def write_quest_file(self):
        if not conf['writequestfile']:
            return
        with open(conf['questfilename'], 'w') as ouf:
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
    db = PlayerDB(IdleRPGPlayerStore(conf["dbfile"]))
    if db.exists():
        db.load()
    else:
        first_setup()

    bot = DawdleBot(db)
    client = IRCClient(bot)
    asyncio.run(mainloop(client))

if __name__ == "__main__":
    start_bot()
