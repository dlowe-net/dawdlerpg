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
import collections
import crypt
import datetime
import itertools
import os
import os.path
import random
import re
import shutil
import sqlite3
import sys
import time

from hmac import compare_digest as compare_hash

from dawdle import abstract
from dawdle import chunk
from dawdle import conf
from dawdle import rand
from dawdle.log import log
from typing import cast, Any, Dict, List, Literal, Iterable, Optional, Sized, Set, Sequence, Tuple


VERSION = "1.0.0"

start_time = int(time.time())

def plural(num: int, singlestr: str='', pluralstr: str='s') -> str:
    """Return singlestr when num is 1, otherwise pluralstr."""
    if num == 1:
        return singlestr
    return pluralstr


def duration(secs: int) -> str:
    """Return description of duration marked in seconds."""
    d, secs = int(secs / 86400), secs % 86400
    h, secs = int(secs / 3600), secs % 3600
    m, secs = int(secs / 60), secs % 60
    return C("duration", f"{d} day{plural(d)}, {h:02d}:{m:02d}:{int(secs):02d}")


def datapath(path: str) -> str:
    """Return path relative to datadir unless path is absolute."""
    if os.path.isabs(path):
        return path
    return os.path.join(conf.get("datadir"), path)


def CC(color: str) -> str:
    """Return color code if colors are enabled."""
    if not conf.get("color"):
        return ""
    colors = {"white": 0, "black": 1, "navy": 2, "green": 3, "red": 4, "maroon": 5, "purple": 6, "olive": 7, "yellow": 8, "lgreen": 9, "teal": 10, "cyan": 11, "blue": 12, "magenta": 13, "gray": 14, "lgray": 15, "default": 99}
    if color not in colors:
        return f"[{color}?]"
    return f"\x03{colors[color]:02d},99"


def C(field: str='', text: str='') -> str:
    """Return colorized version of text according to config field.

    If text is specified, returns the colorized version with a formatting reset.
    If text is not specified, returns just the color code.
    If field is not specified, returns just a formatting reset.
    """
    if not conf.get("color"):
        return text
    if field == "":
        return "\x0f"
    conf_field = f"{field}color"
    if not conf.has(conf_field):
        return f"[{conf_field}?]" + text
    if text == "":
        return CC(conf.get(conf_field))
    return CC(conf.get(conf_field)) + text + "\x0f"


class Item(object):
    """Represents an item held by a player."""

    SLOTS = ['ring', 'amulet', 'charm', 'weapon', 'helm', 'tunic', 'gloves', 'leggings', 'shield', 'boots']
    DESC = {
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


    def __init__(self, level: int, name: str):
        self.level = level
        self.name = name

    def __eq__(self, o: object) -> bool:
        if not isinstance(o, Item):
            return NotImplemented
        return self.level == o.level and self.name == o.name


class Player(object):
    """Represents a player of the dawdlerpg game."""

    name: str
    cclass: str
    pw: str
    isadmin: bool
    level: int
    nextlvl: int
    online: bool
    nick: str
    userhost: str
    idled: int
    posx: int
    posy: int
    penmessage: int
    pennick: int
    penpart: int
    penkick: int
    penquit: int
    pendropped: int
    penquest: int
    penlogout: int
    created: datetime.datetime
    lastlogin: datetime.datetime
    alignment: str
    items: Dict[str, Item]

    @classmethod
    def from_dict(cls: object, d: Dict[str, Any]) -> "Player":
        """Returns a player with its values set to the dict's."""
        p = Player()
        for k,v in d.items():
            setattr(p, k, v)
        p.items = dict()
        return p

    @staticmethod
    def new_player(pname: str, pclass: str, ppass: str, nextlvl: int) -> "Player":
        """Initialize a new player."""
        now = datetime.datetime.now().replace(microsecond=0)
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
        # Items held by player
        p.items = {}

        return p


    def set_password(self, ppass: str) -> None:
        """Sets the password field with a hashed value."""
        self.pw = crypt.crypt(ppass, crypt.mksalt())


    def item_level(self, slot: str) -> int:
        if slot not in self.items:
            return 0
        return self.items[slot].level


    def item_name(self, slot: str) -> str:
        if slot not in self.items:
            return ""
        return self.items[slot].name


    def acquire_item(self, slot: str, level: int, name: str='') -> None:
        """Acquire an item."""
        self.items[slot] = Item(level, name)


    def swap_items(self, o: "Player", slot: str) -> None:
        """Swap items of SLOT with the other player O."""
        myitem, otheritem = self.items.get(slot), o.items.get(slot)
        if myitem is None and otheritem is not None:
            del o.items[slot]
        elif myitem is not None:
            o.items[slot] = myitem
        if otheritem is None and myitem is not None:
            del self.items[slot]
        elif otheritem is not None:
            self.items[slot] = otheritem


    def itemsum(self) -> int:
        """Add up the power of all the player's items"""
        return sum([item.level for item in self.items.values()])


    def battleitemsum(self) -> int:
        """
        Add up item power for battle.

        Good players get a boost, and evil players get a penalty.
        """
        sum = self.itemsum()
        if self.alignment == 'e':
            return int(sum * conf.get("evil_battle_pct")/100)
        if self.alignment == 'g':
            return int(sum * conf.get("good_battle_pct")/100)
        return sum


class Quest(object):
    """Class for tracking quests."""
    questor_names: List[str]
    questors: List[Player]
    mode: int
    text: str
    qtime: Optional[int]
    stage: Optional[int]
    dests: List[Tuple[int, int]]

    def __init__(self) -> None:
        # TODO: This is an ugly hack to support deserialization.
        self.questor_names = []
        self.questors = []
        self.mode = 0
        self.text = ""
        self.qtime = None
        self.stage = None
        self.dests = []


class GameStorage(object):
    """Interface for a GameDB backend."""

    def create(self) -> None:
        """Create a new store."""
        raise NotImplementedError

    def exists(self) -> bool:
        """Return True if a store exists."""
        raise NotImplementedError

    def backup(self) -> None:
        """Backup the store to a backup directory."""
        raise NotImplementedError

    def clear(self) -> None:
        """Reinitialize the store."""
        raise NotImplementedError

    def readall(self) -> Iterable[Player]:
        """Returns all players read from store."""
        raise NotImplementedError

    def write(self, players: Iterable[Player]) -> None:
        """Write the given players to the store."""
        raise NotImplementedError

    def close(self) -> None:
        """Close the store."""
        raise NotImplementedError

    def new(self, player: Player) -> None:
        """Create a new player record."""
        raise NotImplementedError

    def rename_player(self, old: str, new: str) -> None:
        """Rename a player in the store."""
        raise NotImplementedError

    def delete_player(self, pname: str) -> None:
        """Removes a player from the store."""
        raise NotImplementedError

    def add_history(self, players: List[str], text: str) -> None:
        """Adds history text for the players."""
        raise NotImplementedError

    def read_quest(self) -> Optional[Quest]:
        """Returns stored quest object or None."""
        raise NotImplementedError

    def update_quest(self, quest: Optional[Quest]) -> None:
        """Updates quest information in store."""
        raise NotImplementedError


class IdleRPGGameStorage(GameStorage):
    """Implements a GameStorage compatible with the IdleRPG db.

    Since the IdleRPG db is a tsv file, we can't reasonably update it
    piecemeal, so the playerbase is cached during reads, and written
    in its entirety on writes.  The player objects are shared between
    the cache and the GameDB.

    """

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

    _dbpath: str
    _cache: List[Player]

    def _code_to_item(self, s: str) -> Tuple[int, str]:
        """Converts an IdleRPG item code to a tuple of (level, name)."""
        match = re.match(r"(\d+)(.?)", s)
        if not match:
            log.error(f"invalid item code: {s}")
            return (int(s), "")
        lvl = int(match[1])
        if match[2]:
            return (lvl, [k for k,v in IdleRPGGameStorage.ITEMCODES.items() if v == match[2]][0])
        return (lvl, "")


    def _item_to_code(self, level: int, name: str) -> str:
        """Converts an item level and name to an IdleRPG item code."""
        return f"{level}{IdleRPGGameStorage.ITEMCODES.get(name, '')}"


    def __init__(self, dbpath: str):
        self._dbpath = dbpath
        self._cache = []


    def create(self) -> None:
        """Creates a new IdleRPG db."""
        self.write([])


    def exists(self) -> bool:
        """Returns true if the db file exists."""
        return os.path.exists(self._dbpath)


    def close(self) -> None:
        """Does nothing - no need to close the idlerpg file."""
        pass


    def backup(self) -> None:
        """Backs up database to a directory."""
        os.makedirs(datapath(conf.get("backupdir")), exist_ok=True)
        backup_path = os.path.join(datapath(conf.get("backupdir")),
                                   f"{time.strftime('%Y-%m-%dT%H:%M:%S')}-{os.path.basename(conf.get('dbfile'))}")
        shutil.copyfile(self._dbpath, backup_path)


    def _player_to_record(self, p: Player) -> str:
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
            str(int(p.created.timestamp())),
            str(int(p.lastlogin.timestamp())),
            self._item_to_code(p.item_level("amulet"), p.item_name("amulet")),
            self._item_to_code(p.item_level("charm"), p.item_name("charm")),
            self._item_to_code(p.item_level("helm"), p.item_name("helm")),
            self._item_to_code(p.item_level("boots"), p.item_name("boots")),
            self._item_to_code(p.item_level("gloves"), p.item_name("gloves")),
            self._item_to_code(p.item_level("ring"), p.item_name("ring")),
            self._item_to_code(p.item_level("leggings"), p.item_name("leggings")),
            self._item_to_code(p.item_level("shield"), p.item_name("shield")),
            self._item_to_code(p.item_level("tunic"), p.item_name("tunic")),
            self._item_to_code(p.item_level("weapon"), p.item_name("weapon")),
            str(p.alignment)
        ]) + "\n"


    def readall(self) -> Iterable[Player]:
        """Reads all the players into a dict."""
        self._cache = []
        with open(self._dbpath) as inf:
            for line in inf.readlines():
                if re.match(r'\s*(?:#|$)', line):
                    continue
                parts = line.rstrip().split("\t")
                if len(parts) != IdleRPGGameStorage.IRPG_FIELD_COUNT:
                    log.critical("line corrupt in player db - %d fields: %s", len(parts), repr(line))
                    sys.exit(-1)

                # This makes a mapping from irpg field to player field.
                d = dict(zip(["name", "pw", "isadmin", "level", "cclass", "nextlvl", "nick", "userhost", "online", "idled", "posx", "posy", "penmessage", "pennick", "penpart", "penkick", "penquit", "penquest", "penlogout", "created", "lastlogin", "amulet", "charm", "helm", "boots", "gloves", "ring", "leggings", "shield", "tunic", "weapon", "alignment"], parts))
                # convert items
                items = dict()
                for i in Item.SLOTS:
                    level, name = self._code_to_item(d[i])
                    if level > 0:
                        items[i] = Item(level, name)
                    del d[i]

                # convert int fields
                for f in ["level", "nextlvl", "idled", "posx", "posy", "penmessage", "pennick", "penpart", "penkick", "penquit", "penquest", "penlogout", "created", "lastlogin"]:
                    d[f] = round(float(d[f])) # type:ignore
                # convert boolean fields
                for f in ["isadmin", "online"]:
                    d[f] = (d[f] == '1') # type:ignore

                d['pendropped'] = 0 # type: ignore

                d['created'] = datetime.datetime.fromtimestamp(int(d['created'])) # type:ignore
                d['lastlogin'] = datetime.datetime.fromtimestamp(int(d['lastlogin'])) # type:ignore

                p = Player.from_dict(d)
                p.items = items
                self._cache.append(p)
        return self._cache


    def write(self, players: Iterable[Player]) -> None:
        """Writes players to an IdleRPG db."""
        with open(self._dbpath, "w") as ouf:
            ouf.write("# " + "\t".join(IdleRPGGameStorage.IRPG_FIELDS) + "\n")
            for p in self._cache:
                ouf.write(self._player_to_record(p))


    def new(self, p: Player) -> None:
        """Creates a new player in the db."""
        self._cache.append(p)
        with open(self._dbpath, "a") as ouf:
            ouf.write(self._player_to_record(p))


    def rename_player(self, old_name: str, new_name: str) -> None:
        """Renames a player in the db."""
        # Presumably the player in the cache has changed its name, so
        # just write out the file.
        self.write([])


    def delete_player(self, pname:str) -> None:
        """Removes a player from the db."""
        self._cache = [p for p in self._cache if p.name != pname]
        self.write([])


    def add_history(self, pnames: List[str], text: str) -> None:
        """Adds history text for the player.

        IdleRPG dumps all history into a single modsfile, which is
        then grepped for by the website.

        """
        with open(datapath(conf.get("modsfile")), "a") as ouf:
            ouf.write(f"[{time.strftime('%m/%d/%y %H:%M:%S')}] {text}\n")


    def read_quest(self) -> Optional[Quest]:
        """Returns stored Quest object or None."""
        if not conf.get("writequestfile"):
            return None
        if os.stat(datapath(conf.get("questfilename"))).st_size == 0:
            return None

        with open(datapath(conf.get("questfilename"))) as inf:
            q = Quest()
            for line in inf.readlines():
                key, val = line.split(' ', 2)
                if key == "T":
                    q.text = val
                elif key == "Y":
                    q.mode = int(val)
                elif key == "S":
                    if q.mode == 1:
                        q.qtime = int(val)
                    else:
                        q.stage = int(val)
                elif key == "P":
                    for pair in chunk.chunk(val.split(' '), 2):
                        q.dests.append((int(pair[0]), int(pair[1])))
                elif re.match("P\d", key):
                    q.questor_names.append(val)
            return q


    def update_quest(self, quest: Optional[Quest]) -> None:
        """Updates quest information in store."""
        if not conf.get("writequestfile"):
            return
        with open(datapath(conf.get("questfilename")), 'w') as ouf:
            if not quest:
                # leave behind an empty quest file
                return

            ouf.write(f"T {quest.text}\n"
                      f"Y {quest.mode}\n")

            if quest.mode == 1:
                ouf.write(f"S {quest.qtime}\n")
            elif quest.mode == 2:
                ouf.write(f"S {quest.stage:d}\n"
                          f"P {' '.join([' '.join([str(c) for c in p]) for p in quest.dests])}\n")

            ouf.write(f"P1 {quest.questors[0].name}\n"
                      f"P2 {quest.questors[1].name}\n"
                      f"P3 {quest.questors[2].name}\n"
                      f"P4 {quest.questors[3].name}\n")


class Sqlite3GameStorage(GameStorage):
    """Player store using sqlite3."""

    FIELDS = ["name", "cclass", "pw", "isadmin", "level", "nextlvl", "nick", "userhost", "online", "idled", "posx", "posy", "penmessage", "pennick", "penpart", "penkick", "penquit", "pendropped", "penquest", "penlogout", "created", "lastlogin", "alignment"]


    _dbpath: str
    _db: Optional[sqlite3.Connection]

    @staticmethod
    def dict_factory(cursor: sqlite3.Cursor, row: sqlite3.Row) -> Dict[str, str]:
        """Converts a sqlite3 row into a dict."""
        d = {}
        for idx, col in enumerate(cursor.description):
            d[col[0]] = row[idx]
        return d


    def _connect(self) -> sqlite3.Connection:
        """Connects to the sqlite3 db if not already connected."""
        if self._db is None:
            self._db = sqlite3.connect(self._dbpath)
            self._db.row_factory = Sqlite3GameStorage.dict_factory

        return self._db


    def __init__(self, dbpath: str):
        self._dbpath = dbpath
        self._db = None


    def create(self) -> None:
        """Initializes a new db."""
        with self._connect() as con:
            con.execute(f"create table dawdle_player ({','.join(Sqlite3GameStorage.FIELDS)})")
            con.execute('create table dawdle_item (id, owner_id, slot, level, name, CONSTRAINT "unique_item_owner_slot" UNIQUE ("owner_id", "slot"))')
            con.execute("create table dawdle_history (id, owner_id, time, text)")
            con.execute("create table dawdle_quest (id, mode, p1, p2, p3, p4, text, qtime, stage, dest1x, dest1y, dest2x, dest2y)")
            con.execute("insert into dawdle_quest (mode) values (0)")


    def clear(self) -> None:
        """Destroys all data in the db without deleting it."""
        with self._connect() as con:
            con.execute("delete from dawdle_player")
            con.execute("delete from dawdle_item")
            con.execute("delete from dawdle_history")
            con.execute("delete from dawdle_quest")


    def exists(self) -> bool:
        """Returns True if the db exists."""
        return os.path.exists(self._dbpath)


    def backup(self) -> None:
        """Backs up database to a directory."""
        os.makedirs(datapath(conf.get("backupdir")), exist_ok=True)
        with self._connect() as con:
            backup_path = os.path.join(datapath(conf.get("backupdir")),
                                       f"{time.strftime('%Y-%m-%dT%H:%M:%S')}-{os.path.basename(conf.get('dbfile'))}")
            with sqlite3.connect(backup_path) as backup_db:
                con.backup(backup_db)


    def readall(self) -> Iterable[Player]:
        """Reads all the players from the db."""
        players = {}
        with self._connect() as con:
            cur = con.execute("select * from dawdle_player")
            for d in cur.fetchall():
                d["created"] = datetime.datetime.fromisoformat(d["created"])
                d["lastlogin"] = datetime.datetime.fromisoformat(d["lastlogin"])
                players[d["name"]] = Player.from_dict(d)
            cur = con.execute("select * from dawdle_item")
            for d in cur.fetchall():
                players[d["owner_id"]].items[d["slot"]] = Item(d["level"], d["name"])
        return players.values()


    def write(self, players: Iterable[Player]) -> None:
        """Writes player information into the db."""
        with self._connect() as con:
            sql_fields = ",".join(Sqlite3GameStorage.FIELDS)
            p_fields = ",".join([":"+k for k in Sqlite3GameStorage.FIELDS])
            con.executemany(f"replace into dawdle_player ({sql_fields}) values ({p_fields})",
                            [vars(p) for p in players])
            item_updates = []
            for p in players:
                for slot, item in p.items.items():
                    item_updates.append((p.name, slot, item.level, item.name))
            con.executemany("replace into dawdle_item (owner_id, slot, level, name) values (:owner, :slot, :level, :name)",
                            item_updates)


    def close(self) -> None:
        """Finish using db."""
        assert self._db is not None
        self._db.close()


    def new(self, p: Player) -> None:
        """Create new character in db."""
        with self._connect() as con:
            d = vars(p)
            con.execute(f"insert into dawdle_player ({','.join(Sqlite3GameStorage.FIELDS)}) values ({('?, ' * len(Sqlite3GameStorage.FIELDS))[:-2]})",
                        [d[k] for k in Sqlite3GameStorage.FIELDS])
            con.commit()


    def rename_player(self, old_name: str, new_name: str) -> None:
        """Rename player in db."""
        with self._connect() as con:
            con.execute("update dawdle_player set name = ? where name = ?", (new_name, old_name))
            con.commit()


    def delete_player(self, pname: str) -> None:
        """Remove player from db."""
        with self._connect() as con:
            con.execute("delete from dawdle_player where name = ?", (pname,))
            con.commit()


    def bulk_history_insert(self, history: List[Tuple[str, str, str]]) -> None:
        """Inserts (owner, time, text) tuples into history db."""
        with self._connect() as con:
            con.executemany("insert into dawdle_history (owner_id, time, text) values (?, datetime(?), ?)", history)


    def add_history(self, pnames: List[str], text: str, time: str='now') -> None:
        """Adds history text for the player."""
        with self._connect() as con:
            con.executemany("insert into dawdle_history (owner_id, time, text) values (?, datetime(?), ?)",
                            [(pname, time, text) for pname in pnames])


    def read_quest(self) -> Optional[Quest]:
        with self._connect() as con:
            cur = con.execute("select * from dawdle_quest")
            res = cur.fetchone()
            if not res:
                # We should always have a quest object
                con.execute("insert into dawdle_quest (mode, p1, p2, p3, p4) values (0, '', '', '', '')")
                return None
            elif res['mode'] == 0:
                return None
            q = Quest()
            q.questor_names = [res['p1'], res['p2'], res['p3'], res['p4']]
            q.text = res['text']
            q.mode = res['mode']
            if q.mode == 1:
                q.qtime = res['qtime']
            if q.mode == 2:
                q.stage = int(res['stage'])
                q.dests = [(int(res['dest1x']), int(res['dest1y'])), (int(res['dest2x']), int(res['dest2y']))]

            return q


    def update_quest(self, quest: Optional[Quest]) -> None:
        """Updates quest information in store."""
        with self._connect() as con:
            if not quest:
                con.execute("update dawdle_quest set mode = 0")
                con.commit()
                return
            if quest.mode == 1:
                con.execute("update dawdle_quest set mode=?, text=?, p1=?, p2=?, p3=?, p4=?, qtime=?",
                            (quest.mode,
                             quest.text,
                             quest.questors[0].name,
                             quest.questors[1].name,
                             quest.questors[2].name,
                             quest.questors[3].name,
                             quest.qtime))
            else:
                con.execute("update dawdle_quest set mode=?, text=?, p1=?, p2=?, p3=?, p4=?, stage=?, dest1x=?, dest1y=?, dest2x=?, dest2y=?",
                            (quest.mode,
                             quest.text,
                             quest.questors[0].name,
                             quest.questors[1].name,
                             quest.questors[2].name,
                             quest.questors[3].name,
                             quest.stage,
                             quest.dests[0][0],
                             quest.dests[0][1],
                             quest.dests[1][0],
                             quest.dests[1][1]))
            con.commit()


class GameDB(object):
    """Class to manage a collection of Players."""

    _store: GameStorage
    _players: Dict[str, Player]

    def __init__(self, store: GameStorage):
        self._store = store
        self._players = {}

    def __getitem__(self, pname: str) -> Player:
        """Return a player by name."""
        return self._players[pname]


    def __contains__(self, pname: str) -> bool:
        """Returns True if the player is in the db."""
        return pname in self._players


    def create(self) -> None:
        """Creates a new database from scratch."""
        self._store.create()


    def clear(self) -> None:
        """Reinitializes the new database."""
        self._store.clear()


    def close(self) -> None:
        """Close the underlying db.  Used for testing."""
        self._store.close()


    def exists(self) -> bool:
        """Returns True if the underlying store exists."""
        return self._store.exists()


    def backup_store(self) -> None:
        """Backup store into another file."""
        self._store.backup()


    def load_state(self) -> None:
        """Load all players from database into memory"""
        for p in self._store.readall():
            self._players[p.name] = p
        self._quest = self._store.read_quest()
        if self._quest:
            self._quest.questors = [self._players[pname] for pname in self._quest.questor_names]


    def write_players(self, players: Optional[List[Player]]=None) -> None:
        """Write player objects into database.  Defaults to all."""
        if players is None:
            self._store.write(self._players.values())
        else:
            self._store.write(players)


    def new_player(self, pname: str, pclass: str, ppass: str) -> Player:
        """Create a new player with the name, class, and password."""
        if pname in self._players:
            raise KeyError

        p = Player.new_player(pname, pclass, ppass, conf.get("rpbase"))
        self._players[pname] = p
        self._store.new(p)

        return p


    def rename_player(self, old_name: str, new_name: str) -> None:
        """Rename a player in the db."""
        self._players[new_name] = self._players[old_name]
        self._players[new_name].name = new_name
        self._players.pop(old_name, None)
        self._store.rename_player(old_name, new_name)


    def delete_player(self, pname: str) -> None:
        """Remove a player from the db."""
        self._players.pop(pname)
        self._store.delete_player(pname)


    def from_user(self, user: abstract.AbstractClient.User) -> Optional[Player]:
        """Find the given online player with the irc user."""
        # The "userhost" includes the nick so it's still matching the
        # nick.
        for p in self._players.values():
            if p.online and p.userhost == user.userhost:
                return p
        return None


    def add_history(self, players: List[Player], text: str) -> None:
        """Add text to the players' history."""
        self._store.add_history([p.name for p in players], text)


    def update_quest(self, quest: Optional[Quest]) -> None:
        self._store.update_quest(quest)


    def check_login(self, pname: str, ppass: str) -> bool:
        """Return True if name and password are a valid login."""
        result = (pname in self._players)
        result = result and compare_hash(self._players[pname].pw, crypt.crypt(ppass, self._players[pname].pw))
        return result


    def count_players(self) -> int:
        """Return number of all players registered."""
        return len(self._players)


    def online_players(self) -> List[Player]:
        """Return all active, online players."""
        return [p for p in self._players.values() if p.online]


    def max_player_power(self) -> int:
        """Return the itemsum of the most powerful player."""
        return max([p.itemsum() for p in self._players.values()])


    def top_players(self) -> List[Player]:
        """Return the top three players."""
        return sorted(self._players.values(), key=lambda p: (-p.level, p.nextlvl))[:3]


    def inactive_since(self, expire: int) -> List[Player]:
        """Return all players that have been inactive since a point in time."""
        return [p for p in self._players.values() if not p.online and p.lastlogin.timestamp() < expire]


# SpecialItem is a configuration tuple for specifying special items.
SpecialItem = collections.namedtuple('SpecialItem', ['minlvl', 'itemlvl', 'lvlspread', 'kind', 'name', 'flavor'])


class DawdleBot(abstract.AbstractBot):
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


    _irc: Optional[abstract.AbstractClient]
    _db: GameDB
    _state: Literal["disconnected", "connected", "ready"]
    _quest: Optional[Quest]
    _qtimer: int
    _silence: Set[str]
    _pause: bool
    _last_reg_time: float
    _events: Dict[str, List[str]]
    _events_loaded: int
    _new_accounts: int
    _gametick_task: Optional[asyncio.Task] # type: ignore


    def __init__(self, db: GameDB) -> None:
        self._irc = None             # irc connection
        self._db = db           # the player database
        self._state = 'disconnected' # connected, disconnected, or ready
        self._quest = None           # quest if any
        self._qtimer = 0             # time until next quest
        self._silence = set() # can have 'chanmsg' or 'notice' to silence them
        self._pause = False # prevents game events from happening when True
        self._last_reg_time = 0
        self._events = {}       # pre-parsed contents of events file
        self._events_loaded = 0 # time the events file was loaded, to detect file changes
        self._new_accounts = 0  # number of new accounts created since startup
        self._gametick_task = None


    def connected(self, irc: abstract.AbstractClient) -> None:
        """Called when connected to IRC."""
        self._irc = irc
        self._state = 'connected'


    def chanmsg(self, text: str) -> None:
        """Send a message to the bot channel."""
        assert self._irc is not None
        if 'chanmsgs' in self._silence:
            return
        self._irc.chanmsg(text)


    def logchanmsg(self, players: List[Player], text: str) -> None:
        """Send a message to the bot channel and attach it to each player's history."""
        assert self._irc is not None
        if 'chanmsgs' in self._silence:
            return
        self._irc.chanmsg(text)
        # strip color codes for saving to file.
        text = re.sub(r"\x0f|\x03\d\d?(?:,\d\d?)?", "", text)
        self._db.add_history(players, text)


    def notice(self, nick: str, text: str) -> None:
        """Send a notice to a given nick."""
        assert self._irc is not None
        if 'notices' in self._silence:
            return
        self._irc.notice(nick, text)


    def ready(self) -> None:
        """Called when bot has finished joining channel."""
        assert self._irc is not None
        self._state = 'ready'
        self.refresh_events()
        autologin = []
        for p in self._db.online_players():
            if self._irc.match_user(p.nick, p.userhost):
                autologin.append(p.name)
            else:
                p.online = False
                p.lastlogin = datetime.datetime.now()
        self._db.write_players()
        if autologin:
            self.chanmsg(f"{len(autologin)} user{plural(len(autologin))} automatically logged in; accounts: {', '.join(autologin)}")
            if self._irc.bot_has_ops():
                self.acquired_ops()
        else:
            self.chanmsg("0 users qualified for auto login.")
        self._gametick_task = asyncio.create_task(self.gametick_loop())
        self._qtimer = int(time.time()) + rand.randint('qtimer_init',
                                                       conf.get("quest_interval_min"),
                                                       conf.get("quest_interval_max"))


    def acquired_ops(self) -> None:
        """Called when the bot has acquired ops status on the channel."""
        assert self._irc is not None
        if not conf.get("voiceonlogin") or self._state != 'ready':
            return

        self._irc.set_channel_voices([p.nick for p in self._db.online_players()])


    def disconnected(self) -> None:
        """Called when the bot has been disconnected."""
        self._irc = None
        self._state = 'disconnected'
        if self._gametick_task:
            self._gametick_task.cancel()
            self._gametick_task = None


    def private_message(self, user: abstract.AbstractClient.User, text: str) -> None:
        """Called when private message received."""
        assert self._irc is not None
        if text == '':
            return
        if self._state != "ready":
            self.notice(user.nick, "The bot isn't ready yet.")
            return

        parts = text.split(' ', 1)
        cmd = parts[0].lower()
        if len(parts) == 2:
            args = parts[1]
        else:
            args = ''
        player = self._db.from_user(user)
        if cmd in DawdleBot.ALLOWPLAYERS:
            if not player:
                self.notice(user.nick, "You are not logged in.")
                return
        elif cmd not in DawdleBot.ALLOWALL:
            if player is None or not player.isadmin:
                self.notice(user.nick, f"You cannot do '{cmd}'.")
                return
        if hasattr(self, f'cmd_{cmd}'):
            getattr(self, f'cmd_{cmd}')(player, user.nick, args)
        else:
            self.notice(user.nick, f"'{cmd} isn't actually a command.")


    def channel_message(self, user: abstract.AbstractClient.User, text: str) -> None:
        """Called when channel message received."""
        player = self._db.from_user(user)
        if player:
            self.penalize(player, "message", text)


    def channel_notice(self, user: abstract.AbstractClient.User, text: str) -> None:
        """Called when channel notice received."""
        player = self._db.from_user(user)
        if player:
            self.penalize(player, "message", text)


    def nick_changed(self, user: abstract.AbstractClient.User, new_nick: str) -> None:
        """Called when someone on channel changed nick."""
        player = self._db.from_user(user)
        if player:
            player.nick = new_nick
            self.penalize(player, "nick")


    def nick_parted(self, user: abstract.AbstractClient.User) -> None:
        """Called when someone left the channel."""
        player = self._db.from_user(user)
        if player:
            self.penalize(player, "part")
            player.online = False
            player.lastlogin = datetime.datetime.now()
            self._db.write_players([player])


    def netsplit(self, user: abstract.AbstractClient.User) -> None:
        """Called when someone was netsplit."""
        player = self._db.from_user(user)
        if player:
            player.lastlogin = datetime.datetime.now()


    def nick_dropped(self, user: abstract.AbstractClient.User) -> None:
        """Called when someone was disconnected."""
        player = self._db.from_user(user)
        if player:
            player.lastlogin = datetime.datetime.now()


    def nick_quit(self, user: abstract.AbstractClient.User) -> None:
        """Called when someone quit IRC intentionally."""
        player = self._db.from_user(user)
        if player:
            self.penalize(player, "quit")
            player.online = False
            player.lastlogin = datetime.datetime.now()
            self._db.write_players([player])


    def nick_kicked(self, user: abstract.AbstractClient.User) -> None:
        """Called when someone was kicked."""
        player = self._db.from_user(user)
        if player:
            self.penalize(player, "kick")
            player.online = False
            player.lastlogin = datetime.datetime.now()
            self._db.write_players([player])


    def cmd_align(self, player: Player, nick: str, args: str) -> None:
        """change alignment of character."""
        if args not in ["good", "neutral", "evil"]:
            self.notice(nick, "Try: ALIGN good|neutral|evil")
            return
        player.alignment = args[0]
        self.notice(nick, f"You have converted to {args}")
        self._db.write_players([player])


    def cmd_help(self, player: Player, nick: str, args: str) -> None:
        """get help."""
        if args:
            if args in DawdleBot.CMDHELP:
                self.notice(nick, DawdleBot.CMDHELP[args])
            else:
                self.notice(nick, f"{args} is not a command you can get help on.")
            return
        if not player:
            self.notice(nick, f"Available commands: {','.join(DawdleBot.ALLOWALL)}")
            self.notice(nick, f"For more information, see {conf.get('helpurl')}.")
        elif not player.isadmin:
            self.notice(nick, f"Available commands: {','.join(DawdleBot.ALLOWALL + DawdleBot.ALLOWPLAYERS)}")
            self.notice(nick, f"For more information, see {conf.get('helpurl')}.")
        else:
            self.notice(nick, f"Available commands: {','.join(sorted(DawdleBot.CMDHELP.keys()))}")
            self.notice(nick, f"Player help is at {conf.get('helpurl')} ; admin help is at {conf.get('admincommurl')}")


    def cmd_version(self, player: Player, nick: str, args: str) -> None:
        """display version information."""
        self.notice(nick, f"DawdleRPG v{VERSION} by Daniel Lowe")


    def cmd_info(self, player: Player, nick: str, args: str) -> None:
        """display bot information and admin list."""
        assert self._irc is not None
        admins = [C('name', p.name) for p in self._db.online_players() if p.isadmin]
        if admins:
            admin_notice = f"Admin{plural(len(admins))} online: " + ", ".join(admins)
        else:
            admin_notice = "No admins online."
        if not player or not player.isadmin:
            if conf.get("allowuserinfo"):
                self.notice(nick, f"DawdleRPG v{VERSION} by Daniel Lowe, "
                            f"On via server: {self._irc.servername()}. "
                            f"{admin_notice}")
            else:
                self.notice(nick, "You cannot do 'info'.")
            return

        online_count = len(self._db.online_players())
        q_msgs = self._irc.writeq_len()
        q_bytes = self._irc.writeq_bytes()
        if self._silence:
            silent_mode = ','.join(self._silence)
        else:
            silent_mode = 'off'
        self.notice(nick,
                    f"{self._irc.bytes_sent() / 1024:.2f}kiB sent, "
                    f"{self._irc.bytes_received() / 1024:.2f}kiB received "
                    f"in {duration(int(time.time() - start_time))}. "
                    f"{online_count} player{plural(online_count)} online of "
                    f"{self._db.count_players()} total users. "
                    f"{self._new_accounts} account{plural(self._new_accounts)} created since startup. "
                    f"PAUSE_MODE is {'on' if self._pause else 'off'}, "
                    f"SILENT_MODE is {silent_mode}. "
                    f"Outgoing queue is {q_bytes} byte{plural(q_bytes)} "
                    f"in {q_msgs} item{plural(q_msgs)}. "
                    f"On via: {self._irc.servername()}. {admin_notice}")


    def cmd_whoami(self, player: Player, nick: str, args: str) -> None:
        """display game character information."""
        self.notice(nick, f"You are {C('name', player.name)}, the level {player.level} {player.cclass}. Next level in {duration(player.nextlvl)}.")


    def cmd_announce(self, player: Player, nick: str, args: str) -> None:
        """Send a message to the channel via the bot."""
        self.chanmsg(args)


    def cmd_status(self, player: Player, nick: str, args: str) -> None:
        """get status on player."""
        if not conf.get("statuscmd"):
            self.notice(nick, "You cannot do 'status'.")
            return
        if args == '':
            t = player
        elif args not in self._db:
            self.notice(nick, f"No such player '{args}'.")
            return
        else:
            t = self._db[args]
        self.notice(nick,
                    f"{C('name', t.name)}: Level {t.level} {t.cclass}; "
                    f"Status: {'Online' if t.online else 'Offline'}; "
                    f"TTL: {duration(t.nextlvl)}; "
                    f"Idled: {duration(t.idled)}; "
                    f"Item sum: {t.itemsum()}")


    def cmd_login(self, player: Player, nick: str, args: str) -> None:
        """start playing as existing character."""
        assert self._irc is not None
        if not self._irc.user_exists(nick):
            self.notice(nick, f"Sorry, you aren't on {conf.get('botchan')}.")
            return
        if player and self._irc.match_user(player.nick, player.userhost):
            self.notice(nick, f"You are already online as {C('name', player.name)}")
            return

        parts = args.split(' ', 1)
        if len(parts) != 2:
            self.notice(nick, "Try: LOGIN <username> <password>")
            return
        pname, ppass = parts
        if pname not in self._db:
            self.notice(nick, f"Sorry, no such account name.  Note that account names are case sensitive.")
            return
        if not self._db.check_login(pname, ppass):
            self.notice(nick, f"Wrong password.")
            return
        # Success!
        if conf.get("voiceonlogin") and self._irc.bot_has_ops():
            self._irc.grant_voice(nick)
        p = self._db[pname]
        userhost = self._irc.nick_userhost(nick)
        assert userhost is not None
        p.userhost = userhost
        p.lastlogin = datetime.datetime.now()
        if p.online and p.nick == nick:
            # If the player was already online and they have the same
            # nick, they need no reintroduction to the channel.
            self.notice(nick, f"Welcome back, {C('name', p.name)}. Next level in {duration(p.nextlvl)}.")
        else:
            p.online = True
            p.nick = nick
            self.notice(nick, f"Logon successful. Next level in {duration(p.nextlvl)}.")
            self.chanmsg(f"{C('name', p.name)}, the level {p.level} {p.cclass}, is now online from nickname {nick}. Next level in {duration(p.nextlvl)}.")
        self._db.write_players([p])


    def cmd_register(self, player: Player, nick: str, args: str) -> None:
        """start game as new player."""
        assert self._irc is not None
        if player:
            self.notice(nick, f"Sorry, you are already online as {C('name', player.name)}")
            return
        if not self._irc.user_exists(nick):
            self.notice(nick, f"Sorry, you aren't on {conf.get('botchan')}")
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
        if pname in self._db:
            self.notice(nick, "Sorry, that character name is already in use.")
        elif self._irc.is_bot_nick(pname):
            self.notice(nick, "That character name cannot be registered.")
        elif len(parts[1]) < 1 or len(pname) > conf.get("max_name_len"):
            self.notice(nick, f"Sorry, character names must be between 1 and {conf.get('max_name_len')} characters long.")
        elif len(parts[1]) < 1 or len(pclass) > conf.get("max_class_len"):
            self.notice(nick, f"Sorry, character classes must be between 1 and {conf.get('max_class_len')} characters long.")
        elif pname[0] == "#":
            self.notice(nick, "Sorry, character names may not start with #.")
        elif not pname.isprintable():
            self.notice(nick, "Sorry, character names may not include control codes.")
        elif not pclass.isprintable():
            self.notice(nick, "Sorry, character classes may not include control codes.")
        else:
            player = self._db.new_player(pname, pclass, ppass)
            player.online = True
            player.nick = nick
            userhost = self._irc.nick_userhost(nick)
            assert userhost is not None
            player.userhost = userhost
            player.posx = rand.randint("new_player_posy", 0, conf.get("mapx"))
            player.posy = rand.randint("new_player_posy", 0, conf.get("mapy"))

            if conf.get("voiceonlogin") and self._irc.bot_has_ops():
                self._irc.grant_voice(nick)
            self.chanmsg(f"Welcome {nick}'s new player {C('name', pname)}, the {pclass}!  Next level in {duration(player.nextlvl)}.")
            self.notice(nick, f"Success! Account {C('name', pname)} created. You have {duration(player.nextlvl)} seconds of idleness until you reach level 1.")
            self.notice(nick, "NOTE: The point of the game is to see who can idle the longest. As such, talking in the channel, parting, quitting, and changing nicks all penalize you.")
            self._new_accounts += 1


    def cmd_removeme(self, player: Player, nick: str, args: str) -> None:
        """Delete own character."""
        assert self._irc is not None
        if args == "":
            self.notice(nick, "Try: REMOVEME <password>")
        elif not self._db.check_login(player.name, args):
            self.notice(nick, "Wrong password.")
        else:
            self.notice(nick, f"Account {C('name', player.name)} removed.")
            self.chanmsg(f"{nick} removed their account. {C('name', player.name)}, the level {player.level} {player.cclass} is no more.")
            self._db.delete_player(player.name)
            if conf.get("voiceonlogin") and self._irc.bot_has_ops():
                self._irc.revoke_voice(nick)


    def cmd_newpass(self, player: Player, nick: str, args: str) -> None:
        """change own password."""
        parts = args.split(' ', 1)
        if len(parts) != 2:
            self.notice(nick, "Try: NEWPASS <old password> <new password>")
        elif not self._db.check_login(player.name, parts[0]):
            self.notice(nick, "Wrong password.")
        else:
            player.set_password(parts[1])
            self._db.write_players([player])
            self.notice(nick, "Your password was changed.")


    def cmd_logout(self, player: Player, nick: str, args: str) -> None:
        """stop playing as character."""
        assert self._irc is not None
        self.notice(nick, "You have been logged out.")
        player.online = False
        player.lastlogin = datetime.datetime.now()
        self._db.write_players([player])
        if conf.get("voiceonlogin") and self._irc.bot_has_ops():
                self._irc.revoke_voice(nick)
        self.penalize(player, "logout")


    def cmd_backup(self, player: Player, nick: str, args: str) -> None:
        """copy database file to a backup directory."""
        self._db.backup_store()
        self.notice(nick, "Player database backed up.")


    def cmd_chclass(self, player: Player, nick: str, args: str) -> None:
        """change another player's character class."""
        parts = args.split(' ', 1)
        if len(parts) != 2:
            self.notice(nick, "Try: CHCLASS <account> <new class>")
        elif parts[0] not in self._db:
            self.notice(nick, f"{parts[0]} is not a valid account.")
        elif len(parts[1]) < 1 or len(parts[1]) > conf.get("max_class_len"):
            self.notice(nick, f"Character classes must be between 1 and {conf.get('max_class_len')} characters long.")
        elif not parts[1].isprintable():
            self.notice(nick, "Character classes may not include control codes.")
        else:
            self._db[parts[0]].cclass = parts[1]
            self.notice(nick, f"{parts[0]}'s character class is now '{parts[1]}'.")


    def cmd_chpass(self, player: Player, nick: str, args: str) -> None:
        """change another player's password."""
        parts = args.split(' ', 1)
        if len(parts) != 2:
            self.notice(nick, "Try: CHPASS <account> <new password>")
        elif parts[0] not in self._db:
            self.notice(nick, f"{parts[0]} is not a valid account.")
        else:
            self._db[parts[0]].set_password(parts[1])
            self.notice(nick, f"{parts[0]}'s password changed.")


    def cmd_chuser(self, player: Player, nick: str, args: str) -> None:
        """Change someone's username."""
        parts = args.split(' ', 1)
        if len(parts) != 2:
            self.notice(nick, "Try: CHPASS <account> <new account name>")
        elif parts[0] not in self._db:
            self.notice(nick, f"{parts[0]} is not a valid account.")
        elif parts[1] in self._db:
            self.notice(nick, f"{parts[1]} is already taken.")
        elif len(parts[1]) < 1 or len(parts[1]) > conf.get("max_name_len"):
            self.notice(nick, f"Character names must be between 1 and {conf.get('max_name_len')} characters long.")
        elif parts[1][0] == "#":
            self.notice(nick, "Character names may not start with a #.")
        elif not parts[1].isprintable():
            self.notice(nick, "Character names may not include control codes.")
        else:
            self._db.rename_player(parts[0], parts[1])
            self.notice(nick, f"{parts[0]} is now known as {parts[1]}.")


    def cmd_config(self, player: Player, nick: str, args: str) -> None:
        """View/set a configuration setting."""
        if args == "":
            self.notice(nick, "Try: CONFIG <key search> or CONFIG <key> <value>")
            return

        parts = args.split(' ', 2)
        if len(parts) == 1:
            if conf.has(parts[0]):
                self.notice(nick, f"{parts[0]} {conf.get(parts[0])}")
            else:
                self.notice(nick, f"Matching config keys: {', '.join([k for k in conf._conf if parts[0] in k])}")
            return
        if not conf.has(parts[0]):
            self.notice(nick, f"{parts[0]} is not a config key.")
            return
        val = conf.parse_val(parts[1])
        conf._conf[parts[0]] = val
        self.notice(nick, f"{parts[0]} set to {val}.")


    def cmd_clearq(self, player: Player, nick: str, args: str) -> None:
        """Clear outgoing message queue."""
        assert self._irc is not None
        self._irc.clear_writeq()
        self.notice(nick, "Output queue cleared.")


    def cmd_del(self, player: Player, nick: str, args: str) -> None:
        """Delete another player's account."""
        if args not in self._db:
            self.notice(nick, f"{args} is not a valid account.")
        else:
            self._db.delete_player(args)
            self.notice(nick, f"{args} has been deleted.")


    def cmd_deladmin(self, player: Player, nick: str, args: str) -> None:
        """Remove admin authority."""
        if args not in self._db:
            self.notice(nick, f"{args} is not a valid account.")
        elif not self._db[args].isadmin:
            self.notice(nick, f"{args} is already not an admin.")
        elif args == conf.get("owner"):
            self.notice(nick, f"You can't do that.")
        else:
            self._db[args].isadmin = False
            self._db.write_players([player])
            self.notice(nick, f"{args} is no longer an admin.")


    def cmd_delold(self, player: Player, nick: str, args: str) -> None:
        """Remove players not accessed in a number of days."""
        if not re.match(r"\d+", args):
            self.notice(nick, "Try DELOLD <# of days>")
            return
        days = int(args)
        if days < 7:
            self.notice(nick, "That seems a bit low.")
            return
        expire_time = int(time.time()) - days * 86400
        old = [p.name for p in self._db.inactive_since(expire_time)]
        for pname in old:
            self._db.delete_player(pname)
        self.chanmsg(f"{len(old)} account{plural(len(old))} not accessed "
                     f"in the last {days} days removed by {C('name', player.name)}.")


    def cmd_die(self, player: Player, nick: str, args: str) -> None:
        """Shut down the bot."""
        assert self._irc is not None
        self.notice(nick, "Shutting down.")
        log.info("%s (as %s) initiated shutdown.", player.name, nick)
        self._irc.quit("Shutting down for maintenance.")
        sys.exit(0)


    def cmd_jump(self, player: Player, nick: str, args: str) -> None:
        """Switch to new IRC server."""
        # Not implemented.
        pass


    def cmd_mkadmin(self, player: Player, nick: str, args: str) -> None:
        """Grant admin authority to player."""
        if args not in self._db:
            self.notice(nick, f"{args} is not a valid account.")
        elif self._db[args].isadmin:
            self.notice(nick, f"{args} is already an admin.")
        else:
            self._db[args].isadmin = True
            self._db.write_players([self._db[args]])
            self.notice(nick, f"{args} is now an admin.")


    def cmd_pause(self, player: Player, nick: str, args: str) -> None:
        """Toggle pause mode."""
        self._pause = not self._pause
        if self._pause:
            self.notice(nick, "Pause mode enabled.")
        else:
            self.notice(nick, "Pause mode disabled.")


    def cmd_rehash(self, player: Player, nick: str, args: str) -> None:
        """Re-read configuration file."""
        conf.read_config(conf.get("confpath"))
        self.notice(nick, "Configuration reloaded.")


    def cmd_reloaddb(self, player: Player, nick: str, args: str) -> None:
        """Reload the player database."""
        if not self._pause:
            self.notice(nick, "ERROR: can only use RELOADDB while in PAUSE mode.")
            return
        self._db.load_state()


    def cmd_restart(self, player: Player, nick: str, args: str) -> None:
        """Restart from scratch."""
        # Not implemented.
        pass


    def cmd_silent(self, player: Player, nick: str, args: str) -> None:
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


    def cmd_hog(self, player: Player, nick: str, args: str) -> None:
        """Trigger Hand of God."""
        self.chanmsg(f"{C('name', player.name)} has summoned the Hand of God.")
        self.hand_of_god(self._db.online_players())


    def cmd_push(self, player: Player, nick: str, args: str) -> None:
        """Push someone toward or away from their next level."""
        parts = args.split(' ')
        if len(parts) != 2 or not re.match(r'[+-]?\d+', parts[1]):
            self.notice(nick, "Try: PUSH <char name> <seconds>")
            return
        if parts[0] not in self._db:
            self.notice(nick, f"No such username {parts[0]}.")
            return
        target = self._db[parts[0]]
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
        self.logchanmsg([target],
                        f"{C('name', player.name)} has pushed {C('name', target.name)} {abs(amount)} seconds {direction} "
                        f"level {target.level + 1}.  {C('name', target.name)} reaches next level "
                        f"in {duration(target.nextlvl)}.")


    def cmd_trigger(self, player: Player, nick: str, args: str) -> None:
        """Trigger in-game events"""
        if args == 'calamity':
            self.chanmsg(f"{C('name', player.name)} brings down ruin upon the land.")
            self.calamity()
        elif args == 'godsend':
            self.chanmsg(f"{C('name', player.name)} rains blessings upon the people.")
            self.godsend()
        elif args == 'hog':
            self.chanmsg(f"{C('name', player.name)} has summoned the Hand of God.")
            self.hand_of_god(self._db.online_players())
        elif args == 'teambattle':
            self.chanmsg(f"{C('name', player.name)} has decreed violence.")
            self.team_battle(self._db.online_players())
        elif args == 'evilness':
            self.chanmsg(f"{C('name', player.name)} has swept the lands with evil.")
            self.evilness(self._db.online_players())
        elif args == 'goodness':
            self.chanmsg(f"{C('name', player.name)} has drawn down light from the heavens.")
            self.goodness(self._db.online_players())
        elif args == 'battle':
            self.chanmsg(f"{C('name', player.name)} has called forth a gladitorial arena.")
            self.challenge_opp(rand.choice('triggered_battle', self._db.online_players()))
        elif args == 'quest':
            self.chanmsg(f"{C('name', player.name)} has called heroes to a quest.")
            if self._quest:
                self.notice(nick, "There's already a quest on.")
                return
            qp = [p for p in self._db.online_players() if p.level > conf.get("quest_min_level")]
            if len(qp) < 4:
                self.notice(nick, "There's not enough eligible players.")
                return
            self.notice(nick, "Starting quest.")
            self.quest_start(int(time.time()))


    def cmd_quest(self, player: Player, nick: str, args: str) -> None:
        """Get information on current quest."""
        assert self._irc is not None
        if self._quest is None:
            self.notice(nick, "There is no active quest.")
        elif self._quest.mode == 1:
            assert self._quest.qtime is not None
            qp = self._quest.questors
            self.notice(nick,
                        f"{C('name', qp[0].name)}, {C('name', qp[1].name)}, {C('name', qp[2].name)}, and {C('name', qp[3].name)} "
                        f"are on a quest to {self._quest.text}. Quest to complete in "
                        f"{duration(int(self._quest.qtime - time.time()))}.")
        elif self._quest.mode == 2:
            assert self._quest.dests is not None
            qp = self._quest.questors
            mapnotice = ''
            if conf.has("mapurl"):
                mapnotice = f" See {conf.get('mapurl')} to monitor their journey's progress."
            self.notice(nick,
                        f"{C('name', qp[0].name)}, {C('name', qp[1].name)}, {C('name', qp[2].name)}, and {C('name', qp[3].name)} "
                        f"are on a quest to {self._quest.text}. Participants must first reach "
                        f"({self._quest.dests[0][0]}, {self._quest.dests[0][1]}), then "
                        f"({self._quest.dests[1][0]}, {self._quest.dests[1][1]}).{mapnotice}")


    def penalize(self, player: Player, kind: str, text: Optional[str]=None) -> None:
        """Exact penalities on a transgressing player."""
        penalty = conf.get("pen"+kind)
        if penalty == 0:
            return

        if self._quest and player in self._quest.questors:
            op = self._db.online_players()
            self.logchanmsg(op,
                            f"{C('name')}{player.name}'s{C()} insolence has brought the wrath of "
                            f"the gods down upon them.  Your great wickedness "
                            f"burdens you like lead, drawing you downwards with "
                            f"great force towards hell. Thereby have you plunged "
                            f"{conf.get('penquest')} steps closer to that gaping maw.")
            for p in op:
                gain = int(conf.get("penquest") * (conf.get("rppenstep") ** p.level))
                p.penquest += gain
                p.nextlvl += gain

            self._quest = None
            self._qtimer = time.time() + conf.get("quest_interval_min")

        if text:
            penalty *= len(text)
        penalty *= int(conf.get("rppenstep") ** player.level)
        if conf.has("limitpen") and penalty > conf.get("limitpen"):
            penalty = conf.get("limitpen")
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


    def refresh_events(self) -> None:
        """Read events file if it has changed."""
        if self._events_loaded == os.path.getmtime(datapath(conf.get("eventsfile"))):
            return

        self._events = {}
        with open(datapath(conf.get("eventsfile"))) as inf:
            for line in inf.readlines():
                line = line.rstrip()
                if line != "":
                    self._events.setdefault(line[0], []).append(line[1:].lstrip())


    def expire_splits(self) -> None:
        """Kick players offline if they were disconnected for too long."""
        assert self._irc is not None
        expiration = time.time() - conf.get("splitwait")
        dropped_players = []
        for p in self._db.online_players():
            if self._irc.user_exists(p.nick):
                continue
            if p.lastlogin.timestamp() > expiration:
                continue
            log.info("Expiring %s who was logged in as %s but was lost in a netsplit.", p.nick, p.name)
            self.penalize(p, "dropped")
            p.online = False
            dropped_players.append(p)

        self._db.write_players(dropped_players)

    async def gametick_loop(self) -> None:
        """Main gameplay loop to manage timing."""
        try:
            last_time = time.time() - 1
            while self._state == 'ready':
                await asyncio.sleep(conf.get("self_clock"))
                now = time.time()
                self.gametick(int(now), int(now - last_time))
                last_time = now
        except Exception as err:
            log.exception(err)
            sys.exit(2)


    def gametick(self, now: int, passed: int) -> None:
        """Main gameplay routine."""
        if conf.get("detectsplits"):
            self.expire_splits()
        self.refresh_events()

        op = self._db.online_players()
        online_count = 0
        evil_count = 0
        good_count = 0
        for player in op:
            online_count += 1
            if player.alignment == 'e':
                evil_count += 1
            elif player.alignment == 'g':
                good_count += 1

        day_ticks = 86400/conf.get("self_clock")
        if rand.randint('hog_trigger', 0, 20 * day_ticks) < online_count:
            self.hand_of_god(op)
        if rand.randint('team_battle_trigger', 0, 24 * day_ticks) < online_count:
            self.team_battle(op)
        if rand.randint('calamity_trigger', 0, 8 * day_ticks) < online_count:
            self.calamity()
        if rand.randint('godsend_trigger', 0, 4 * day_ticks) < online_count:
            self.godsend()
        if rand.randint('evilness_trigger', 0, 8 * day_ticks) < evil_count:
            self.evilness(op)
        if rand.randint('goodness_trigger', 0, 12 * day_ticks) < good_count:
            self.goodness(op)

        self.move_players()
        self.quest_check(now)

        if now % 120 == 0 and self._quest:
            self._db.update_quest(self._quest)
        if now % 36000 == 0:
            top = self._db.top_players()
            if top:
                self.chanmsg("Idle RPG Top Players:")
                for i, p in zip(itertools.count(), top):
                    self.chanmsg(f"{C('name', p.name)}, the level {p.level} {p.cclass}, is #{i+1}! "
                                 f"Next level in {duration(p.nextlvl)}.")
            self._db.backup_store()
        # high level players fight each other randomly
        hlp = [p for p in op if p.level >= 45]
        if now % 3600 == 0 and len(hlp) > len(op) * 0.15:
            self.challenge_opp(rand.choice('pvp_combat', hlp))

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
                    player.nextlvl = int(conf.get("rpbase") * conf.get("rpstep") ** 60) + (86400 * (player.level - 60))
                else:
                    player.nextlvl = int(conf.get("rpbase") * conf.get("rpstep") ** player.level)

                self.chanmsg(f"{C('name', player.name)}, the {player.cclass}, has attained level {player.level}! Next level in {duration(player.nextlvl)}.")
                self.find_item(player)
                # Players below level 25 have fewer battles.
                if player.level >= 25 or rand.randomly('lowlevel_battle', 4):
                    self.challenge_opp(player)

        self._db.write_players(op)


    def hand_of_god(self, op: List[Player]) -> None:
        """Hand of God that pushes a random player forword or back."""
        player = rand.choice('hog_player', op)
        amount = int(player.nextlvl * (5 + rand.randint('hog_amount', 0, 71))/100)
        if rand.randomly('hog_effect', 5):
            self.logchanmsg([player], f"Thereupon He stretched out His little finger among them and consumed {C('name', player.name)} with fire, slowing the heathen {duration(amount)} from level {player.level + 1}.")
            player.nextlvl += amount
        else:
            self.logchanmsg([player], f"Verily I say unto thee, the Heavens have burst forth, and the blessed hand of God carried {C('name', player.name)} {duration(amount)} toward level {player.level + 1}.")
            player.nextlvl -= amount
        self.chanmsg(f"{C('name', player.name)} reaches next level in {duration(player.nextlvl)}.")
        self._db.write_players([player])


    def find_item(self, player: Player) -> None:
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
            if player.level >= si.minlvl and rand.randomly('specitem_find', 40):
                ilvl = si.itemlvl + rand.randint('specitem_level', 0, si.lvlspread)
                player.acquire_item(si.kind, ilvl, si.name)
                self.notice(player.nick,
                                 f"The light of the gods shines down upon you! You have "
                                 f"found the {C('item')}level {ilvl} {si.name}{C()}!  {si.flavor}")
                return

        slot = rand.choice('find_item_slot', Item.SLOTS)
        level = rand.gauss('find_item_level',
                           player.level,
                           player.level / 5)

        old_level = player.item_level(slot)
        if level > old_level:
            self.notice(player.nick,
                        f"You found a {C('item')}level {level} {Item.DESC[slot]}{C()}! "
                        f"Your current {C('item')}{Item.DESC[slot]}{C()} is only "
                        f"level {old_level}, so it seems Luck is with you!")
            player.acquire_item(slot, level)
            self._db.write_players([player])
        else:
            self.notice(player.nick,
                        f"You found a {C('item')}level {level} {Item.DESC[slot]}{C()}. "
                        f"Your current {C('item', Item.DESC[slot])} is level {old_level}, "
                        f"so it seems Luck is against you.  You toss the {C('item', Item.DESC[slot])}.")


    def pvp_battle(self, player: Player, opp: Optional[Player], flavor_start: str, flavor_win: str, flavor_loss: str) -> None:
        """Enact a powerful player-vs-player battle."""
        if opp is None:
            oppname = conf.get("botnick")
            oppsum = self._db.max_player_power()+1
        else:
            oppname = opp.name
            oppsum = opp.battleitemsum()

        playersum = player.battleitemsum()
        playerroll = rand.randint('pvp_player_roll', 0, playersum)
        opproll = rand.randint('pvp_opp_roll', 0, oppsum)
        if playerroll >= opproll:
            gain = 20 if opp is None else max(7, int(opp.level / 4))
            amount = int((gain / 100)*player.nextlvl)
            self.logchanmsg([player], f"{C('name', player.name)} [{playerroll}/{playersum}] has {flavor_start} "
                            f"{C('name', oppname)} [{opproll}/{oppsum}] {flavor_win}! "
                            f"{duration(amount)} is removed from {C('name')}{player.name}'s{C()} clock.")
            player.nextlvl -= amount
            if player.nextlvl > 0:
                self.chanmsg(f"{C('name', player.name)} reaches next level in {duration(player.nextlvl)}.")
            if opp is not None:
                if rand.randomly('pvp_critical', {'g': 50, 'n': 35, 'e': 20}[player.alignment]):
                    penalty = int(((5 + rand.randint('pvp_cs_penalty_pct', 0, 20))/100 * opp.nextlvl))
                    self.logchanmsg([opp], f"{C('name', player.name)} has dealt {C('name', opp.name)} a {CC('red')}Critical Strike{C()}! "
                                    f"{duration(penalty)} is added to {C('name', opp.name)}'s clock.")
                    opp.nextlvl += penalty
                    self.chanmsg(f"{C('name', opp.name)} reaches next level in {duration(opp.nextlvl)}.")
                elif player.level > 19 and rand.randomly('pvp_swap_item', 25):
                    slot = rand.choice('pvp_swap_itemtype', Item.SLOTS)
                    playeritem = player.item_level(slot)
                    oppitem = opp.item_level(slot)
                    if oppitem > playeritem:
                        self.logchanmsg([player, opp], f"In the fierce battle, {C('name', opp.name)} dropped their {C('item')}level "
                                        f"{oppitem} {Item.DESC[slot]}{C()}! {C('name', player.name)} picks it up, tossing "
                                        f"their old {C('item')}level {playeritem} {Item.DESC[slot]}{C()} to {C('name', opp.name)}.")
                        player.swap_items(opp, slot)
        else:
            # Losing
            loss = 10 if opp is None else max(7, int(opp.level / 7))
            amount = int((loss / 100)*player.nextlvl)
            self.logchanmsg([player], f"{C('name', player.name)} [{playerroll}/{playersum}] has {flavor_start} "
                            f"{oppname} [{opproll}/{oppsum}] {flavor_loss}! {duration(amount)} is "
                            f"added to {C('name')}{player.name}'s{C()} clock.")
            player.nextlvl += amount
            self.chanmsg(f"{C('name', player.name)} reaches next level in {duration(player.nextlvl)}.")

        if rand.randomly('pvp_find_item', {'g': 50, 'n': 67, 'e': 100}[player.alignment]):
            self.logchanmsg([player], f"While recovering from battle, {C('name', player.name)} notices a glint "
                         f"in the mud. Upon investigation, they find an old lost item!")
            self.find_item(player)


    def challenge_opp(self, player: Player) -> None:
        """Pit player against another random player."""
        op = cast(List[Optional[Player]], self._db.online_players())
        op.remove(player)       # Let's not fight ourselves
        op.append(None)         # This is the bot opponent
        self.pvp_battle(player, rand.choice('challenge_opp_choice', op), 'challenged', 'and won', 'and lost')


    def team_battle(self, op: List[Player]) -> None:
        """Have a 3-vs-3 battle between teams."""
        if len(op) < 6:
            return
        op = rand.sample('team_battle_members', op, 6)
        team_a = sum([p.battleitemsum() for p in op[0:3]])
        team_b = sum([p.battleitemsum() for p in op[3:6]])
        gain = int(min([p.nextlvl for p in op[0:6]]) * 0.2)
        roll_a = rand.randint('team_a_roll', 0, team_a)
        roll_b = rand.randint('team_b_roll', 0, team_b)
        if roll_a >= roll_b:
            self.logchanmsg(op[0:3], f"{C('name', op[0].name)}, {C('name', op[1].name)}, and {C('name', op[2].name)} [{roll_a}/{team_a}] "
                            f"have team battled {C('name', op[3].name)}, {C('name', op[4].name)}, and {C('name', op[5].name)} "
                            f"[{roll_b}/{team_b}] and won!  {duration(gain)} is removed from their clocks.")
            for p in op[0:3]:
                p.nextlvl -= gain
        else:
            self.logchanmsg(op[0:3], f"{C('name', op[0].name)}, {C('name', op[1].name)}, and {C('name', op[2].name)} [{roll_a}/{team_a}] "
                            f"have team battled {C('name', op[3].name)}, {C('name', op[4].name)}, and {C('name', op[5].name)} "
                            f"[{roll_b}/{team_b}] and lost!  {duration(gain)} is added to their clocks.")
            for p in op[0:3]:
                p.nextlvl += gain


    def calamity(self) -> None:
        """Bring bad things to a random player."""
        player = rand.choice('calamity_target', self._db.online_players())
        if not player:
            return

        if player.items and rand.randomly('calamity_item_damage', 10):
            # Item damaging calamity
            slot = rand.choice('calamity_slot', sorted(player.items.keys()))
            if slot == "ring":
                msg = f"{C('name', player.name)} accidentally smashed their {C('item', 'ring')} with a hammer!"
            elif slot == "amulet":
                msg = f"{C('name', player.name)} fell, chipping the stone in their {C('item', 'amulet')}!"
            elif slot == "charm":
                msg = f"{C('name', player.name)} slipped and dropped their {C('item', 'charm')} in a dirty bog!"
            elif slot == "weapon":
                msg = f"{C('name', player.name)} left their {C('item', 'weapon')} out in the rain to rust!"
            elif slot == "helm":
                msg = f"{C('name')}{player.name}'s{C()} {C('item', 'helm')} was touched by a rust monster!"
            elif slot == "tunic":
                msg = f"{C('name', player.name)} spilled a level 7 shrinking potion on their {C('item', 'tunic')}!"
            elif slot == "gloves":
                msg = f"{C('name', player.name)} dipped their gloved fingers in a pool of acid!"
            elif slot == "leggings":
                msg = f"{C('name', player.name)} burned a hole through their {C('item', 'leggings')} while ironing them!"
            elif slot == "shield":
                msg = f"{C('name')}{player.name}'s{C()} {C('item', 'shield')} was damaged by a dragon's fiery breath!"
            elif slot == "boots":
                msg = f"{C('name', player.name)} stepped in some hot lava!"
            self.logchanmsg([player], msg + f" {C('name')}{player.name}'s{C()} {C('item', Item.DESC[slot])} loses 10% of its effectiveness.")
            player.items[slot].level = int(player.items[slot].level * 0.9)
            return

        # Level setback calamity
        amount = int(rand.randint('calamity_setback_pct', 5, 13) / 100 * player.nextlvl)
        player.nextlvl += amount
        action = rand.choice('calamity_action', self._events["C"])
        self.logchanmsg([player], f"{C('name', player.name)} {action}! This terrible calamity has slowed them "
                        f"{duration(amount)} from level {player.level + 1}.")
        if player.nextlvl > 0:
            self.chanmsg(f"{C('name', player.name)} reaches next level in {duration(player.nextlvl)}.")


    def godsend(self) -> None:
        """Bring good things to a random player."""
        player = rand.choice('godsend_target', self._db.online_players())
        if not player:
            return

        if player.items and rand.randomly('godsend_item_improve', 10):
            # Item improving godsend
            slot = rand.choice('godsend_slot', sorted(player.items.keys()))
            if slot == "ring":
                msg = f"{C('name', player.name)} dipped their {C('item', 'ring')} into a sacred fountain!"
            elif slot == "amulet":
                msg = f"{C('name')}{player.name}'s{C()} {C('item', 'amulet')} was blessed by a passing cleric!"
            elif slot == "charm":
                msg = f"{C('name')}{player.name}'s{C()} {C('item', 'charm')} ate a bolt of lightning!"
            elif slot == "weapon":
                msg = f"{C('name', player.name)} sharpened the edge of their {C('item', 'weapon')}!"
            elif slot == "helm":
                msg = f"{C('name', player.name)} polished their {C('item', 'helm')} to a mirror shine."
            elif slot == "tunic":
                msg = f"A magician cast a spell of Rigidity on {C('name')}{player.name}'s{C()} {C('item', 'tunic')}!"
            elif slot == "gloves":
                msg = f"{C('name', player.name)} lined their {C('item', 'gloves')} with a magical cloth!"
            elif slot == "leggings":
                msg = f"The local wizard imbued {C('name')}{player.name}'s{C()} {C('item', 'pants')} with a Spirit of Fortitude!"
            elif slot == "shield":
                msg = f"{C('name', player.name)} reinforced their {C('item', 'shield')} with a dragon's scale!"
            elif slot == "boots":
                msg = f"A sorceror enchanted {C('name')}{player.name}'s{C()} {C('item', 'boots')} with Swiftness!"

            self.logchanmsg([player], msg + f" {C('name')}{player.name}'s{C()} {C('item', Item.DESC[slot])} gains 10% effectiveness.")
            player.items[slot].level = int(player.items[slot].level * 1.1)
            return

        # Level godsend
        amount = int(rand.randint('godsend_amount_pct', 5, 13) / 100 * player.nextlvl)
        player.nextlvl -= amount
        action = rand.choice('godsend_action', self._events["G"])
        self.logchanmsg([player], f"{C('name', player.name)} {action}! This wondrous godsend has accelerated them "
                        f"{duration(amount)} towards level {player.level + 1}.")
        if player.nextlvl > 0:
            self.chanmsg(f"{C('name', player.name)} reaches next level in {duration(player.nextlvl)}.")


    def evilness(self, op: List[Player]) -> None:
        """Bring evil or an item to a random evil player."""
        evil_p = [p for p in op if p.alignment == 'e']
        if not evil_p:
            return
        player = rand.choice('evilness_player', evil_p)
        if rand.randomly('evilness_theft', 2):
            target = rand.choice('evilness_target', [p for p in op if p.alignment == 'g'])
            if not target:
                return
            slot = rand.choice('evilness_slot', Item.SLOTS)
            if player.item_level(slot) < target.item_level(slot):
                player.swap_items(target, slot)
                self.logchanmsg([player, target],
                                f"{C('name', player.name)} stole {target.name}'s {C('item')}level {player.item_level(slot)} "
                                f"{Item.DESC[slot]}{C()} while they were sleeping!  {C('name', player.name)} "
                                f"leaves their old {C('item')}level {target.item_level(slot)} {Item.DESC[slot]}{C()} "
                                f"behind, which {C('name', target.name)} then takes.")
            else:
                self.notice(player.nick,
                            f"You made to steal {C('name', target.name)}'s {C('item', Item.DESC[slot])}, "
                            f"but realized it was lower level than your own.  You creep "
                            f"back into the shadows.")
        else:
            amount = int(player.nextlvl * rand.randint('evilness_penalty_pct', 1,6) / 100)
            player.nextlvl += amount
            self.logchanmsg([player], f"{C('name', player.name)} is forsaken by their evil god. {duration(amount)} is "
                              f"added to their clock.")
            if player.nextlvl > 0:
                self.chanmsg(f"{C('name', player.name)} reaches next level in {duration(player.nextlvl)}.")

    def goodness(self, op: List[Player]) -> None:
        """Bring two good players closer to their next level."""
        good_p = [p for p in op if p.alignment == 'g']
        if len(good_p) < 2:
            return
        players = rand.sample('goodness_players', good_p, 2)
        gain = rand.randint('goodness_gain_pct', 5, 13)
        self.logchanmsg([players[0], players[1]],
                        f"{C('name', players[0].name)} and {C('name', players[1].name)} have not let the iniquities "
                        f"of evil people poison them. Together have they prayed to their god, "
                        f"and light now shines down upon them. {gain}% of their time is removed "
                        f"from their clocks.")
        for player in players:
            player.nextlvl = int(player.nextlvl * (1 - gain / 100))
            if player.nextlvl > 0:
                self.chanmsg(f"{C('name', player.name)} reaches next level in {duration(player.nextlvl)}.")


    def move_players(self) -> None:
        """Move players around the map."""
        op = self._db.online_players()
        if not op:
            return
        rand.shuffle('move_players_order', op)
        mapx = conf.get("mapx")
        mapy = conf.get("mapy")
        combatants: Dict[Tuple[int,int], Player] = dict()
        if self._quest and self._quest.mode == 2:
            assert self._quest.stage is not None
            assert self._quest.dests is not None
            destx = self._quest.dests[self._quest.stage-1][0]
            desty = self._quest.dests[self._quest.stage-1][1]
            for p in self._quest.questors:
                if not rand.randomly("quest_movement", 10):
                    # Move at 10% speed when questing.
                    op.remove(p)
                    continue
                # mode 2 questors always move towards the next goal
                xmove = 0
                ymove = 0
                distx = destx - p.posx
                if distx != 0:
                    if abs(distx) > mapx/2:
                        distx = -distx
                    xmove = int(distx / abs(distx)) # normalize to -1/0/1

                disty = desty - p.posy
                if disty != 0:
                    if abs(disty) > mapy/2:
                        disty = -disty
                    ymove = int(disty / abs(disty)) # normalize to -1/0/1

                p.posx = (p.posx + xmove) % mapx
                p.posy = (p.posy + ymove) % mapy
                # take questors out of rotation for movement and pvp
                op.remove(p)

        for p in op:
            # everyone else wanders aimlessly
            p.posx = (p.posx + rand.randint('move_player_x',-1,1)) % mapx
            p.posy = (p.posy + rand.randint('move_player_y',-1,1)) % mapy

            if (p.posx, p.posy) in combatants:
                combatant = combatants[(p.posx, p.posy)]
                if combatant.isadmin and rand.randomly('move_player_bow', 100):
                    self.chanmsg(f"{C('name', p.name)} encounters {C('name', combatant.name)} and bows humbly.")
                elif rand.randomly('move_player_combat', len(op)):
                    self.pvp_battle(p, combatant,
                                    'come upon',
                                    'and taken them in combat',
                                    'and been defeated in combat')
                    del combatants[(p.posx, p.posy)]
            else:
                combatants[(p.posx, p.posy)] = p


    def quest_start(self, now: int) -> None:
        """Start a random quest with four random players."""
        latest_login_time = now - 36000
        qp = [p for p in self._db.online_players() if p.level > conf.get("quest_min_level") and p.lastlogin.timestamp() < latest_login_time]
        if len(qp) < 4:
            return
        qp = rand.sample('quest_members', qp, 4)
        questconf = rand.choice('quest_selection', self._events["Q"])
        match = (re.match(r'(1) (.*)', questconf) or
                 re.match(r'(2) (\d+) (\d+) (\d+) (\d+) (.*)', questconf))
        if not match:
            return
        self._quest = Quest()
        self._quest.questors = qp
        if match[1] == '1':
            quest_time = rand.randint('quest_time', 6, 12)*3600
            self._quest.mode = 1
            self._quest.text = match[2]
            self._quest.qtime = int(time.time()) + quest_time
            self.chanmsg(f"{C('name', qp[0].name)}, {C('name', qp[1].name)}, {C('name', qp[2].name)}, and {C('name', qp[3].name)} have "
                         f"been chosen by the gods to {self._quest.text}.  Quest to end in "
                         f"{duration(quest_time)}.")
        elif match[1] == '2':
            self._quest.mode = 2
            self._quest.stage = 1
            self._quest.dests = [(int(match[2]), int(match[3])), (int(match[4]), int(match[5]))]
            self._quest.text = match[6]
            mapnotice = ''
            if conf.has("mapurl"):
                mapnotice = f" See {conf.get('mapurl')} to monitor their journey's progress."
            self.chanmsg(f"{C('name', qp[0].name)}, {C('name', qp[1].name)}, {C('name', qp[2].name)}, and {C('name', qp[3].name)} have "
                         f"been chosen by the gods to {self._quest.text}.  Participants must first "
                         f"reach ({self._quest.dests[0][0]},{self._quest.dests[0][1]}), "
                         f"then ({self._quest.dests[1][0]},{self._quest.dests[1][1]}).{mapnotice}")
        self._db.update_quest(self._quest)


    def quest_check(self, now: int) -> None:
        """Complete quest if criteria are met."""
        if self._quest is None:
            if now >= self._qtimer:
                self.quest_start(now)
        elif self._quest.mode == 1:
            assert self._quest.qtime is not None
            if now >= self._quest.qtime:
                qp = self._quest.questors
                self.logchanmsg(qp,
                                f"{C('name', qp[0].name)}, {C('name', qp[1].name)}, {C('name', qp[2].name)}, and {C('name', qp[3].name)} "
                                f"have blessed the realm by completing their quest! 25% of "
                                f"their burden is eliminated.")
                for q in qp:
                    q.nextlvl = int(q.nextlvl * 0.75)
                self._quest = None
                self._qtimer = now + conf.get("quest_interval_min")
                self._db.update_quest(self._quest)
        elif self._quest.mode == 2:
            assert self._quest.stage is not None
            assert self._quest.dests is not None
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
                    self.logchanmsg(qp, f"{C('name', qp[0].name)}, {C('name', qp[1].name)}, {C('name', qp[2].name)}, and {C('name', qp[3].name)} "
                                    f"have completed their journey! 25% of "
                                    f"their burden is eliminated.")
                    for q in qp:
                        q.nextlvl = int(q.nextlvl * 0.75)
                    self._quest = None
                    self._qtimer = now + conf.get("quest_interval_min")
                self._db.update_quest(self._quest)
