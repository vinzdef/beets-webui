#!/bin/sh
set -e

# Seed a minimal config on first run; users can then edit /config/config.yaml.
if [ ! -f "$BEETSDIR/config.yaml" ]; then
	mkdir -p "$BEETSDIR"
	cp /docker/config.yaml "$BEETSDIR/config.yaml"
fi

exec "$@"
