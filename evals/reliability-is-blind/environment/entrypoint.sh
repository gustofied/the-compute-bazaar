#!/bin/sh
set -eu

if [ "$#" -eq 0 ]; then
    exec sleep infinity
fi

exec "$@"
