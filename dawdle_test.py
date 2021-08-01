#!/usr/bin/python3

import dawdle
import os.path
import sys
import tempfile
import unittest

class TestPlayerDB(unittest.TestCase):
    def test_db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = dawdle.PlayerDB(os.path.join(tmpdir, 'dawdle_test.db'))
            self.assertFalse(db.exists())
            db.create()
            db.new_player('foo', 'bar', 'baz')
            db.write()
            self.assertTrue(db.exists())
            db.load()
            self.assertEqual(db['foo'].name, 'foo')

class TestIRCMessage(unittest.TestCase):
    def test_basic(self):
        line = "@time=2021-07-31T13:55:00,bar=baz :nick!example@example.com PART #example :later!"
        msg = dawdle.IRCClient.parse_message(None, bytes(line, encoding='utf8'))
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
        msg = dawdle.IRCClient.parse_message(None, bytes(line, encoding='utf8'))
        self.assertEqual(msg.tags, {})
        self.assertEqual(msg.src, "nick")

    def test_badtags(self):
        line = "@asdf :nick!example@example.com PART #example :later!"
        msg = dawdle.IRCClient.parse_message(None, bytes(line, encoding='utf8'))
        self.assertEqual(msg.tags, {'asdf': None})
        self.assertEqual(msg.src, "nick")

        line = "@ :nick!example@example.com PART #example :later!"
        msg = dawdle.IRCClient.parse_message(None, bytes(line, encoding='utf8'))
        self.assertEqual(msg.tags, {})
        self.assertEqual(msg.src, "nick")

    def test_bad_encoding(self):
        line = b"\255\035"
        msg = dawdle.IRCClient.parse_message(None, line)
        

if __name__ == "__main__":
    unittest.main()
