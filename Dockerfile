FROM python:3.9.6-slim

RUN pip install --no-cache-dir poetry

# Copying requirements of a project
COPY pyproject.toml poetry.lock /app/procollab-backend/
WORKDIR /app/procollab-backend

# Installing requirements
RUN poetry install --no-root

# Copying actuall application
COPY . /app/procollab-backend/
RUN poetry install --no-root

CMD ["/usr/local/bin/python", "manage.py", "runserver"]

# Uncommit this line if you want to use expose port
EXPOSE 8000