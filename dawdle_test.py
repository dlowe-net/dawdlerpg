#!/usr/bin/python3

import dawdle
import os.path
import random
import sys
import tempfile
import time
import unittest

class TestPlayerDB(unittest.TestCase):
    def test_db(self):
        dawdle.conf['rpbase'] = 600
        with tempfile.TemporaryDirectory() as tmpdir:
            db = dawdle.PlayerDB(os.path.join(tmpdir, 'dawdle_test.db'))
            self.assertFalse(db.exists())
            db.create()
            p = db.new_player('foo', 'bar', 'baz')
            p.online = True
            db.write()
            self.assertTrue(db.exists())
            db.load()
            self.assertEqual(db['foo'].name, 'foo')
            self.assertEqual(db['foo'].online, True)
            db.close()

    def test_passwords(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = dawdle.PlayerDB(os.path.join(tmpdir, 'dawdle_test.db'))
            self.assertFalse(db.exists())
            db.create()
            p = db.new_player('foo', 'bar', 'baz')
            self.assertTrue(db.check_login('foo', 'baz'))
            self.assertFalse(db.check_login('foo', 'azb'))
            p.set_password('azb')
            self.assertTrue(db.check_login('foo', 'azb'))
            db.close()


class TestIRCMessage(unittest.TestCase):
    def test_basic(self):
        line = "@time=2021-07-31T13:55:00,bar=baz :nick!example@example.com PART #example :later!"
        msg = dawdle.IRCClient.parse_message(None, line)
        self.assertEqual(msg.tags, {"time": "2021-07-31T13:55:00", "bar": "baz"})
        self.assertEqual(msg.src, "nick")
        self.assertEqual(msg.user, "example")
        self.assertEqual(msg.host, "example.com")
        self.assertEqual(msg.cmd, "PART")
        self.assertEqual(msg.args, ["#example", "later!"])
        self.assertEqual(msg.trailing, "later!")
        self.assertEqual(msg.line, line)
        self.assertEqual(msg.time, 1627754100)

    def test_notags(self):
        line = ":nick!example@example.com PART #example :later!"
        msg = dawdle.IRCClient.parse_message(None,line)
        self.assertEqual(msg.tags, {})
        self.assertEqual(msg.src, "nick")

    def test_badtags(self):
        line = "@asdf :nick!example@example.com PART #example :later!"
        msg = dawdle.IRCClient.parse_message(None,line)
        self.assertEqual(msg.tags, {'asdf': None})
        self.assertEqual(msg.src, "nick")

        line = "@ :nick!example@example.com PART #example :later!"
        msg = dawdle.IRCClient.parse_message(None,line)
        self.assertEqual(msg.tags, {})
        self.assertEqual(msg.src, "nick")

    def test_bad_encoding(self):
        line = "\255\035"
        msg = dawdle.IRCClient.parse_message(None, line)


class FakeIRCClient(object):
    def __init__(self):
        self.chanmsgs = []
        self.notices = {}

    def chanmsg(self, text):
        self.chanmsgs.append(text)

    def notice(self, nick, text):
        self.notices.setdefault(nick, []).append(text)

class FakePlayerDB(object):
    def __init__(self):
        pass


    def write(self):
        pass


    def online(self):
        return self._online


    def max_player_power(self):
        return 42

class TestPvPBattle(unittest.TestCase):


    def setUp(self):
        dawdle.conf['rpbase'] = 600
        self.bot = dawdle.DawdleBot(FakePlayerDB())
        self.irc = FakeIRCClient()
        self.bot.connected(self.irc)


    def test_player_battle_win(self):
        a = dawdle.Player.new_player('a', 'b', 'c')
        a.amulet = 20
        b = dawdle.Player.new_player('b', 'c', 'd')
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
        dawdle.conf['botnick'] = 'dawdlerpg'
        a = dawdle.Player.new_player('a', 'b', 'c')
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
            "a [20/20] has fought dawdlerpg [10/43] and has won! 0 days, 00:02:00 is removed from a's clock.",
            "a reaches next level in 0 days, 00:08:00."
            ])
        self.assertEqual(a.nextlvl, 480)


    def test_player_battle_lose(self):
        a = dawdle.Player.new_player('a', 'b', 'c')
        a.amulet = 20
        b = dawdle.Player.new_player('b', 'c', 'd')
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
        a = dawdle.Player.new_player('a', 'b', 'c')
        a.amulet = 20
        b = dawdle.Player.new_player('b', 'c', 'd')
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
        a = dawdle.Player.new_player('a', 'b', 'c')
        a.level = 20
        a.amulet = 20
        b = dawdle.Player.new_player('b', 'c', 'd')
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
        a = dawdle.Player.new_player('a', 'b', 'c')
        a.nick = 'a'
        a.amulet = 20
        b = dawdle.Player.new_player('b', 'c', 'd')
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
        dawdle.conf['rpbase'] = 600
        self.bot = dawdle.DawdleBot(None)
        self.irc = FakeIRCClient()
        self.bot.connected(self.irc)


    def test_setup_insufficient_players(self):
        op = [dawdle.Player.new_player(pname, 'a', 'b') for pname in "abcde"]
        self.bot.team_battle(op)
        self.assertEqual(self.irc.chanmsgs, [])


    def test_win(self):
        op = [dawdle.Player.new_player(pname, 'a', 'b') for pname in "abcdef"]
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
        op = [dawdle.Player.new_player(pname, 'a', 'b') for pname in "abcdef"]
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
        dawdle.conf['rpbase'] = 600
        self.bot = dawdle.DawdleBot(FakePlayerDB())
        self.irc = FakeIRCClient()
        self.bot.connected(self.irc)


    def test_theft(self):
        op = [dawdle.Player.new_player('a', 'b', 'c'), dawdle.Player.new_player('b', 'c', 'd')]
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
        op = [dawdle.Player.new_player('a', 'b', 'c')]
        op[0].alignment = 'e'
        self.bot._overrides = {
            'evilness_theft': False,
            'evilness_penalty_pct': 5
        }
        self.bot.evilness(op)
        self.assertEqual(self.irc.chanmsgs[0], "a is forsaken by their evil god. 0 days, 00:00:30 is added to their clock.")


class TestGoodness(unittest.TestCase):


    def setUp(self):
        dawdle.conf['rpbase'] = 600
        self.bot = dawdle.DawdleBot(FakePlayerDB())
        self.irc = FakeIRCClient()
        self.bot.connected(self.irc)


    def test_goodness(self):
        op = [dawdle.Player.new_player('a', 'b', 'c'), dawdle.Player.new_player('b', 'c', 'd')]
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
        dawdle.conf['rpbase'] = 600
        self.bot = dawdle.DawdleBot(FakePlayerDB())
        self.irc = FakeIRCClient()
        self.bot.connected(self.irc)


    def test_forward(self):
        op = [dawdle.Player.new_player('a', 'b', 'c')]
        self.bot._overrides = {
            'hog_effect': True,
            'hog_amount': 10
        }
        self.bot.hand_of_god(op)
        self.assertEqual(self.irc.chanmsgs[0], "Verily I say unto thee, the Heavens have burst forth, and the blessed hand of God carried a 0 days, 00:01:30 toward level 1.")
        self.assertEqual(self.irc.chanmsgs[1], "a reaches next level in 0 days, 00:08:30.")


    def test_back(self):
        op = [dawdle.Player.new_player('a', 'b', 'c')]
        self.bot._overrides = {
            'hog_effect': False,
            'hog_amount': 10
        }
        self.bot.hand_of_god(op)
        self.assertEqual(self.irc.chanmsgs[0], "Thereupon He stretched out His little finger among them and consumed a with fire, slowing the heathen 0 days, 00:01:30 from level 1.")
        self.assertEqual(self.irc.chanmsgs[1], "a reaches next level in 0 days, 00:11:30.")


class TestQuest(unittest.TestCase):


    def setUp(self):
        dawdle.conf['rpbase'] = 600
        dawdle.conf['eventsfile'] = "events.txt"
        self.bot = dawdle.DawdleBot(FakePlayerDB())
        self.irc = FakeIRCClient()
        self.bot.connected(self.irc)


    def test_questing_mode_1(self):
        op = [dawdle.Player.new_player(pname, 'a', 'b') for pname in "abcd"]
        now = time.time()
        for p in op:
            p.level = 25
            p.lastlogin = now - 36001
        self.bot._overrides = {
            "quest_members": op,
            "quest_selection": "Q1 locate the centuries-lost tomes of the grim prophet Haplashak Mhadhu",
            "quest_time": 12
        }
        self.bot._players._online = op
        self.bot.quest_start()
        # time passes
        self.bot._quest.qtime = time.time() - 1
        self.bot.quest_check()

        self.assertListEqual(self.irc.chanmsgs, [
            "a, b, c, and d have been chosen by the gods to locate the centuries-lost tomes of the grim prophet Haplashak Mhadhu.  Quest to end in 0 days, 12:00:00.",
            "a, b, c, and d have blessed the realm by completing their quest! 25% of their burden is eliminated."
        ])
        self.assertEqual(op[0].nextlvl, 450)
        self.assertEqual(op[1].nextlvl, 450)
        self.assertEqual(op[2].nextlvl, 450)
        self.assertEqual(op[3].nextlvl, 450)


    def test_questing_mode_2(self):
        dawdle.conf['mapurl'] = "https://example.com/"
        op = [dawdle.Player.new_player(pname, 'a', 'b') for pname in "abcd"]
        now = time.time()
        for p in op:
            p.level = 25
            p.lastlogin = now - 36001
        self.bot._overrides = {
            "quest_members": op,
            "quest_selection": "Q2 400 475 480 380 explore and chart the dark lands of T'rnalvph",
        }
        self.bot._players._online = op
        self.bot.quest_start()
        for p in op:
            p.posx, p.posy = 400, 475
        self.bot.quest_check()
        for p in op:
            p.posx, p.posy = 480, 380
        self.bot.quest_check()

        self.assertEqual(self.irc.chanmsgs, [
            "a, b, c, and d have been chosen by the gods to explore and chart the dark lands of T'rnalvph.  Participants must first reach (400,475), then (480,380). See https://example.com/ to monitor their journey's progress.",
            "a, b, c, and d have reached a landmark on their journey! 1 landmark remains.",
            "a, b, c, and d have completed their journey! 25% of their burden is eliminated."
        ])
        self.assertEqual(op[0].nextlvl, 450)
        self.assertEqual(op[1].nextlvl, 450)
        self.assertEqual(op[2].nextlvl, 450)
        self.assertEqual(op[3].nextlvl, 450)


    def test_questing_failure(self):
        dawdle.conf['rppenstep'] = 1.14
        op = [dawdle.Player.new_player(pname, 'a', 'b') for pname in "abcd"]
        self.bot._players._online = op
        now = time.time()
        for p in op:
            p.nick = p.name
            p.level = 25
            p.lastlogin = now - 36001
        self.bot._overrides = {
            "quest_members": op,
            "quest_selection": "Q1 locate the centuries-lost tomes of the grim prophet Haplashak Mhadhu",
            "quest_time": 12
        }
        self.bot._players._online = op
        self.bot.quest_start()
        self.bot.penalize(op[0], 'logout')

        self.assertListEqual(self.irc.chanmsgs, [
            "a, b, c, and d have been chosen by the gods to locate the centuries-lost tomes of the grim prophet Haplashak Mhadhu.  Quest to end in 0 days, 12:00:00.",
            "a's cowardice has brought the wrath of the gods down upon them.  All their great wickedness makes them heavy with lead, and to tend downwards with great weight and pressure towards hell. Therefore have they drawn themselves 15 steps closer to that gaping maw."
        ])
        self.assertListEqual(self.irc.notices['a'],
                             ["Penalty of 0 days, 00:08:40 added to your timer for LOGOUT command."])
        self.assertEqual(op[0].nextlvl, 1516)
        self.assertEqual(op[1].nextlvl, 996)
        self.assertEqual(op[2].nextlvl, 996)
        self.assertEqual(op[3].nextlvl, 996)





if __name__ == "__main__":
    unittest.main()
