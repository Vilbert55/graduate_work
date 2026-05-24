#!/bin/bash
set -e

echo "Starting UGC API with Gunicorn (gevent workers)..."
exec gunicorn -c gunicorn.conf.py 'src.main:create_app()'