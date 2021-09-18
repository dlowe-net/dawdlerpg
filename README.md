# DawdleRPG

DawdleRPG is an IdleRPG clone written in Python.

## Basic Setup

- Edit `dawdle.conf` to configure your bot.
- Run `dawdle.py <path to dawdle.conf>`
- The data directory defaults to the parent directory of the
  configuration file, and dawdlerpg expects files to be in that
  directory.

## Setup with Website

The website is written on top of the Django web framework, so it must
first be installed.

- Run `pip install django`, making sure that `~/.local/bin` is part of
  your `PATH` environment variable.
- Run `site/manage.py migrate` to create the main database.
- Run `site/manage.py migrate --database=game` to create the main database.
- Set `store_format sqlite3` in your `dawdle.conf`
- Set `dbfile <path to site/game.sqlite3>` in your `dawdle.conf`
- Run `dawdle.py <path to your dawdle.conf>`
- Point a webserver at your Django instance.

## Migrating from IdleRPG

DawdleRPG is capable of being a drop-in replacement.

- Run `dawdle.py <path to old irpg.conf>`

If you have any command line overrides to the configuration, you will
need to replace them with the `-o key=value` option.

## Differences from IdleRPG

- Names, items, and durations are in different colors.
- Output throttling allows configurable rate over a period.
- Long messages are word wrapped.
- Logging can be set to different levels.
- Better IRC protocol support.
- More game numbers are configurable.
- Quest pathfinding is much more efficient.
- Fights caused by map collisions have chance of finding item.
- All worn items have a chance to get buffs/debuffs instead of a subset.
