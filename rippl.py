import gc
import logging.handlers
import signal
import threading
import time
from os import environ
from pathlib import Path
from sys import stdout
from typing import Optional, List

import typer
from bdfr.downloader import DownloadFactory
from bdfr.exceptions import NotADownloadableLinkError, SiteDownloaderError
from praw import Reddit, exceptions, models

Log_Format = "%(levelname)s %(asctime)s - %(message)s"
logger = logging.getLogger(__name__)


class BaseStreamer(threading.Thread):
    def __init__(
            self,
            client_id: str,
            client_secret: str,
            username: str,
            password: str,
            entity_name: str,
            search_terms: List[str],
            base_download_path: Path,
    ):
        threading.Thread.__init__(self)

        # The shutdown_flag is a threading.Event object that
        # indicates whether the thread should be terminated.
        self._shutdown_flag = threading.Event()

        self._entity_name = entity_name
        self._search_terms = search_terms

        self._download_path = Path.joinpath(base_download_path, entity_name.replace('-', '_'))

        self._client = Reddit(
            client_id=client_id,
            client_secret=client_secret,
            password=password,
            user_agent="rippl v1",
            username=username,
        )

    def run(self):
        self._stream()

    def begin_shutdown(self):
        self._shutdown_flag.set()

    @property
    def _entity(self):
        raise NotImplementedError

    def _stream(self):
        try:
            for submission in self._entity.stream.submissions(skip_existing=True, pause_after=-1):
                if self._shutdown_flag.is_set():
                    logger.info(f'Thread {self.ident} exited')
                    break
                elif submission is None:
                    gc.collect()

                    continue

                try:
                    self._download_submission(submission)
                except exceptions.PRAWException as e:
                    logger.error(f'Failed to retrieve submission: {e}')
        except Exception as e:
            logger.error(f'Failed to stream {self._entity_name}: {e}')

    def _download_submission(self, submission: models.Submission):
        if self._search_terms:
            if not any([t in submission.title for t in self._search_terms]):
                return

        try:
            downloader_class = DownloadFactory.pull_lever(submission.url)
            downloader = downloader_class(submission)
            logger.debug(f'Using {downloader_class.__name__} with url {submission.url}')

        except NotADownloadableLinkError as e:
            logger.error(f'Could not download submission {submission.id}: {e}')

            return
        try:
            resources = downloader.find_resources()
        except SiteDownloaderError as e:
            logger.error(f'Site {downloader_class.__name__} failed to download submission {submission.id}: {e}')

            return

        for resource in resources:
            try:
                resource.download()

                ext = resource.extension if "." in resource.extension else f'.{resource.extension}'
                if "txt" in ext:
                    return

                filepath = Path.joinpath(self._download_path, f'{submission.author}_{resource.hash.hexdigest()}{ext}')

                try:
                    Path(self._download_path).mkdir(exist_ok=True)

                    with open(filepath, 'wb') as new:
                        new.write(resource.content)

                    logger.info(f'Downloaded: {filepath}')
                except Exception as e:
                    logger.error(f'Failed to write file {filepath}: {e}')

            except Exception as e:
                logger.error(f'Failed to download resource {resource.url} for submission {submission.id}: {e}')


class SubredditStreamer(BaseStreamer):
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        username: str,
        password: str,
        subreddit_name: str,
        search_terms: List[str],
        base_download_path: Path,
    ):
        super().__init__(
            client_id,
            client_secret,
            username,
            password,
            subreddit_name,
            search_terms,
            base_download_path,
        )

    @property
    def _entity(self):
        return self._client.subreddit(self._entity_name)


class RedditorStreamer(BaseStreamer):
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        username: str,
        password: str,
        redditor_name: str,
        search_terms: List[str],
        base_download_path: Path,
    ):
        super().__init__(
            client_id,
            client_secret,
            username,
            password,
            redditor_name,
            search_terms,
            base_download_path
        )

    @property
    def _entity(self):
        return self._client.redditor(self._entity_name)


class ServiceExit(Exception):
    """
    Custom exception which is used to trigger the clean exit
    of all running threads and the main program.
    """
    pass


def service_shutdown(signum, _):
    logger.info('Caught signal %d, triggering graceful shutdown' % signum)
    raise ServiceExit


def main(
        client_id: str = typer.Option(environ.get('RIPPL_CLIENT_ID')),
        client_secret: str = typer.Option(environ.get('RIPPL_CLIENT_SECRET')),
        password: str = typer.Option(environ.get('RIPPL_PASSWORD')),
        username: str = typer.Option(environ.get('RIPPL_USERNAME')),
        subreddits: str = typer.Option(
            environ.get('RIPPL_SUBREDDITS', ''),
            help='Comma separated string, ex: "a,b,c" or "a, b, c"',
        ),
        redditors: str = typer.Option(
            environ.get('RIPPL_REDDITORS', ''),
            help='Comma separated string, ex: "a,b,c" or "a, b, c"',
        ),
        search_terms: str = typer.Option(
            environ.get('RIPPL_SEARCH_TERMS', ''),
            help='Comma separated string, ex: "a,b,c" or "a, b, c"',
        ),
        base_download_path: Optional[Path] = typer.Option(
            environ.get('RIPPL_BASE_DOWNLOAD_PATH', '.'),
            exists=True,
            dir_okay=True,
            writable=True,
        ),
):
    logging.basicConfig(
        stream=stdout,
        filemode="w",
        format=Log_Format,
        level=logging.INFO,
    )

    # Register the signal handlers
    signal.signal(signal.SIGTERM, service_shutdown)
    signal.signal(signal.SIGINT, service_shutdown)

    subreddits = [s.strip() for s in subreddits.split(',')] if len(subreddits) > 0 else []
    redditors = [r.strip() for r in redditors.split(',')] if len(redditors) > 0 else []
    search_terms = [s.strip() for s in search_terms.split(',')] if len(search_terms) > 0 else []

    num_threads = len(subreddits) + len(redditors)
    if num_threads == 0:
        logger.info("Nothing to do...")

        return
    else:
        logger.info(f'Starting {len(subreddits)} subreddit streamers and {len(redditors)} redditor streamers')

    streamers = [
        SubredditStreamer(
            client_id,
            client_secret,
            username,
            password,
            s,
            search_terms,
            base_download_path,
        ) for s in subreddits
    ]

    # noinspection PyTypeChecker
    streamers.extend(
        [
            RedditorStreamer(
                client_id,
                client_secret,
                username,
                password,
                r,
                search_terms,
                base_download_path,
            ) for r in redditors
        ]
    )

    try:
        for s in streamers:
            s.start()

        while True:
            time.sleep(0.5)
    except ServiceExit:
        for s in streamers:
            s.begin_shutdown()

        # wait for every streamer to stop
        for s in streamers:
            s.join()

    logging.info("Exited")


if __name__ == '__main__':
    typer.run(main)
