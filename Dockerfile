# syntax=docker/dockerfile:1

FROM python:3.9-slim-buster

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip3 install -r requirements.txt

COPY . .

RUN apt-get -y update && apt-get install -y ffmpeg

CMD [ "python3", "-u", "rippl.py"]