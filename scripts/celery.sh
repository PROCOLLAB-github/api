#!/bin/bash
set -eu

exec celery -A procollab worker --beat --loglevel=debug
