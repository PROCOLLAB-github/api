#!/bin/bash
cd apps
celery -A procollab worker --loglevel=debug
