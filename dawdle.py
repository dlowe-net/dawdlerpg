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
import logging
import os
import os.path
import random
import re
import sqlite3
import sys
import time

from hmac import compare_digest as compare_hash

log = logging.getLogger()

VERSION = "1.0.0"

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


def duration(secs):
    d, secs = int(secs / 86400), secs % 86400
    h, secs = int(secs / 3600), secs % 3600
    m, secs = int(secs / 60), secs % 60
    return f"{d} day{'' if d == 1 else 's'}, {h:02d}:{m:02d}:{int(secs):02d}"


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
        p.pw = crypt.crypt(ppass, crypt.mksalt())
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


class PlayerDB(object):

    FIELDS = ["name", "cclass", "pw", "isadmin", "level", "nextlvl", "nick", "userhost", "online", "idled", "posx", "posy", "penmessage", "pennick", "penpart", "penkick", "penquit", "penquest", "penlogout", "created", "lastlogin", "alignment", "amulet", "amuletname", "charm", "charmname", "helm", "helmname", "boots", "bootsname", "gloves", "glovesname", "ring", "ringname", "leggings", "leggingsname", "shield", "shieldname", "tunic", "tunicname", "weapon", "weaponname"]


    @staticmethod
    def dict_factory(cursor, row):
        d = {}
        for idx, col in enumerate(cursor.description):
            d[col[0]] = row[idx]
        return d


    def __init__(self, dbpath):
        self._dbpath = dbpath
        self._db = None
        self._players = {}

    def __getitem__(self, pname):
        return self._players[pname]


    def __contains__(self, pname):
        return pname in self._players

    def _connect(self):
        if self._db is None:
            self._db = sqlite3.connect(self._dbpath)
            self._db.row_factory = PlayerDB.dict_factory

        return self._db


    def close(self):
        """Close the underlying db.  Used for testing."""
        self._db.close()

    def exists(self):
        return os.path.exists(self._dbpath)


    def load(self):
        """Load all players from database into memory"""
        self._players = {}
        with self._connect() as con:
            cur = con.execute("select * from players")
            for d in cur.fetchall():
                self._players[d['name']] = Player.from_dict(d)


    def write(self):
        """Write all players into database"""
        with self._connect() as cur:
            update_fields = ",".join(f"{k}=:{k}" for k in PlayerDB.FIELDS)
            cur.executemany(f"update players set {update_fields} where name=:name",
                            [vars(p) for p in self._players.values()])


    def create(self):
        with self._connect() as cur:
            cur.execute(f"create table players ({','.join(PlayerDB.FIELDS)})")


    def new_player(self, pname, pclass, ppass):
        global conf

        if pname in self._players:
            raise KeyError

        pclass = pclass[:30]

        p = Player.new_player(pname, pclass, ppass)
        self._players[pname] = p

        with self._connect() as cur:
            d = vars(p)
            cur.execute(f"insert into players values ({('?, ' * len(d))[:-2]})",
                        [d[k] for k in PlayerDB.FIELDS])
            cur.commit()

        return p


    def delete_player(self, pname):
        del self._players[pname]
        with self._connect() as cur:
            cur.execute("delete from players where name = ?", (pname,))
            cur.commit()


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
        self.send(f"NICK {conf['botnick']}")
        self.send(f"USER {conf['botuser']} 0 * :{conf['botrlnm']}")
        self._bot.connected(self)
        while True:
            line = await reader.readline()
            if not line:
                self._bot.disconnected()
                break
            # Assume utf-8 encoding, fall back to latin-1, which has no invalid encodings from bytes.
            try:
                line = str(line, encoding='utf8')
            except UnicodeDecodeError:
                line = str(line, encoding='latin-1')
            line = line.rstrip('\r\n')
            if conf["debug"]:
                print("<- ", line)
            msg = self.parse_message(line)
            self.dispatch(msg)


    def send(self, s):
        if conf["debug"]:
            print("-> ", s)
        self._writer.write(bytes(s+"\r\n", encoding='utf8'))


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


    def dispatch(self, msg):
        if hasattr(self, "handle_"+msg.cmd.lower()):
            getattr(self, "handle_"+msg.cmd.lower())(msg)


    def handle_ping(self, msg):
        self.send(f"PONG :{msg.trailing}")


    def handle_376(self, msg):
        """RPL_ENDOFMOTD - server is ready"""
        print("mode")
        self.mode(conf['botnick'], conf['botmodes'])
        self.join(conf['botchan'])

    def handle_422(self, msg):
        """ERR_NOTMOTD - server is ready, but without a MOTD"""
        self.mode(conf['botnick'], conf['botmodes'])
        self.join(conf['botchan'])


    def handle_353(self, msg):
        """RPL_NAMREPLY - names in the channel"""
        for nick in msg.trailing.split(' '):
            self._bot.nick_joined(nick)


    def handle_366(self, msg):
        """RPL_ENDOFNAMES - the actual end of channel joining"""
        # We know who is in the channel now
        if 'botopcmd' in conf:
            self.send(re.sub(r'%botnick%', self._nick, conf['botopcmd']))
        self._bot.ready()


    def handle_433(self, msg):
        """ERR_NICKNAME_IN_USE - try another nick"""
        self._nick = self._nick + "0"
        self.nick(self._nick)

    def handle_join(self, msg):
        if msg.src != self._nick:
            self._bot.nick_joined(msg.src)


    def handle_part(self, msg):
        self._bot.nick_parted(msg.src)


    def handle_kick(self, msg):
        self._bot.nick_kicked(msg.args[0])


    def handle_nick(self, msg):
        if msg.src == self._nick:
            # Update my nick
            self._nick = msg.args[0]
        else:
            if msg.src == conf['botnick']:
                # Grab my nick that someone left
                self.nick(conf['botnick'])
            self._bot.nick_changed(self, msg.src, msg.args[0])


    def handle_quit(self, msg):
        if msg.src == conf['botnick']:
            # Grab my nick that someone left
            self.nick(conf['botnick'])
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
        self.send(f"NICK {nick}")

    def join(self, channel):
        self.send(f"JOIN {channel}")


    def notice(self, target, text):
        self.send(f"NOTICE {target} :{text}")


    def mode(self, target, *modeinfo):
        self.send(f"MODE {target} {' '.join(modeinfo)}")


    def chanmsg(self, text):
        self.send(f"PRIVMSG {conf['botchan']} :{text}")


SpecialItem = collections.namedtuple('SpecialItem', ['minlvl', 'itemlvl', 'lvlspread', 'kind', 'name', 'flavor'])
Quest = collections.namedtuple('Quest', ['questors', 'mode', 'text', 'qtime', 'p1', 'p2', 'stage'])

class DawdleBot(object):
    # Commands in ALLOWALL can be used by anyone.
    # Commands in ALLOWPLAYERS can only be used by logged-in players
    # All other commands are admin-only
    ALLOWALL = ["help", "login", "register", "quest", "version", "eval"]
    ALLOWPLAYERS = ["align", "logout", "newpass", "removeme", "status", "whoami"]

    def __init__(self, db):
        self._irc = None             # irc connection
        self._onchan = []            # all players in the channel
        self._players = db           # the player database
        self._state = 'disconnected' # connected, disconnected, or ready
        self._quest = None      # quest if any
        self._qtimer = 0        # time until next quest

    def connected(self, irc):
        self._irc = irc
        self._state = 'connected'


    def ready(self):
        self._state = 'ready'
        self._rpcheck_task = asyncio.create_task(self.rpcheck_loop())
        self._qtimer = time.time() + random.randrange(12, 24)*3600


    def disconnected(self, evt):
        self._irc = None
        self._onchan = []
        self._state = 'disconnected'
        if self._rpcheck_task:
            self._rpcheck_task.cancel()
            self._rpcheck_task = None


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
                self._irc.notice(src, "You are not logged in.")
                return
        elif cmd not in DawdleBot.ALLOWALL:
            if player is None or not player.isadmin:
                self._irc.notice(src, f"You cannot do '{cmd}'.")
                return
        if hasattr(self, f'cmd_{cmd}'):
            getattr(self, f'cmd_{cmd}')(player, src, args)
        else:
            self._irc.notice(src, f"'{cmd} isn't actually a command.")


    def channel_message(self, src, text):
        player = self._players.from_nick(src)
        if player:
            self.penalty(player, "message")


    def channel_notice(self, src, text):
        player = self._players.from_nick(src)
        if player:
            self.penalty(player, "message")


    def self_joined(self, src):
        if 'botopcmd' in conf:
            send(conf['botopcmd'])


    def names_done(self):
        pass


    def nick_changed(self, old_nick, new_nick):
        self._onchan.remove(old_nick)
        self._onchan.append(new_nicK)
        player = self._players.from_nick(src)
        if player:
            player.nick = new_nick
            self.penalty(player, "nick")


    def nick_joined(self, src):
        self._onchan.append(src)


    def nick_parted(self, src):
        self._onchan.remove(src)
        player = self._players.from_nick(src)
        if player:
            self.penalty(player, "part")
            player.online = False
            self._players.write()


    def nick_quit(self, src):
        self._onchan.remove(src)
        player = self._players.from_nick(src)
        if player:
            self.penalty(player, "quit")
            player.online = False
            self._players.write()


    def nick_kicked(self, target):
        self._onchan.remove(src)
        player = self._players.from_nick(src)
        if player:
            self.penalty(player, "kick")
            player.online = False
            self._players.write()


    def cmd_align(self, player, nick, args):
        if args not in ["good", "neutral", "evil"]:
            self._irc.notice(nick, "Try: ALIGN good|neutral|evil")
            return
        player.alignment = args[0]
        self._irc.notice(nick, f"You have converted to {args}")
        self._players.write()


    def cmd_help(self, player, nick, args):
        self._irc.notice(nick, "Help?  But we are dawdling!")


    def cmd_version(self, player, nick, args):
        self._irc.notice(nick, f"DawdleRPG v{VERSION} by Daniel Lowe")


    def cmd_whoami(self, player, nick, args):
        self._irc.notice(nick, f"You are {player.name}, the level {player.level} {player.cclass}. Next level in {duration(player.nextlvl)}.")


    def cmd_login(self, player, nick, args):
        if player:
            self._irc.notice(nick, f"Sorry, you are already online as {player.name}")
            return
        if nick not in self._onchan:
            self._irc.notice(nick, f"Sorry, you aren't on {conf['botchan']}")
            return

        parts = args.split(' ', 1)
        if len(parts) != 2:
            self._irc.notice(nick, "Try: LOGIN <username> <password>")
            return
        pname, ppass = parts
        if pname not in self._players:
            self._irc.notice(nick, f"Sorry, no such account name.  Note that account names are case sensitive.")
            return
        if not self._players.check_login(pname, ppass):
            self._irc.notice(nick, f"Wrong password.")
            return
        # Success!
        if conf['voiceonlogin']:
            self._irc.mode(conf['botchan'], "+v", nick)
        player = self._players[pname]
        player.online = True
        player.nick = nick
        player.lastlogin = time.time()
        self._players.write()
        self._irc.chanmsg(f"{player.name}, the level {player.level} {player.cclass}, is now online from nickname {nick}. Next level in {duration(player.nextlvl)}.")
        self._irc.notice(nick, f"Logon successful. Next level in {duration(player.nextlvl)}.")


    def cmd_register(self, player, nick, args):
        if player:
            self._irc.notice(nick, f"Sorry, you are already online as {player.name}")
            return
        if nick not in self._onchan:
            self._irc.notice(nick, f"Sorry, you aren't on {conf['botchan']}")
            return

        parts = args.split(' ', 2)
        if len(parts) != 3:
            self._irc.notice(nick, "Try: REGISTER <username> <password> <char class>")
            self._irc.notice(nick, "i.e. REGISTER Poseidon MyPassword God of the Sea")
            return
        pname, ppass, pclass = parts
        if pname in self._players:
            self._irc.notice(nick, "Sorry, that character name is already in use.")
        elif pname == self._irc._nick or pname == conf['botnick']:
            self._irc.notice(nick, "That character name cannot be registered.")
        elif len(pname) > 16:
            self._irc.notice(nick, "Sorry, character names must be between 1 and 16 characters long.")
        elif len(pclass) > 30:
            self._irc.notice(nick, "Sorry, character classes must be between 1 and 30 characters long.")
        elif '\001' in pname:
            self._irc.notice(nick, "Sorry, character names may not include \\001.")
        else:
            player = self._players.new_player(pname, pclass, ppass)
            player.online = True
            player.nick = nick
            self._irc.chanmsg(f"Welcome {nick}'s new player {pname}, the {pclass}!  Next level in {duration(player.nextlvl)}.")
            self._irc.notice(nick, f"Success! Account {pname} created. You have {duration(player.nextlvl)} seconds of idleness until you reach level 1.")
            self._irc.notice(nick, "NOTE: The point of the game is to see who can idle the longest. As such, talking in the channel, parting, quitting, and changing nicks all penalize you.")


    def cmd_removeme(self, player, nick, args):
        if args == "":
            self._irc.notice(nick, "Try: REMOVEME <password>")
        elif not self._players.check_login(player.name, args):
            self._irc.notice(nick, "Wrong password.")
        else:
            self._irc.notice(nick, f"Account {player.name} removed.")
            self._irc.chanmsg(f"{nick} removed their account, {player.name}, the {player.cclass}.")
            self._players.delete_player(player.name)


    def cmd_newpass(self, player, nick, args):
        parts = args.split(' ', 1)
        if len(parts) != 2:
            self._irc.notice(nick, "Try: NEWPASS <old password> <new password>")
        elif not self._players.check_login(player.name, parts[0]):
            self._irc.notice(nick, "Wrong password.")
        else:
            player.set_password(parts[1])
            self._players.write()
            self._irc.notice(nick, "Your password was changed.")


    def cmd_logout(self, player, nick, args):
        self._irc.notice(nick, "You have been logged out.")
        player.online = False
        self._players.write()
        self.penalty(player, "logout")


    def cmd_hog(self, player, nick, args):
        self.hand_of_god()


    def cmd_push(self, player, nick, args):
        parts = args.split(' ')
        if len(parts) != 2 or not re.match(r'[+-]?\d+', parts[1]):
            self._irc.notice(nick, "Try: PUSH <char name> <seconds>")
            return
        if parts[0] not in self._players:
            self._irc.notice(nick, f"No such username {parts[0]}.")
            return
        player = self._players[parts[0]]
        amount = int(parts[1])
        if amount == 0:
            self._irc.notice(nick, "That would not be interesting.")
            return

        if amount > player.nextlvl:
            self._irc.notice(nick,
                             f"Time to level for {player.name} ({player.nextlvl}s) "
                             f"is lower than {amount}; setting TTL to 0.")
            amount = player.nextlvl
        player.nextlvl -= amount
        direction = 'towards' if amount > 0 else 'away from'
        self._irc.notice(nick, f"{player.name} now reaches level {player.level + 1} in {duration(player.nextlvl)}.")
        self._irc.chanmsg(f"{nick} has pushed {player.name} {abs(amount)} seconds {direction} "
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
            self.evilness()
        elif args == 'goodness':
            self.goodness()
        elif args == 'battle':
            self.challenge_opp(player)


    def cmd_quest(self, player, nick, args):
        if self._quest is None:
            self._irc.notice(nick, "There is no active quest.")
        elif self._quest.mode == 1:
            qp = quest.questors
            self._irc.notice(nick,
                             f"{qp[0].name}, {qp[1].name}, {qp[2].name}, and {qp[3].name} "
                             f"are on a quest to {quest.text}. Quest to complete in "
                             f"{duration(quest.qtime - time.time())}.")
        elif self._quest.mode == 2:
            qp = quest.questors
            mapnotice = ''
            if 'mapurl' in conf:
                mapnotice = f" See {conf['mapurl']} to monitor their journey's progress."
            self._irc.notice(nick,
                             f"{qp[0].name}, {qp[1].name}, {qp[2].name}, and {qp[3].name} "
                             f"are on a quest to {quest.text}. Participants must first reach "
                             f"({quest.dests[0][0]}, {quest.dest[0][1]}), then "
                             f"({quest.dests[1][0]}, {quest.dest[1][1]}).{mapnotice}")


    def penalize(self, player, kind, text=None):
        if self._quest:
            if player in self._quest.questors:
                self._irc.chanmsg(player.name + "'s cowardice has brought the wrath of the gods "
                                  "down upon them.  All their great wickedness makes "
                                  "them heavy with lead, and to tend downwards with "
                                  "great weight and pressure towards hell. Therefore "
                                  "have they drawn themself 30 steps closer to that "
                                  "gaping maw.")
                gain = int(30 * (conf['rppenstep'] ** player.level))
                player.penquest += gain
                player.nextlvl += gain
                self._quest = None
                self._qtimer = time.time() + 12 * 3600

        penalty = PENALITIES[kind]
        if text:
            penalty *= len(text)
        penality *= conf['rppenstep'] ** player.level
        if 'limitpen' in conf and penalty > conf['limitpen']:
            penalty = conf['limitpen']
        setattr(player, "pen"+kind, getattr(player, "pen"+kind) + penalty)
        if kind != 'quit':
            self._irc.notice(player.nick, f"Penalty of {duration(penalty)} added to your timer for {PENDESC[kind]}.")


    async def rpcheck_loop(self):
        try:
            last_time = time.time() - 1
            while self._state == 'ready':
                await asyncio.sleep(conf['self_clock'])
                now = time.time()
                self.rpcheck(int(now - last_time))
                last_time = now
        except Exception as err:
            print(err)
            sys.exit(2)

    def rpcheck(self, passed):
        online_players = self._players.online()
        online_count = 0
        evil_count = 0
        good_count = 0
        for player in online_players:
            online_count += 1
            if player.alignment == 'e':
                evil_count += 1
            elif player.alignment == 'g':
                good_count += 1
        if random.randrange(20 * 86400/conf['self_clock']) < online_count:
            self.hand_of_god()
        if random.randrange(24 * 86400/conf['self_clock']) < online_count:
            self.team_battle()
        if random.randrange(8 * 86400/conf['self_clock']) < online_count:
            self.calamity()
        if random.randrange(4 * 86400/conf['self_clock']) < online_count:
            self.godsend()
        if random.randrange(8 * 86400/conf['self_clock']) < evil_count:
            self.evilness()
        if random.randrange(12 * 86400/conf['self_clock']) < good_count:
            self.goodness()

        self.move_players()
        self.quest_check()

        if not pause_mode:
            self._players.write()

        for player in online_players:
            player.nextlvl -= passed
            player.idled += passed
            if player.nextlvl < 1:
                player.level += 1
                if player.level > 60:
                    # linear after level 60
                    player.nextlvl = int(conf['rpbase'] * (conf['rpstep'] ** 60 + (86400 * (player.level - 60))))
                else:
                    player.nextlvl = int(conf['rpbase'] * (conf['rpstep'] ** player.level))

                self._irc.chanmsg(f"{player.name}, the {player.cclass}, has attained level {player.level}! Next level in {duration(player.nextlvl)}.")
                self.find_item(player)
                # Players below level 25 have less battles.
                if player.level >= 25 or random.randrange(4) < 1:
                    self.challenge_opp(player)


    def hand_of_god(self):
        player = random.choice(self._players.online())
        amount = int(player.nextlvl * (5 + random.randrange(71))/100)
        if random.randrange(5) > 0:
            self._irc.chanmsg(f"Verily I say unto thee, the Heavens have burst forth, and the blessed hand of God carried {player.name} {duration(amount)} toward level {player.level + 1}.")
            player.nextlvl -= amount
        else:
            self._irc.chanmsg(f"Thereupon He stretched out His little finger among them and consumed {player.name} with fire, slowing the heathen {duration(amount)} from level {player.level + 1}.")
            player.nextlvl += amount
        self._irc.chanmsg(f"{player.name} reaches next level in {duration(player.nextlvl)}.")

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
            if player.level >= si.minlvl and random.randrange(40) < 1:
                ilvl = si.itemlvl + random.randrange(si.lvlspread)
                player.acquire_item(si.kind, ilvl, si.name)
                self._irc.notice(player.nick,
                                 f"The light of the gods shines down upon you! You have "
                                 f"found the level {ilvl} {si.name}!  {si.flavor}")
                return

        item = random.choice(Player.ITEMS)
        level = 0
        for num in range(1, int(player.level * 1.5)):
            if random.randrange(int(1.4**(num / 4))) < 1:
                level = num
        old_level = int(getattr(player, item))
        if level > old_level:
            self._irc.notice(player.nick,
                             f"You found a level {level} {Player.ITEMDESC[item]}! "
                             f"Your current {Player.ITEMDESC[item]} is only "
                             f"level {old_level}, so it seems Luck is with you!")
            player.acquire_item(item, level)
            self._players.write()
        else:
            self._irc.notice(player.nick,
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
        playerroll = random.randrange(playersum)
        opproll = random.randrange(oppsum)
        if playerroll >= opproll:
            gain = 20 if oppname == conf['botnick'] else int(opp.level / 4)
            if gain < 7:
                gain = 7
            amount = int((gain / 100)*player.nextlvl)
            self._irc.chanmsg(f"{player.name} [{playerroll}/{playersum}] has {flavor_start} "
                              f"{oppname} [{opproll}/{oppsum}] {flavor_win}! "
                              f"{duration(amount)} is removed from {player.name}'s clock.")
            player.nextlvl -= amount
            if player.nextlvl > 0:
                self._irc.chanmsg(f"{player.name} reaches next level in {duration(player.nextlvl)}.")
            if opp is not None:
                csfactor = 35
                if player.alignment == 'g':
                    csfactor = 50
                elif player.alignment == 'e':
                    csfactor = 20
                if random.randrange(csfactor) < 1:
                    penalty = int(((5 + random.randrange(20))/100 * opp.nextlvl))
                    self._irc.chanmsg(f"{player.name} has dealt {opp.name} a Critical Strike! "
                                      f"{duration(penalty)} is added to {opp.name}'s clock.")
                    opp.nextlvl += penalty
                    self._irc.chanmsg(f"{opp.name} reaches next level in {duration(opp.nextlvl)}.")
                elif player.level > 19 and random.randrange(25) < 1:
                    item = random.choice(Player.ITEMS)
                    playeritem = getattr(player, item)
                    oppitem = getattr(opp, item)
                    if oppitem > playeritem:
                        self._irc.chanmsg(f"In the fierce battle, {opp.name} dropped their level "
                                          f"{oppitem} {Player.ITEMDESC[item]}! {player.name} picks it up, tossing "
                                          f"their old level {playeritem} {Player.ITEMDESC[item]} to {opp.name}.")
                        player.swap_items(opp, item)
        else:
            # Losing
            loss = 10 if oppname == conf['botnick'] else int(opp.level / 7)
            if loss < 7:
                loss = 7
            amount = int((loss / 100)*player.nextlvl)
            self._irc.chanmsg(f"{player.name} [{playerroll}/{playersum}] has {flavor_start} "
                              f"{oppname} {flavor_loss}! {duration(amount)} is "
                              f"added to {player.name}'s clock.")
            player.nextlvl += amount
            self._irc.chanmsg(f"{player.name} reaches next level in {duration(player.nextlvl)}.")

        idfactor = 67
        if player.alignment == 'g':
            idfactor = 50
        elif player.alignment == 'e':
            idfactor = 100
        if random.randrange(idfactor) < 1:
            self._irc.chanmsg(f"While recovering from battle, {player.name} notices a glint "
                              f"in the mud. Upon investigation, they find an old lost item!")
            self.find_item(player)


    def challenge_opp(self, player):
        """Pit player against another random player."""
        op = self._players.online()
        op.remove(player)       # Let's not fight ourselves
        op.append(None)         # This is the bot opponent
        self.pvp_battle(player, random.choice(op), 'challenged', 'and won', 'and lost')


    def team_battle(self):
        op = self._players.online()
        if len(op) < 6:
            return
        op = random.shuffle(op)
        team_a = sum([p.battleitemsum() for p in op[0:3]])
        team_b = sum([p.battleitemsum() for p in op[3:6]])
        gain = min([p.nextlvl for p in op[0:6]]) * 0.2
        roll_a = random.randrange(team_a)
        roll_b = random.randrange(team_b)
        if roll_a >= roll_b:
            self._irc.chanmsg(f"{op[0].name}, {op[1].name}, and {op[2].name} [{roll_a}/{team_a}] "
                              f"have team battled {op[3].name}, {op[4].name}, and {op[5].name}"
                              f"[{roll_b}/{team_b}] and won!  {duration(gain)} is removed from their clocks.")
            for p in op[0:3]:
                p.nextlvl -= gain
        else:
            self._irc.chanmsg(f"{op[0].name}, {op[1].name}, and {op[2].name} [{roll_a}/{team_a}] "
                              f"have team battled {op[3].name}, {op[4].name}, and {op[5].name}"
                              f"[{roll_b}/{team_b}] and lost!  {duration(gain)} is added to their clocks.")
            for p in op[0:3]:
                p.nextlvl += gain


    def calamity(self):
        player = random.choice(self._players.online())
        if not player:
            return

        if random.randrange(10) < 1:
            # Item damaging calamity
            item = random.choice(Player.ITEMS)
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
            self._irc.chanmsg(msg + f" {player.name}'s {Player.ITEMDESC[item]} loses 10% of its effectiveness.")
            setattr(player, item, int(getattr(player, item) * 0.9))
            return

        # Level setback calamity
        amount = int((5 + random.randrange(8)) / 100 * player.nextlvl)
        player.nextlvl += amount
        # TODO: reading this file every time is silly
        with open(conf['eventsfile']) as inf:
            lines = [line.rstrip() for line in inf.readlines() if line.startswith("C ")]
        action = random.choice(lines)[2:]
        self._irc.chanmsg(f"{player.name} {action}! This terrible calamity has slowed them "
                          f"{duration(amount)} from level {player.level + 1}.")
        if player.nextlvl > 0:
            self._irc.chanmsg(f"{player.name} reaches next level in {duration(player.nextlvl)}.")


    def godsend(self):
        player = random.choice(self._players.online())
        if not player:
            return

        if random.randrange(10) < 1:
            # Item improving godsend
            item = random.choice(Player.ITEMS)
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

            self._irc.chanmsg(msg + f" {player.name}'s {Player.ITEMDESC[item]} gains 10% effectiveness.")
            setattr(player, item, int(getattr(player, item) * 1.1))
            return

        # Level godsend
        amount = int((5 + random.randrange(8)) / 100 * player.nextlvl)
        player.nextlvl -= amount
        # TODO: reading this file every time is silly
        with open(conf['eventsfile']) as inf:
            lines = [line.rstrip() for line in inf.readlines() if line.startswith("G ")]
        action = random.choice(lines)[2:]
        self._irc.chanmsg(f"{player.name} {action}! This wondrous godsend has accelerated them "
                          f"{duration(amount)} towards level {player.level + 1}.")
        if player.nextlvl > 0:
            self._irc.chanmsg(f"{player.name} reaches next level in {duration(player.nextlvl)}.")


    def evilness(self):
        op = self._players.online()
        evil_p = [p for p in op if p.alignment == 'e']
        if not evil_p:
            return
        player = random.choice(evil_p)
        if random.randrange(2) < 1:
            target = random.choice([p for p in op if p.alignment == 'g'])
            if not target:
                return
            item = random.choice(Player.ITEMS)
            if getattr(player, item) > getattr(target, item):
                player.swap_items(target, item)
                self._irc.chanmsg(f"{player.name} stole {target.name}'s level {getattr(player, item)} "
                                  f"{Player.ITEMDESC[item]} while they were sleeping!  {player.name} "
                                  f"leaves their old level {getattr(target, item)} {Player.ITEMDESC[item]} "
                                  f"behind, which {target.name} then takes.")
            else:
                self._irc.notice(f"You made to steal {target.name}'s {Player.ITEMDESC[item]}, "
                                 f"but realized it was lower level than your own.  You creep "
                                 f"back into the shadows.")
        else:
            amount = int(player.nextlvl * random.randrange(1,6) / 100)
            player.nextlvl += amount
            self._irc.chanmsg(f"{player.name} is forsaken by their evil god. {duration(amount)} is "
                              f"added to their clock.")
            if player.nextlvl > 0:
                self._irc.chanmsg(f"{player.name} reaches next level in {duration(player.nextlvl)}.")

    def goodness(self):
        op = self._players.online()
        good_p = [p for p in op if p.alignment == 'g']
        if len(good_p) < 2:
            return
        players = random.shuffle(good_p)[:2]
        gain = random.randrange(5, 13)
        self._irc.chanmsg(f"{players[0].name} and {players[1].name} have not let the iniquities "
                          f"of evil people poison them. Together have they prayed to their god, "
                          f"and light now shines down upon them. {gain}% of their time is removed "
                          f"from their clocks.")
        for player in players:
            player.nextlvl = int(player.nextlvl * (1 - gain / 100))
            if player.nextlvl > 0:
                self._irc.chanmsg(f"{player.name} reaches next level in {duration(player.nextlvl)}.")


    def move_players(self):
        op = self._players.online()
        if not op:
            return
        random.shuffle(op)
        mapx = conf['mapx']
        mapy = conf['mapy']
        combatants = dict()
        if self._quest and self._quest.mode == 2:
            for p in self._quest.questors:
                # mode 2 questors always move towards the next goal
                distx = p.posx - self._quest.dest[0][0]
                if distx != 0:
                    if abs(distx) > mapx/2:
                        distx = -distx
                    xdir = distx / abs(distx)
                    p.posx = (p.posx + xdir) % mapx

                disty = p.posy - self._quest.dest[0][1]
                if disty != 0:
                    if abs(disty) > mapy/2:
                        disty = -disty
                    ydir = disty / abs(disty)
                    p.posy = (p.posy + ydir) % mapy
                # take questors out of rotation for movement and pvp
                op.remove(p)

        for p in op:
            # everyone else wanders aimlessly
            p.posx = (p.posx + random.randrange(-1,1)) % mapx
            p.posy = (p.posy + random.randrange(-1,1)) % mapy

            if (p.posx, p.posy) in combatants:
                combatant = combatants[(p.posx, p.posy)]
                if combatant.isadmin and random.randrange(100) < 1:
                    self._irc.chanmsg(f"{p.name} encounters {combatant.name} and bows humbly.")
                elif random.randrange(len(op)) < 1:
                    self.pvp_battle(p, combatant,
                                    'come upon',
                                    'and taken them in combat',
                                    'and been defeated in combat')
                    del combatants[(p.posx, p.posy)]
            else:
                combatants[(p.posx, p.posy)] = p


    def quest_check(self):
        if self._quest is None:
            if time.time() <= self._qtimer:
                self.quest_start()
        elif self._quest.mode == 1:
            if time.time() <= self._quest.qtime:
                qp = self._quest.questors
                self._irc.chanmsg(f"{qp[0].name}, {qp[1].name}, {qp[2].name}, and {qp[3].name} "
                                  f"have blessed the realm by completing their quest! 25% of "
                                  f"their burden is eliminated.")
                for q in qp:
                    q.nextlvl = int(q.nextlvl * 0.75)
                self._quest = None
                self._qtimer = time() + 6*3600
        elif self._quest.mode == 2:
            done = True
            for q in self._quest.questors:
                if q.posx != self._quest.dest[0][0] or q.posy != self._quest.dest[0][1]:
                    done = False
                    break
            if done:
                self._quest.dest = self._quest.dest[1:]
                if len(self._quest.dest) > 0:
                    if len(self._quest.dest) == 1:
                        landmarks_remain = "1 landmark remains."
                    else:
                        landmarks_remain = f"{len(self._quest.dest)} landmarks remain."
                    self._irc.chanmsg(f"{qp[0].name}, {qp[1].name}, {qp[2].name}, and {qp[3].name} "
                                      f"have reached a landmark on their journey! {landmarks_remain} ")
                else:
                    self._irc.chanmsg(f"{qp[0].name}, {qp[1].name}, {qp[2].name}, and {qp[3].name} "
                                      f"have completed their journey! 25% of "
                                      f"their burden is eliminated.")
                    for q in qp:
                        q.nextlvl = int(q.nextlvl * 0.75)
                    self._quest = None
                    self._qtimer = time() + 6*3600


    def quest_start(self):
        latest_login_time = time.time() - 36000
        qp = [p for p in self._players.online() if p.level > 24 and p.lastlogin < latest_login_time]
        if len(qp) < 4:
            return
        qp = random.shuffle(qp)[:4]
        # TODO: reading this file every time is silly
        with open(conf['eventsfile']) as inf:
            lines = [line.rstrip() for line in inf.readlines() if line.startswith("Q")]
        questconf = random.choice(lines)
        match = (re.match(r'^Q(1) (.*)', questconf) or
                 re.match(r'^Q(2) (\d+) (\d+) (\d+) (\d+) (.*)', questconf))
        if not match:
            return
        self._quest = Quest(questors=qp)
        if match[1] == '1':
            self._quest.mode = 1
            self._quest.text = match[2]
            self._quest.qtime = time.time() + random.randrange(12, 24)*3600
        elif match[1] == '2':
            self._quest.mode = 2
            self._quest.dest = [(int(match[2]), int(match[3])), (int(match[4]), int(match[5]))]
            self._quest.text = match[5]

        if self._quest.mode == 1:
            self._irc.chanmsg(f"{qp[0].name}, {qp[1].name}, {qp[2].name}, and {qp[3].name} have "
                              f"been chosen by the gods to {self._quest.text}.  Quest to end in "
                              f"{duration(self._quest.qtime - time.time())}.")
        elif self._quest.mode == 2:
            mapnotice = ''
            if 'mapurl' in conf:
                mapnotice = f" See {conf['mapurl']} to monitor their journey's progress."
            self._irc.chanmsg(f"{qp[0].name}, {qp[1].name}, {qp[2].name}, and {qp[3].name} have "
                              f"been chosen by the gods to {self._quest.text}.  Participants must first "
                              f"reach ({self._quest.dest[0][0]},{self._quest.dest[0][0]}), "
                              f"then ({self._quest.dest[1][0]},{self._quest.dest[1][0]}).{mapnotice}")


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
    db = PlayerDB(conf["dbfile"])
    if db.exists():
        db.load()
    else:
        first_setup()

    bot = DawdleBot(db)
    client = IRCClient(bot)
    asyncio.run(mainloop(client))


if __name__ == "__main__":
    start_bot()
