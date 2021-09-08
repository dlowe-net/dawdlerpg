#!/usr/bin/python3

import os.path
import tempfile
import time
import unittest

import dawdle
import dawdleirc
import dawdlebot
import dawdleconf

class TestGameDBSqlite3(unittest.TestCase):
    def test_db(self):
        dawdleconf.conf['rpbase'] = 600
        with tempfile.TemporaryDirectory() as tmpdir:
            db = dawdlebot.GameDB(dawdlebot.Sqlite3GameStorage(os.path.join(tmpdir, 'dawdle_test.db')))
            self.assertFalse(db.exists())
            db.create()
            p = db.new_player('foo', 'bar', 'baz')
            p.online = True
            db.write_players()
            self.assertTrue(db.exists())
            db.load_players()
            self.assertEqual(db['foo'].name, 'foo')
            self.assertEqual(db['foo'].online, True)
            db.close()

    def test_passwords(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = dawdlebot.GameDB(dawdlebot.Sqlite3GameStorage(os.path.join(tmpdir, 'dawdle_test.db')))
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
            db = dawdlebot.GameDB(dawdlebot.IdleRPGGameStorage(os.path.join(tmpdir, 'dawdle_test.db')))
            db.create()
            op = db.new_player('foo', 'bar', 'baz')
            op.amulet = 55
            op.helm = 42
            op.helmname = "Jeff's Cluehammer of Doom"
            db.write_players()
            db.load_players()
            p = db['foo']
            self.maxDiff = None
            self.assertEqual(vars(op), vars(p))
            db.close()


class TestIRCMessage(unittest.TestCase):
    def test_basic(self):
        line = "@time=2021-07-31T13:55:00;bar=baz :nick!example@example.com PART #example :later!"
        msg = dawdleirc.IRCClient.parse_message(None, line)
        self.assertEqual(msg.tags, {"time": "2021-07-31T13:55:00", "bar": "baz"})
        self.assertEqual(msg.src, "nick")
        self.assertEqual(msg.user, "example")
        self.assertEqual(msg.host, "example.com")
        self.assertEqual(msg.cmd, "PART")
        self.assertEqual(msg.args, ["#example", "later!"])
        self.assertEqual(msg.trailing, "later!")
        self.assertEqual(msg.line, line)
        self.assertEqual(msg.time, 1627754100)

    def test_one_trailing_arg(self):
        line = ":foo!bar@example.com NICK :baz"
        msg = dawdleirc.IRCClient.parse_message(None, line)
        self.assertEqual(msg.tags, {})
        self.assertEqual(msg.src, "foo")
        self.assertEqual(msg.user, "bar")
        self.assertEqual(msg.host, "example.com")
        self.assertEqual(msg.cmd, "NICK")
        self.assertEqual(msg.args, ["baz"])
        self.assertEqual(msg.trailing, "baz")
        self.assertEqual(msg.line, line)

    def test_complextags(self):
        line = "@keyone=one\\sbig\\:value;keytwo=t\\wo\\rbig\\n\\\\values :nick!example@example.com PART #example :later!"
        msg = dawdleirc.IRCClient.parse_message(None, line)
        self.assertEqual(msg.tags, {
            "keyone": "one big;value",
            "keytwo": "two\rbig\n\\values",
            })


    def test_notags(self):
        line = ":nick!example@example.com PART #example :later!"
        msg = dawdleirc.IRCClient.parse_message(None,line)
        self.assertEqual(msg.tags, {})
        self.assertEqual(msg.src, "nick")

    def test_badtags(self):
        line = "@asdf :nick!example@example.com PART #example :later!"
        msg = dawdleirc.IRCClient.parse_message(None,line)
        self.assertEqual(msg.tags, {'asdf': None})
        self.assertEqual(msg.src, "nick")

        line = "@ :nick!example@example.com PART #example :later!"
        msg = dawdleirc.IRCClient.parse_message(None,line)
        self.assertEqual(msg.tags, {})
        self.assertEqual(msg.src, "nick")

    def test_bad_encoding(self):
        line = "\255\035"
        msg = dawdleirc.IRCClient.parse_message(None, line)


class TestIRCClient(unittest.TestCase):

    def test_handle_cap(self):
        dawdleconf.conf['botnick'] = 'foo'
        irc = dawdleirc.IRCClient(None)
        irc.handle_cap(dawdleirc.IRCClient.Message(tags={}, src='tungsten.libera.chat', user=None, host=None, cmd='CAP', args=['*', 'ACK', 'multi-prefix'], trailing='multi-prefix', line=':tungsten.libera.chat CAP * ACK :multi-prefix', time=1629501206))
        self.assertIn("multi-prefix", irc._caps)


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


class FakeGameStorage(dawdlebot.GameStorage):

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


class TestIRCClient(unittest.TestCase):

    def test_nick_change(self):
        dawdleconf.conf['botnick'] = 'dawdlerpg'
        bot = dawdlebot.DawdleBot(dawdlebot.GameDB(FakeGameStorage()))
        irc = dawdleirc.IRCClient(bot)
        irc.handle_join(dawdleirc.IRCClient.Message(tags={}, src='foo', user=None, host=None, cmd='NICK', args=['#dawdlerpg'], trailing='', line='', time=0))
        irc.handle_nick(dawdleirc.IRCClient.Message(tags={}, src='foo', user=None, host=None, cmd='NICK', args=['bar'], trailing='bar', line='', time=0))
        self.assertNotIn('foo', irc._users)
        self.assertIn('bar', irc._users)


class TestDawdleBot(unittest.TestCase):

    def test_nick_change(self):
        dawdleconf.conf['botnick'] = 'dawdlerpg'
        dawdleconf.conf['botchan'] = '#dawdlerpg'
        dawdleconf.conf['message_wrap_len'] = 400
        dawdleconf.conf['throttle'] = False
        dawdleconf.conf['pennick'] = 10
        dawdleconf.conf['penquit'] = 20
        dawdleconf.conf['rppenstep'] = 1.14

        bot = dawdlebot.DawdleBot(dawdlebot.GameDB(FakeGameStorage()))
        irc = FakeIRCClient()
        bot.connected(irc)
        irc._users['foo'] = dawdleirc.IRCClient.User("foo", "foo!foo@example.com", [], 1)
        a = bot._db.new_player('a', 'b', 'c')
        a.online = True
        a.nick = 'foo'
        a.userhost = 'foo!foo@example.com'
        self.assertEqual('foo', a.nick)
        bot.nick_changed(irc._users['foo'], 'bar')
        self.assertEqual('bar', a.nick)
        bot.nick_quit(irc._users['foo'])

class TestGameDB(unittest.TestCase):

    def test_top_players(self):
        db = dawdlebot.GameDB(FakeGameStorage())
        a = db.new_player('a', 'waffle', 'c')
        a.level, a.nextlvl = 30, 100
        b = db.new_player('b', 'doughnut', 'c')
        b.level, b.nextlvl = 20, 1000
        c = db.new_player('c', 'bagel', 'c')
        c.level, c.nextlvl = 10, 10
        self.assertEqual(['a', 'b', 'c'], [p.name for p in db.top_players()])


class TestPvPBattle(unittest.TestCase):


    def setUp(self):
        dawdleconf.conf['rpbase'] = 600
        dawdleconf.conf['modsfile'] = '/tmp/modsfile.txt'
        dawdleconf.conf['color'] = False
        self.bot = dawdlebot.DawdleBot(dawdlebot.GameDB(FakeGameStorage()))
        self.irc = FakeIRCClient()
        self.bot.connected(self.irc)


    def test_player_battle_win(self):
        a = self.bot._db.new_player('a', 'b', 'c')
        a.amulet = 20
        b = self.bot._db.new_player('b', 'c', 'd')
        b.amulet = 40
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
        dawdleconf.conf['botnick'] = 'dawdlerpg'
        a = self.bot._db.new_player('a', 'b', 'c')
        a.amulet = 20
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
        a.amulet = 20
        b = self.bot._db.new_player('b', 'c', 'd')
        b.amulet = 40
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
        a.amulet = 20
        b = self.bot._db.new_player('b', 'c', 'd')
        b.amulet = 40
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
        a.amulet = 20
        b = self.bot._db.new_player('b', 'c', 'd')
        b.amulet = 40
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
        self.assertEqual(a.amulet, 40)
        self.assertEqual(b.amulet, 20)


    def test_player_battle_finditem(self):
        a = self.bot._db.new_player('a', 'b', 'c')
        a.nick = 'a'
        a.amulet = 20
        b = self.bot._db.new_player('b', 'c', 'd')
        b.amulet = 40
        self.bot._overrides = {
            'pvp_player_roll': 20,
            'pvp_opp_roll': 10,
            'pvp_critical': False,
            'pvp_swap_item': False,
            'pvp_find_item': True,
            'specitem_find': False,
            'find_item_itemtype': 'charm',
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
        dawdleconf.conf['rpbase'] = 600
        dawdleconf.conf['modsfile'] = '/tmp/modsfile.txt'
        dawdleconf.conf['color'] = False
        self.bot = dawdlebot.DawdleBot(dawdlebot.GameDB(FakeGameStorage()))
        self.irc = FakeIRCClient()
        self.bot.connected(self.irc)


    def test_setup_insufficient_players(self):
        op = [self.bot._db.new_player(pname, 'a', 'b') for pname in "abcde"]
        self.bot.team_battle(op)
        self.assertEqual(self.irc.chanmsgs, [])


    def test_win(self):
        op = [self.bot._db.new_player(pname, 'a', 'b') for pname in "abcdef"]
        op[0].amulet, op[0].nextlvl = 20, 1200
        op[1].amulet, op[1].nextlvl = 20, 3600
        op[2].amulet, op[2].nextlvl = 20, 3600
        op[3].amulet, op[3].nextlvl = 40, 3600
        op[4].amulet, op[4].nextlvl = 40, 3600
        op[5].amulet, op[5].nextlvl = 40, 3600
        self.bot._overrides = {
            'team_battle_members': op,
            'team_a_roll': 60,
            'team_b_roll': 30
        }
        self.bot.team_battle(op)
        self.assertEqual(self.irc.chanmsgs[0], "a, b, and c [60/60] have team battled d, e, and f [30/120] and won!  0 days, 00:04:00 is removed from their clocks.")

    def test_loss(self):
        op = [self.bot._db.new_player(pname, 'a', 'b') for pname in "abcdef"]
        op[0].amulet, op[0].nextlvl = 20, 1200
        op[1].amulet, op[1].nextlvl = 20, 3600
        op[2].amulet, op[2].nextlvl = 20, 3600
        op[3].amulet, op[3].nextlvl = 40, 3600
        op[4].amulet, op[4].nextlvl = 40, 3600
        op[5].amulet, op[5].nextlvl = 40, 3600
        self.bot._overrides = {
            'team_battle_members': op,
            'team_a_roll': 30,
            'team_b_roll': 60
        }
        self.bot.team_battle(op)
        self.assertEqual(self.irc.chanmsgs[0], "a, b, and c [30/60] have team battled d, e, and f [60/120] and lost!  0 days, 00:04:00 is added to their clocks.")


class TestEvilness(unittest.TestCase):


    def setUp(self):
        dawdleconf.conf['rpbase'] = 600
        dawdleconf.conf['modsfile'] = '/tmp/modsfile.txt'
        dawdleconf.conf['color'] = False
        self.bot = dawdlebot.DawdleBot(dawdlebot.GameDB(FakeGameStorage()))
        self.irc = FakeIRCClient()
        self.bot.connected(self.irc)


    def test_theft(self):
        op = [self.bot._db.new_player('a', 'b', 'c'), self.bot._db.new_player('b', 'c', 'd')]
        op[0].alignment = 'e'
        op[1].alignment = 'g'
        op[1].amulet = 20
        self.bot._overrides = {
            'evilness_theft': True,
            'evilness_item': 'amulet'
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
        dawdleconf.conf['rpbase'] = 600
        dawdleconf.conf['modsfile'] = '/tmp/modsfile.txt'
        dawdleconf.conf['color'] = False
        self.bot = dawdlebot.DawdleBot(dawdlebot.GameDB(FakeGameStorage()))
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
        dawdleconf.conf['rpbase'] = 600
        dawdleconf.conf['color'] = False
        self.bot = dawdlebot.DawdleBot(dawdlebot.GameDB(FakeGameStorage()))
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
        dawdleconf.conf['rpbase'] = 600
        dawdleconf.conf['datadir'] = os.path.join(os.path.dirname(__file__), "data")
        dawdleconf.conf['eventsfile'] = "events.txt"
        dawdleconf.conf['writequestfile'] = True
        dawdleconf.conf['questfilename'] = "/tmp/testquestfile.txt"
        dawdleconf.conf['quest_interval_min'] = 6*3600
        dawdleconf.conf['quest_min_level'] = 24
        dawdleconf.conf['penquest'] = 15
        dawdleconf.conf['penlogout'] = 20
        dawdleconf.conf['color'] = False
        self.bot = dawdlebot.DawdleBot(dawdlebot.GameDB(FakeGameStorage()))
        self.irc = FakeIRCClient()
        self.bot.connected(self.irc)
        self.bot._state = "ready"
        self.bot.refresh_events()


    def test_questing_mode_1(self):
        users = [dawdleirc.IRCClient.User(uname, f"{uname}!{uname}@irc.example.com", [], 0) for uname in "abcd"]
        op = [self.bot._db.new_player(pname, 'a', 'b') for pname in "abcd"]
        now = time.time()
        for u,p in zip(users,op):
            p.online = True
            p.level = 25
            p.lastlogin = now - 36001
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
        dawdleconf.conf['mapurl'] = "https://example.com/"
        users = [dawdleirc.IRCClient.User(uname, f"{uname}!{uname}@irc.example.com", [], 0) for uname in "abcd"]
        op = [self.bot._db.new_player(pname, 'a', 'b') for pname in "abcd"]
        now = time.time()
        for u,p in zip(users,op):
            p.online = True
            p.level = 25
            p.lastlogin = now - 36001
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
        dawdleconf.conf['rppenstep'] = 1.14
        op = [self.bot._db.new_player(pname, 'a', 'b') for pname in "abcd"]
        now = time.time()
        for p in op:
            p.online = True
            p.nick = p.name
            p.level = 25
            p.lastlogin = now - 36001
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
        dawdleconf.conf['rpbase'] = 600
        dawdleconf.conf['color'] = False
        self.bot = dawdlebot.DawdleBot(dawdlebot.GameDB(FakeGameStorage()))
        self.irc = FakeIRCClient()
        self.bot.connected(self.irc)

    def test_delold(self):
        op = [self.bot._db.new_player(pname, 'a', 'b') for pname in "abcd"]
        level = 25
        expired = time.time() - 9 * 86400
        for p in op[:2]:
            p.lastlogin = expired
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
        dawdleconf.conf['rpbase'] = 600
        dawdleconf.conf['color'] = False
        dawdleconf.conf['allowuserinfo'] = True
        dawdleconf.conf['helpurl'] = "http://example.com/"
        dawdleconf.conf['botchan'] = "#dawdlerpg"
        dawdleconf.conf["voiceonlogin"] = False
        self.bot = dawdlebot.DawdleBot(dawdlebot.GameDB(FakeGameStorage()))
        self.irc = FakeIRCClient()
        self.bot.connected(self.irc)

    def test_unrestricted_commands_without_player(self):
        self.irc._server = 'irc.example.com'
        for cmd in dawdlebot.DawdleBot.ALLOWALL:
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
        self.irc._users['foo'] = dawdleirc.IRCClient.User("foo", "foo@example.com", [], 1)
        self.assertEqual("Sorry, you aren't on #dawdlerpg.", self.irc.notices["foo"][0])
        self.irc.resetmsgs()
        player = self.bot._db.new_player("bar", 'a', 'b')
        player.set_password("baz")
        self.bot.cmd_login(None, "foo", "bar baz")
        self.assertIn("foo", self.irc.chanmsgs[0])


class TestGameTick(unittest.TestCase):

    def setUp(self):
        dawdleconf.conf['rpbase'] = 600
        dawdleconf.conf['rpstep'] = 1.14
        dawdleconf.conf['detectsplits'] = True
        dawdleconf.conf['splitwait'] = 300
        dawdleconf.conf['datadir'] = os.path.join(os.path.dirname(__file__), "data")
        dawdleconf.conf['eventsfile'] = "events.txt"
        dawdleconf.conf['writequestfile'] = True
        dawdleconf.conf['questfilename'] = "/tmp/testquestfile.txt"
        dawdleconf.conf['quest_min_level'] = 24
        dawdleconf.conf['self_clock'] = 1
        dawdleconf.conf['mapx'] = 500
        dawdleconf.conf['mapy'] = 500
        dawdleconf.conf['color'] = False
        self.bot = dawdlebot.DawdleBot(dawdlebot.GameDB(FakeGameStorage()))
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