#!/bin/bash
cd apps
celery -A procollab worker --beat --loglevel=debug