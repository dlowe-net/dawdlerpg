#!/bin/bash

if [[ "$UID" != "0" ]]; then
    echo This script must be run as root.
    exit 1
fi

if [[ "x$1" == "x" ]]; then
    echo "Usage: install.sh <hostname>" >/dev/stderr
    exit 1
fi

HOST="$1"

DIR="$(readlink -f $(dirname $0))"
echo "Using $DIR as dawdlerpg directory."

echo Installing services.
apt install -y nginx python3-pip
pip install django uwsgi Pillow

echo Configuring services.
sed "s#DAWDLERPG_DIR#${DIR}#g" setup/uwsgi.service >/etc/systemd/system/uwsgi.service
sed "s#DAWDLERPG_DIR#${DIR}#g" setup/uwsgi.ini >/etc/uwsgi.ini
sed "s#DAWDLERPG_DIR#${DIR}#g" setup/dawdlerpg.service >/etc/systemd/system/dawdlerpg.service
sed "s#DAWDLERPG_DIR#${DIR}#g" setup/dawdlerpg.nginx >/etc/nginx/sites-available/dawdlerpg
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/dawdlerpg /etc/nginx/sites-enabled/

systemctl enable uwsgi
systemctl enable dawdlerpg
systemctl enable nginx

echo Setting up dawdlerpg.
cp setup/dawdle.conf "$DIR/data"
cp setup/events.txt "$DIR/data"
pushd "$DIR/site/"
SECRET_KEY="$(openssl rand -base64 45)"
sed -e "/^SECRET_KEY/ c \\SECRET_KEY = '${SECRET_KEY}'" \
    -e "/^ALLOWED_HOSTS/ c \\ALLOWED_HOSTS = ['${HOST}']" \
    -e "/^DEBUG/ c \\DEBUG = False" \
    setup/project-settings.py \
    >project/settings.py
./manage.py migrate --database=default
./manage.py migrate --database=game
./manage.py collectstatic --no-input
cd "$DIR"
echo -n "You should now edit the dawdle.conf file for your particular game.  Press RETURN to begin editing."
read
"$EDITOR" "$DIR/data/dawdle.conf"
if [[ $! != 0 ]]; then
    exit $!
fi
"$DIR/dawdle.py" --setup "$DIR/data/dawdle.conf"
popd

chown -R www-data:www-data "$DIR"

echo Starting systems.
systemctl start uwsgi
systemctl restart nginx
systemctl start dawdlerpg

echo Done.
