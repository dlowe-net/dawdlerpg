#!/usr/bin/python3

import datetime
import os.path
import tempfile
import time
import unittest

from dawdle import irc
from dawdle import bot
from dawdle import conf

class TestGameDBSqlite3(unittest.TestCase):
    def test_db(self):
        conf._conf['rpbase'] = 600
        with tempfile.TemporaryDirectory() as tmpdir:
            db = bot.GameDB(bot.Sqlite3GameStorage(os.path.join(tmpdir, 'dawdle_test.db')))
            self.assertFalse(db.exists())
            db.create()
            p = db.new_player('foo', 'bar', 'baz')
            p.online = True
            db.write_players()
            self.assertTrue(db.exists())
            db.load_state()
            self.assertEqual(db['foo'].name, 'foo')
            self.assertEqual(db['foo'].online, True)
            db.close()

    def test_passwords(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = bot.GameDB(bot.Sqlite3GameStorage(os.path.join(tmpdir, 'dawdle_test.db')))
            self.assertFalse(db.exists())
            db.create()
            p = db.new_player('foo', 'bar', 'baz')
            self.assertTrue(db.check_login('foo', 'baz'))
            self.assertFalse(db.check_login('foo', 'azb'))
            p.set_password('azb')
            self.assertTrue(db.check_login('foo', 'azb'))
            db.close()


class TestGameDBIdleRPG(unittest.TestCase):
    def test_db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = bot.GameDB(bot.IdleRPGGameStorage(os.path.join(tmpdir, 'dawdle_test.db')))
            db.create()
            op = db.new_player('foo', 'bar', 'baz')
            op.items['amulet'] = bot.Item(55, '')
            op.items['helm'] = bot.Item(42, "Jeff's Cluehammer of Doom")
            db.write_players()
            db.load_state()
            p = db['foo']
            self.maxDiff = None
            self.assertEqual(vars(op), vars(p))
            db.close()


class FakeIRCClient(object):
    def __init__(self):
        self._nick = 'dawdlerpg'
        self._users = {}
        self.server = "irc.example.com"
        self.chanmsgs = []
        self.notices = {}

    def resetmsgs(self):
        self.chanmsgs = []
        self.notices = {}

    def chanmsg(self, text):
        self.chanmsgs.append(text)

    def notice(self, nick, text):
        self.notices.setdefault(nick, []).append(text)


class FakeGameStorage(bot.GameStorage):

    def __init__(self):
        self._mem = {}

    def create(self):
        pass

    def readall(self):
        pass

    def writeall(self, p):
        pass

    def close(self):
        pass

    def new(self, p):
        self._mem[p.name] = p

    def rename(self, old, new):
        self._mem[new] = self._mem[old]
        self._mem.pop(old)

    def delete(self, pname):
        self._mem.pop(pname)


class TestBot(unittest.TestCase):

    def test_nick_change(self):
        conf._conf['botnick'] = 'dawdlerpg'
        conf._conf['botchan'] = '#dawdlerpg'
        conf._conf['message_wrap_len'] = 400
        conf._conf['throttle'] = False
        conf._conf['pennick'] = 10
        conf._conf['penquit'] = 20
        conf._conf['rppenstep'] = 1.14

        testbot = bot.DawdleBot(bot.GameDB(FakeGameStorage()))
        testirc = FakeIRCClient()
        testbot.connected(testirc)
        testirc._users['foo'] = irc.IRCClient.User("foo", "foo!foo@example.com", [], 1)
        a = testbot._db.new_player('a', 'b', 'c')
        a.online = True
        a.nick = 'foo'
        a.userhost = 'foo!foo@example.com'
        self.assertEqual('foo', a.nick)
        testbot.nick_changed(testirc._users['foo'], 'bar')
        self.assertEqual('bar', a.nick)
        testbot.nick_quit(testirc._users['foo'])

class TestGameDB(unittest.TestCase):

    def test_top_players(self):
        db = bot.GameDB(FakeGameStorage())
        a = db.new_player('a', 'waffle', 'c')
        a.level, a.nextlvl = 30, 100
        b = db.new_player('b', 'doughnut', 'c')
        b.level, b.nextlvl = 20, 1000
        c = db.new_player('c', 'bagel', 'c')
        c.level, c.nextlvl = 10, 10
        self.assertEqual(['a', 'b', 'c'], [p.name for p in db.top_players()])


class TestPvPBattle(unittest.TestCase):


    def setUp(self):
        conf._conf['rpbase'] = 600
        conf._conf['modsfile'] = '/tmp/modsfile.txt'
        conf._conf['color'] = False
        self.bot = bot.DawdleBot(bot.GameDB(FakeGameStorage()))
        self.irc = FakeIRCClient()
        self.bot.connected(self.irc)


    def test_player_battle_win(self):
        a = self.bot._db.new_player('a', 'b', 'c')
        a.items['amulet'] = bot.Item(20, '')
        b = self.bot._db.new_player('b', 'c', 'd')
        b.items['amulet'] = bot.Item(40, '')
        self.bot._overrides = {
            'pvp_player_roll': 20,
            'pvp_opp_roll': 10,
            'pvp_critical': False,
            'pvp_swap_item': False,
            'pvp_find_item': False
        }
        self.bot.pvp_battle(a, b, "fought", "and has won", "and has lost")
        self.assertListEqual(self.irc.chanmsgs, [
            "a [20/20] has fought b [10/40] and has won! 0 days, 00:00:42 is removed from a's clock.",
            "a reaches next level in 0 days, 00:09:18."
            ])
        self.assertEqual(a.nextlvl, 558)


    def test_player_battle_bot(self):
        conf._conf['botnick'] = 'dawdlerpg'
        a = self.bot._db.new_player('a', 'b', 'c')
        a.items['amulet'] = bot.Item(20, '')
        self.bot._overrides = {
            'pvp_player_roll': 20,
            'pvp_opp_roll': 10,
            'pvp_critical': False,
            'pvp_swap_item': False,
            'pvp_find_item': False
        }
        self.bot.pvp_battle(a, None, "fought", "and has won", "and has lost")
        self.assertListEqual(self.irc.chanmsgs, [
            "a [20/20] has fought dawdlerpg [10/21] and has won! 0 days, 00:02:00 is removed from a's clock.",
            "a reaches next level in 0 days, 00:08:00."
            ])
        self.assertEqual(a.nextlvl, 480)


    def test_player_battle_lose(self):
        a = self.bot._db.new_player('a', 'b', 'c')
        a.items['amulet'] = bot.Item(20, '')
        b = self.bot._db.new_player('b', 'c', 'd')
        b.items['amulet'] = bot.Item(40, '')
        self.bot._overrides = {
            'pvp_player_roll': 10,
            'pvp_opp_roll': 20,
            'pvp_critical': False,
            'pvp_swap_item': False,
            'pvp_find_item': False
        }
        self.bot.pvp_battle(a, b, "fought", "and has won", "and has lost")
        self.assertListEqual(self.irc.chanmsgs, [
            "a [10/20] has fought b [20/40] and has lost! 0 days, 00:00:42 is added to a's clock.",
            "a reaches next level in 0 days, 00:10:42."
            ])
        self.assertEqual(a.nextlvl, 642)


    def test_player_battle_critical(self):
        a = self.bot._db.new_player('a', 'b', 'c')
        a.items['amulet'] = bot.Item(20, '')
        b = self.bot._db.new_player('b', 'c', 'd')
        b.items['amulet'] = bot.Item(40, '')
        self.bot._overrides = {
            'pvp_player_roll': 20,
            'pvp_opp_roll': 10,
            'pvp_critical': True,
            'pvp_cs_penalty_pct': 10,
            'pvp_swap_item': False,
            'pvp_find_item': False
        }
        self.bot.pvp_battle(a, b, "fought", "and has won", "and has lost")
        self.assertListEqual(self.irc.chanmsgs, [
            "a [20/20] has fought b [10/40] and has won! 0 days, 00:00:42 is removed from a's clock.",
            "a reaches next level in 0 days, 00:09:18.",
            "a has dealt b a Critical Strike! 0 days, 00:01:30 is added to b's clock.",
            "b reaches next level in 0 days, 00:11:30."
            ])
        self.assertEqual(a.nextlvl, 558)
        self.assertEqual(b.nextlvl, 690)


    def test_player_battle_swapitem(self):
        a = self.bot._db.new_player('a', 'b', 'c')
        a.level = 20
        a.items['amulet'] = bot.Item(20, '')
        b = self.bot._db.new_player('b', 'c', 'd')
        b.items['amulet'] = bot.Item(40, '')
        self.bot._overrides = {
            'pvp_player_roll': 20,
            'pvp_opp_roll': 10,
            'pvp_critical': False,
            'pvp_swap_item': True,
            'pvp_swap_itemtype': 'amulet',
            'pvp_find_item': False
        }
        self.bot.pvp_battle(a, b, "fought", "and has won", "and has lost")
        self.assertListEqual(self.irc.chanmsgs, [
            "a [20/20] has fought b [10/40] and has won! 0 days, 00:00:42 is removed from a's clock.",
            "a reaches next level in 0 days, 00:09:18.",
            "In the fierce battle, b dropped their level 40 amulet! a picks it up, tossing their old level 20 amulet to b."
            ])
        self.assertEqual(a.nextlvl, 558)
        self.assertEqual(a.items['amulet'].level, 40)
        self.assertEqual(b.items['amulet'].level, 20)


    def test_player_battle_finditem(self):
        a = self.bot._db.new_player('a', 'b', 'c')
        a.nick = 'a'
        a.items['amulet'] = bot.Item(20, '')
        b = self.bot._db.new_player('b', 'c', 'd')
        b.items['amulet'] = bot.Item(40, '')
        self.bot._overrides = {
            'pvp_player_roll': 20,
            'pvp_opp_roll': 10,
            'pvp_critical': False,
            'pvp_swap_item': False,
            'pvp_find_item': True,
            'specitem_find': False,
            'find_item_slot': 'charm',
            'find_item_level': 5
        }
        self.bot.pvp_battle(a, b, "fought", "and has won", "and has lost")
        self.assertListEqual(self.irc.chanmsgs, [
            "a [20/20] has fought b [10/40] and has won! 0 days, 00:00:42 is removed from a's clock.",
            "a reaches next level in 0 days, 00:09:18.",
            "While recovering from battle, a notices a glint in the mud. Upon investigation, they find an old lost item!"
            ])
        self.assertListEqual(self.irc.notices['a'], [
            "You found a level 5 charm! Your current charm is only level 0, so it seems Luck is with you!"
            ])

        self.assertEqual(a.nextlvl, 558)


class TestTeamBattle(unittest.TestCase):


    def setUp(self):
        conf._conf['rpbase'] = 600
        conf._conf['modsfile'] = '/tmp/modsfile.txt'
        conf._conf['color'] = False
        self.bot = bot.DawdleBot(bot.GameDB(FakeGameStorage()))
        self.irc = FakeIRCClient()
        self.bot.connected(self.irc)


    def test_setup_insufficient_players(self):
        op = [self.bot._db.new_player(pname, 'a', 'b') for pname in "abcde"]
        self.bot.team_battle(op)
        self.assertEqual(self.irc.chanmsgs, [])


    def test_win(self):
        op = [self.bot._db.new_player(pname, 'a', 'b') for pname in "abcdef"]
        op[0].items['amulet'] = bot.Item(20, "")
        op[1].items['amulet'] = bot.Item(20, "")
        op[2].items['amulet'] = bot.Item(20, "")
        op[3].items['amulet'] = bot.Item(40, "")
        op[4].items['amulet'] = bot.Item(40, "")
        op[5].items['amulet'] = bot.Item(40, "")
        op[0].nextlvl = 1200
        op[1].nextlvl = 3600
        op[2].nextlvl = 3600
        op[3].nextlvl = 3600
        op[4].nextlvl = 3600
        op[5].nextlvl = 3600
        self.bot._overrides = {
            'team_battle_members': op,
            'team_a_roll': 60,
            'team_b_roll': 30
        }
        self.bot.team_battle(op)
        self.assertEqual(self.irc.chanmsgs[0], "a, b, and c [60/60] have team battled d, e, and f [30/120] and won!  0 days, 00:04:00 is removed from their clocks.")

    def test_loss(self):
        op = [self.bot._db.new_player(pname, 'a', 'b') for pname in "abcdef"]
        op[0].items['amulet'] = bot.Item(20, "")
        op[1].items['amulet'] = bot.Item(20, "")
        op[2].items['amulet'] = bot.Item(20, "")
        op[3].items['amulet'] = bot.Item(40, "")
        op[4].items['amulet'] = bot.Item(40, "")
        op[5].items['amulet'] = bot.Item(40, "")
        op[0].nextlvl = 1200
        op[1].nextlvl = 3600
        op[2].nextlvl = 3600
        op[3].nextlvl = 3600
        op[4].nextlvl = 3600
        op[5].nextlvl = 3600
        self.bot._overrides = {
            'team_battle_members': op,
            'team_a_roll': 30,
            'team_b_roll': 60
        }
        self.bot.team_battle(op)
        self.assertEqual(self.irc.chanmsgs[0], "a, b, and c [30/60] have team battled d, e, and f [60/120] and lost!  0 days, 00:04:00 is added to their clocks.")


class TestEvilness(unittest.TestCase):


    def setUp(self):
        conf._conf['rpbase'] = 600
        conf._conf['modsfile'] = '/tmp/modsfile.txt'
        conf._conf['color'] = False
        self.bot = bot.DawdleBot(bot.GameDB(FakeGameStorage()))
        self.irc = FakeIRCClient()
        self.bot.connected(self.irc)


    def test_theft(self):
        op = [self.bot._db.new_player('a', 'b', 'c'), self.bot._db.new_player('b', 'c', 'd')]
        op[0].alignment = 'e'
        op[1].alignment = 'g'
        op[1].items['amulet'] = bot.Item(20, "")
        self.bot._overrides = {
            'evilness_theft': True,
            'evilness_slot': 'amulet'
        }
        self.bot.evilness(op)
        self.assertEqual(self.irc.chanmsgs[0], "a stole b's level 20 amulet while they were sleeping!  a leaves their old level 0 amulet behind, which b then takes.")


    def test_penalty(self):
        op = [self.bot._db.new_player('a', 'b', 'c')]
        op[0].alignment = 'e'
        self.bot._overrides = {
            'evilness_theft': False,
            'evilness_penalty_pct': 5
        }
        self.bot.evilness(op)
        self.assertEqual(self.irc.chanmsgs[0], "a is forsaken by their evil god. 0 days, 00:00:30 is added to their clock.")


class TestGoodness(unittest.TestCase):


    def setUp(self):
        conf._conf['rpbase'] = 600
        conf._conf['modsfile'] = '/tmp/modsfile.txt'
        conf._conf['color'] = False
        self.bot = bot.DawdleBot(bot.GameDB(FakeGameStorage()))
        self.irc = FakeIRCClient()
        self.bot.connected(self.irc)


    def test_goodness(self):
        op = [self.bot._db.new_player('a', 'b', 'c'), self.bot._db.new_player('b', 'c', 'd')]
        op[0].alignment = 'g'
        op[1].alignment = 'g'
        self.bot._overrides = {
            'goodness_players': op,
            'goodness_gain_pct': 10,
        }
        self.bot.goodness(op)
        self.assertListEqual(self.irc.chanmsgs, [
            "a and b have not let the iniquities of evil people poison them. Together have they prayed to their god, and light now shines down upon them. 10% of their time is removed from their clocks.",
            "a reaches next level in 0 days, 00:09:00.",
            "b reaches next level in 0 days, 00:09:00."
        ])
        self.assertEqual(op[0].nextlvl, 540)
        self.assertEqual(op[1].nextlvl, 540)


class TestHandOfGod(unittest.TestCase):


    def setUp(self):
        conf._conf['rpbase'] = 600
        conf._conf['color'] = False
        self.bot = bot.DawdleBot(bot.GameDB(FakeGameStorage()))
        self.irc = FakeIRCClient()
        self.bot.connected(self.irc)


    def test_forward(self):
        op = [self.bot._db.new_player('a', 'b', 'c')]
        self.bot._overrides = {
            'hog_effect': False,
            'hog_amount': 10
        }
        self.bot.hand_of_god(op)
        self.assertEqual(self.irc.chanmsgs[0], "Verily I say unto thee, the Heavens have burst forth, and the blessed hand of God carried a 0 days, 00:01:30 toward level 1.")
        self.assertEqual(self.irc.chanmsgs[1], "a reaches next level in 0 days, 00:08:30.")


    def test_back(self):
        op = [self.bot._db.new_player('a', 'b', 'c')]
        self.bot._overrides = {
            'hog_effect': True,
            'hog_amount': 10
        }
        self.bot.hand_of_god(op)
        self.assertEqual(self.irc.chanmsgs[0], "Thereupon He stretched out His little finger among them and consumed a with fire, slowing the heathen 0 days, 00:01:30 from level 1.")
        self.assertEqual(self.irc.chanmsgs[1], "a reaches next level in 0 days, 00:11:30.")


class TestQuest(unittest.TestCase):


    def setUp(self):
        conf._conf['rpbase'] = 600
        conf._conf['datadir'] = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
        conf._conf['eventsfile'] = "events.txt"
        conf._conf['writequestfile'] = True
        conf._conf['questfilename'] = "/tmp/testquestfile.txt"
        conf._conf['quest_interval_min'] = 6*3600
        conf._conf['quest_min_level'] = 24
        conf._conf['penquest'] = 15
        conf._conf['penlogout'] = 20
        conf._conf['color'] = False
        self.bot = bot.DawdleBot(bot.GameDB(FakeGameStorage()))
        self.irc = FakeIRCClient()
        self.bot.connected(self.irc)
        self.bot._state = "ready"
        self.bot.refresh_events()


    def test_questing_mode_1(self):
        users = [irc.IRCClient.User(uname, f"{uname}!{uname}@irc.example.com", [], 0) for uname in "abcd"]
        op = [self.bot._db.new_player(pname, 'a', 'b') for pname in "abcd"]
        now = time.time()
        for u,p in zip(users,op):
            p.online = True
            p.level = 25
            p.lastlogin = datetime.datetime.fromtimestamp(now - 36001)
            p.nick = u.nick
            p.userhost = u.userhost
        self.bot._overrides = {
            "quest_members": op,
            "quest_selection": "1 locate the centuries-lost tomes of the grim prophet Haplashak Mhadhu",
            "quest_time": 12
        }
        self.bot.quest_start(now)
        self.bot.private_message(users[0], 'quest')
        # time passes
        self.bot._quest.qtime = now-1
        self.bot.quest_check(now)

        self.assertListEqual(self.irc.chanmsgs, [
            "a, b, c, and d have been chosen by the gods to locate the centuries-lost tomes of the grim prophet Haplashak Mhadhu.  Quest to end in 0 days, 12:00:00.",
            "a, b, c, and d have blessed the realm by completing their quest! 25% of their burden is eliminated."
        ])
        self.assertListEqual(self.irc.notices['a'], [
            "a, b, c, and d are on a quest to locate the centuries-lost tomes of the grim prophet Haplashak Mhadhu. Quest to complete in 0 days, 11:59:59."
        ])
        self.assertEqual(op[0].nextlvl, 450)
        self.assertEqual(op[1].nextlvl, 450)
        self.assertEqual(op[2].nextlvl, 450)
        self.assertEqual(op[3].nextlvl, 450)


    def test_questing_mode_2(self):
        conf._conf['mapurl'] = "https://example.com/"
        users = [irc.IRCClient.User(uname, f"{uname}!{uname}@irc.example.com", [], 0) for uname in "abcd"]
        op = [self.bot._db.new_player(pname, 'a', 'b') for pname in "abcd"]
        now = time.time()
        for u,p in zip(users,op):
            p.online = True
            p.level = 25
            p.lastlogin = datetime.datetime.fromtimestamp(now - 36001)
            p.nick = u.nick
            p.userhost = u.userhost
        self.bot._overrides = {
            "quest_members": op,
            "quest_selection": "2 400 475 480 380 explore and chart the dark lands of T'rnalvph",
        }
        self.bot._db._online = op
        self.bot.quest_start(now)
        self.bot.private_message(users[0], 'quest')
        for p in op:
            p.posx, p.posy = 400, 475
        self.bot.quest_check(1)
        for p in op:
            p.posx, p.posy = 480, 380
        self.bot.quest_check(2)

        self.assertEqual(self.irc.chanmsgs, [
            "a, b, c, and d have been chosen by the gods to explore and chart the dark lands of T'rnalvph.  Participants must first reach (400,475), then (480,380). See https://example.com/ to monitor their journey's progress.",
            "a, b, c, and d have reached a landmark on their journey! 1 landmark remains.",
            "a, b, c, and d have completed their journey! 25% of their burden is eliminated."
        ])
        self.assertListEqual(self.irc.notices['a'], [
            "a, b, c, and d are on a quest to explore and chart the dark lands of T'rnalvph. Participants must first reach (400, 475), then (480, 380). See https://example.com/ to monitor their journey's progress."
        ])
        self.assertEqual(op[0].nextlvl, 450)
        self.assertEqual(op[1].nextlvl, 450)
        self.assertEqual(op[2].nextlvl, 450)
        self.assertEqual(op[3].nextlvl, 450)


    def test_questing_failure(self):
        conf._conf['rppenstep'] = 1.14
        op = [self.bot._db.new_player(pname, 'a', 'b') for pname in "abcd"]
        now = time.time()
        for p in op:
            p.online = True
            p.nick = p.name
            p.level = 25
            p.lastlogin = datetime.datetime.fromtimestamp(now - 36001)
        self.bot._overrides = {
            "quest_members": op,
            "quest_selection": "1 locate the centuries-lost tomes of the grim prophet Haplashak Mhadhu",
            "quest_time": 12
        }
        self.bot.quest_start(now)
        self.bot.penalize(op[0], 'logout')

        self.assertListEqual(self.irc.chanmsgs, [
            "a, b, c, and d have been chosen by the gods to locate the centuries-lost tomes of the grim prophet Haplashak Mhadhu.  Quest to end in 0 days, 12:00:00.",
            "a's insolence has brought the wrath of the gods down upon them.  Your great wickedness burdens you like lead, drawing you downwards with great force towards hell. Thereby have you plunged 15 steps closer to that gaping maw."
        ])
        self.assertListEqual(self.irc.notices['a'],
                             ["Penalty of 0 days, 00:08:40 added to your timer for LOGOUT command."])
        self.assertEqual(op[0].nextlvl, 1516)
        self.assertEqual(op[1].nextlvl, 996)
        self.assertEqual(op[2].nextlvl, 996)
        self.assertEqual(op[3].nextlvl, 996)

class TestAdminCommands(unittest.TestCase):

    def setUp(self):
        conf._conf['rpbase'] = 600
        conf._conf['color'] = False
        self.bot = bot.DawdleBot(bot.GameDB(FakeGameStorage()))
        self.irc = FakeIRCClient()
        self.bot.connected(self.irc)

    def test_delold(self):
        op = [self.bot._db.new_player(pname, 'a', 'b') for pname in "abcd"]
        level = 25
        expired = time.time() - 9 * 86400
        for p in op[:2]:
            p.lastlogin = datetime.datetime.fromtimestamp(expired)
        op[3].online = True
        op[3].isadmin = True
        self.bot.cmd_delold(op[3], op[3].nick, "7")
        self.assertListEqual(self.irc.chanmsgs, [
            "2 accounts not accessed in the last 7 days removed by d."
        ])
        self.assertNotIn(op[0].name, self.bot._db)
        self.assertNotIn(op[1].name, self.bot._db)
        self.assertIn(op[2].name, self.bot._db)
        self.assertIn(op[3].name, self.bot._db)


class TestPlayerCommands(unittest.TestCase):

    def setUp(self):
        conf._conf['rpbase'] = 600
        conf._conf['color'] = False
        conf._conf['allowuserinfo'] = True
        conf._conf['helpurl'] = "http://example.com/"
        conf._conf['botchan'] = "#dawdlerpg"
        conf._conf["voiceonlogin"] = False
        self.bot = bot.DawdleBot(bot.GameDB(FakeGameStorage()))
        self.irc = FakeIRCClient()
        self.bot.connected(self.irc)

    def test_unrestricted_commands_without_player(self):
        self.irc._server = 'irc.example.com'
        for cmd in bot.DawdleBot.ALLOWALL:
            # We don't care what it does, as long as it doesn't crash.
            getattr(self.bot, f"cmd_{cmd}")(None, "foo", "")

    def test_cmd_info(self):
        self.irc._server = 'irc.example.com'
        self.bot.cmd_info(None, "foo", "")
        self.assertIn("DawdleRPG v", self.irc.notices["foo"][0])
        player = self.bot._db.new_player("bar", 'a', 'b')
        self.bot.cmd_info(player, "bar", "")
        self.assertIn("DawdleRPG v", self.irc.notices["bar"][0])

    def test_cmd_login(self):

        self.bot.cmd_login(None, "foo", "bar baz")
        self.irc._users['foo'] = irc.IRCClient.User("foo", "foo@example.com", [], 1)
        self.assertEqual("Sorry, you aren't on #dawdlerpg.", self.irc.notices["foo"][0])
        self.irc.resetmsgs()
        player = self.bot._db.new_player("bar", 'a', 'b')
        player.set_password("baz")
        self.bot.cmd_login(None, "foo", "bar baz")
        self.assertIn("foo", self.irc.chanmsgs[0])


class TestGameTick(unittest.TestCase):

    def setUp(self):
        conf._conf['rpbase'] = 600
        conf._conf['rpstep'] = 1.14
        conf._conf['detectsplits'] = True
        conf._conf['splitwait'] = 300
        conf._conf['datadir'] = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
        conf._conf['eventsfile'] = "events.txt"
        conf._conf['writequestfile'] = True
        conf._conf['questfilename'] = "/tmp/testquestfile.txt"
        conf._conf['quest_min_level'] = 24
        conf._conf['self_clock'] = 1
        conf._conf['mapx'] = 500
        conf._conf['mapy'] = 500
        conf._conf['color'] = False
        self.bot = bot.DawdleBot(bot.GameDB(FakeGameStorage()))
        self.irc = FakeIRCClient()
        self.bot.connected(self.irc)

    def test_gametick(self):
        op = [self.bot._db.new_player(pname, 'a', 'b') for pname in "abcd"]
        level = 25
        for p in op:
            p.online = True
            p.level = level
            level += 3
        self.bot.gametick(0, 0)

if __name__ == "__main__":
    unittest.main()
