FROM golang:1.18.3 as builder
# Define build env
ENV GOOS linux
ENV CGO_ENABLED 0
# Add a work directory
WORKDIR /streamer
# Cache and install dependencies
COPY go.mod go.sum ./
RUN go mod download
# Copy app files
COPY main.go .
# Build app
RUN go build -o streamer

FROM python:3.10-slim-buster as production
# Copy built binary from builder
COPY --from=builder streamer .
# Python
COPY download.py requirements.txt ./
RUN pip install -r requirements.txt
RUN apt-get update && apt-get install ffmpeg -y8
# Exec built binary
CMD ./streamer
