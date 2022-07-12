import logging
from pathlib import Path
from sys import stdout
from typing import List
from os import environ
from enum import Enum

import typer
from bdfr.downloader import DownloadFactory
from bdfr.exceptions import NotADownloadableLinkError, SiteDownloaderError
from praw import Reddit
from praw.models import Submission

RIPPL_SECTION = "Rippl"

Log_Format = "%(levelname)s %(asctime)s - %(message)s"
LOGGER = logging.getLogger(__name__)


class LoggingLevel(str, Enum):
    critical = "critical"
    error = "error"
    warning = "warning"
    info = "info"
    debug = "debug"

    def __int__(self):
        level = self.__str__()

        if self.critical in level:
            return logging.CRITICAL
        elif self.error in level:
            return logging.ERROR
        elif self.warning in level:
            return logging.WARNING
        elif self.info in level:
            return logging.INFO
        elif self.debug in level:
            return logging.DEBUG


def main(
        submission_ids: List[str],
        logging_level: LoggingLevel = typer.Option(default='info'),
):
    logging.basicConfig(
        stream=stdout,
        format=Log_Format,
        level=int(logging_level),
    )

    r = Reddit(
        client_id=environ.get("RIPPL_CLIENT_ID"),
        client_secret=environ.get("RIPPL_CLIENT_SECRET"),
        password=environ.get("RIPPL_PASSWORD"),
        user_agent="rippl v1",
        username=environ.get("RIPPL_USERNAME"),
    )

    for submission_id in submission_ids:
        submission = Submission(r, id=submission_id)
        subreddit_path = Path.joinpath(
            Path(environ.get("RIPPL_BASE_DOWNLOAD_PATH", ".")),
            submission.subreddit.display_name,
        )

        try:
            downloader_class = DownloadFactory.pull_lever(submission.url)
            downloader = downloader_class(submission)
            LOGGER.debug(f'Using {downloader_class.__name__} with url {submission.url}')

        except NotADownloadableLinkError as e:
            LOGGER.error(f'Could not download submission {submission.id}: {e}')

            return
        try:
            resources = downloader.find_resources()
        except SiteDownloaderError as e:
            LOGGER.error(f'Site {downloader_class.__name__} failed to download submission {submission.id}: {e}')

            return

        for resource in resources:
            try:
                resource.download()

                ext = resource.extension if "." in resource.extension else f'.{resource.extension}'
                if "txt" in ext:
                    return

                filepath = Path.joinpath(subreddit_path, f'{submission.author}_{resource.hash.hexdigest()}{ext}')

                try:
                    Path(subreddit_path).mkdir(exist_ok=True)

                    with open(filepath, 'wb') as new:
                        new.write(resource.content)

                    LOGGER.debug(f'Downloaded: {filepath}')
                except Exception as e:
                    LOGGER.error(f'Failed to write file {filepath}: {e}')

            except Exception as e:
                LOGGER.error(f'Failed to download resource {resource.url} for submission {submission.id}: {e}')


if __name__ == "__main__":
    typer.run(main)
