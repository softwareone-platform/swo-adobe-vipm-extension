FROM python:3.12.2-slim-bookworm
ENV PYTHONUNBUFFERED=1 POETRY_VERSION=1.7.0

RUN pip3 install poetry==$POETRY_VERSION

WORKDIR /extension

ADD . /extension

RUN poetry update && poetry install --with dev,runtime,sdk

CMD ["swoext", "run", "--no-color"]
