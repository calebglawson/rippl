Threaded, streaming downloader of Reddit media.

Why separate the Download Server from the Stream Client? Writing to external directories from a docker volume causes files to be cached in-memory on Linux hosts. While this memory is available to other processes, these files aren't accessed by the program after being downloaded.

## Download Server
1. Install python requirements.
2. Fill out the .env file template.
3. `uvicorn rippl:app --log-config ./logging.yml`

## Stream Client
1. Build an image from the Dockerfile.
2. Fill out the docker-compose template.
4. Deploy the stack.

## Attributions
The Download Server uses components of [Bulk Media Downloader for Reddit, which is GNU GPL Licensed](https://github.com/aliparlakci/bulk-downloader-for-reddit/blob/master/LICENSE).
