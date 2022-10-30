FROM python:3.9

RUN apt update --no-install-recommends -y

ENV PYTHONFAULTHANDLER=1 \
  PYTHONUNBUFFERED=1 \
  PYTHONHASHSEED=random \
  PIP_NO_CACHE_DIR=off \
  PIP_DISABLE_PIP_VERSION_CHECK=on \
  PIP_DEFAULT_TIMEOUT=100 \
  POETRY_VERSION=1.2.2

RUN pip install "poetry==$POETRY_VERSION"

RUN mkdir /procollab

WORKDIR /procollab

COPY poetry.lock pyproject.toml /procollab/

RUN poetry config virtualenvs.create false \
  && poetry install  --no-root

EXPOSE 8000

COPY . /procollab/

CMD ["bash", "startup.sh"]
