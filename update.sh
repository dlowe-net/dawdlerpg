#!/bin/bash

set -x
set -e

DIR="$(readlink -f $(dirname $0))"
echo "Using $DIR as dawdlerpg directory"

echo "Updating source tree"
cd "$DIR"
git fetch -a
git stash
git merge origin/main
git stash pop

echo "Migrating db"
cd "$DIR/site"
./manage.py --database=default
./manage.py --database=game
./manage collectstatic --no-input
cd "$DIR"

chown -R www-data:www-data "$DIR"

echo "Restart bot and website"
systemctl restart dawdlerpg
systemctl restart uwsgi
