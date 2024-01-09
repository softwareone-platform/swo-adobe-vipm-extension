FROM python:3.12.1-slim-bookworm
ENV PYTHONUNBUFFERED=1 POETRY_VERSION=1.7.0

RUN pip3 install poetry==$POETRY_VERSION

WORKDIR /install_temp
COPY pyproject.toml poetry.* /install_temp

RUN poetry update && poetry install --with dev,devmock,runtime,sdk

ADD ./adobe_vipm /extension

WORKDIR /extension
