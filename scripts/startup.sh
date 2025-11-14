#!/bin/bash

python manage.py migrate
python manage.py collectstatic --no-input

# Use Daphne ASGI server instead of Django's dev server.
exec daphne -b 0.0.0.0 -p 8000 procollab.asgi:application
