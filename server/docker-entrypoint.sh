#!/bin/sh
set -e
# Bring the database schema up to date before the server starts.
alembic upgrade head
exec "$@"
