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
    @classmethod
    def from_dict(cls, d):
        p = cls()
        for k,v in d.items():
            setattr(p, k, v)
        return p

    @staticmethod
    def new_player(pname, pclass, ppass):
        p = Player()
        p.name = pname
        p.cclass = pclass
        p.pw = crypt.crypt(ppass, crypt.mksalt())
        p.isadmin = False
        p.level = 0
        p.nextlvl = conf['rpbase']
        p.nick = ""
        p.userhost = ""
        p.online = False
        p.idled = 0
        p.posx = 0
        p.posy = 0
        p.penmesg = 0
        p.pennick = 0
        p.penpart = 0
        p.penkick = 0
        p.penquit = 0
        p.penquest = 0
        p.penlogout = 0
        p.created = time.time()
        p.lastlogin = time.time()
        p.amulet = 0
        p.charm = 0
        p.helm = 0
        p.boots = 0
        p.gloves = 0
        p.ring = 0
        p.leggings = 0
        p.shield = 0
        p.tunic = 0
        p.weapon = 0
        p.alignment = "n"
        return p

    def set_password(self, ppass):
        self.pw = crypt.crypt(ppass, crypt.mksalt())


class PlayerDB(object):

    FIELDS = ["name", "cclass", "pw", "isadmin", "level", "nextlvl", "nick", "userhost", "online", "idled", "posx", "posy", "penmesg", "pennick", "penpart", "penkick", "penquit", "penquest", "penlogout", "created", "lastlogin", "amulet", "charm", "helm", "boots", "gloves", "ring", "leggings", "shield", "tunic", "weapon", "alignment"]


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
                            [vars(u) for u in self._players.values()])


    def create(self):
        with self._connect() as cur:
            cur.execute(f"create table players ({','.join(PlayerDB.FIELDS)})")


    def new_player(self, pname, ppass, pclass):
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
        for u in self._players.values():
            if u.online and u.nick == nick:
                return u
        return None


    def check_login(self, pname, ppass):
        result = True
        result = result and pname in self._players
        result = result and crypt.crypt(ppass, self._players[pname].pw) == self._players[pname].pw
        return result


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
    u = db.new_player(pname, pclass, ppass)
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


class DawdleBot(object):
    # Commands in ALLOWALL can be used by anyone.
    # Commands in ALLOWPLAYERS can only be used by logged-in players
    # All other commands are admin-only
    ALLOWALL = ["help", "login", "register", "quest", "version", "eval"]
    ALLOWPLAYERS = ["align", "logout", "newpass", "removeme", "status", "whoami"]

    def __init__(self, db):
        self._irc = None
        self._onchan = []
        self._players = db

    def connected(self, irc):
        self._irc = irc


    def ready(self):
        pass


    def disconnected(self, evt):
        self._irc = None
        self._onchan = []


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


    def channel_message(self, src, text):
        pass


    def channel_notice(self, src, text):
        pass


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


    def nick_joined(self, src):
        self._onchan.append(src)


    def nick_parted(self, src):
        self._onchan.remove(src)
        player = self._players.from_nick(src)
        if player:
            player.online = False


    def nick_quit(self, src):
        self._onchan.remove(src)
        player = self._players.from_nick(src)
        if player:
            player.online = False


    def nick_kicked(self, target):
        self._onchan.remove(src)
        player = self._players.from_nick(src)
        if player:
            player.online = False


    def cmd_align(self, player, nick, args):
        if args not in ["good", "neutral", "evil"]:
            self._irc.notice(nick, "Try: ALIGN good|neutral|evil")
            return
        player.alignment = args[0]
        _players.write()


    def cmd_help(self, player, nick, args):
        self._irc.notice(nick, "Help?  But we are dawdling!")


    def cmd_version(self, player, nick, args):
        self._irc.notice(nick, f"DawdleRPG v{VERSION} by Daniel Lowe")


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
