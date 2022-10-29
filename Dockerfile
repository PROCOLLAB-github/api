FROM python:3.9.6-slim-buster as compiler

RUN pip install --no-cache-dir poetry


RUN python -m venv /opt/venv
# Enable venv
ENV PATH="/opt/venv/bin:$PATH"

# Copying requirements of a project
COPY pyproject.toml poetry.lock /procollab-backend/
WORKDIR /procollab-backend

FROM python:3.9.6-slim-buster as runner

COPY --from=compiler /opt/venv /opt/venv

# Installing requirements
RUN poetry install --no-root

# Enable venv
ENV PATH="/opt/venv/bin:$PATH"

# Copying actuall application
COPY . /procollab-backend/

CMD ["python", "manage.py", "runserver"]

# Uncommit this line if you want to use expose port
EXPOSE 8000