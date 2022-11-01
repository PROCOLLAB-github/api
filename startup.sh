#!/bin/bash

celery -A procollab.celery worker --pool=solo  -l info --detach

redis-server --daemonize yes

python manage.py migrate
python manage.py collectstatic
python manage.py runserver 0.0.0.0:8000 --noreload
