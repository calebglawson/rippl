import logging.handlers
from multiprocessing.pool import ThreadPool
from os import environ
from pathlib import Path
from typing import Optional, List

import typer
from praw import Reddit, exceptions, models
from bdfr.downloader import DownloadFactory
from bdfr.exceptions import NotADownloadableLinkError, SiteDownloaderError

logger = logging.getLogger(__name__)


def get_praw_client(client_id, client_secret, username, password):
    return Reddit(
        client_id=client_id,
        client_secret=client_secret,
        password=password,
        user_agent="rippl v1",
        username=username,
    )


def process_submission(submission: models.Submission, search_terms: List[str], base_path: Path):
    if search_terms:
        if not any([t in submission.title for t in search_terms]) and\
                not any([t in submission.selftext for t in search_terms]):
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

    Path(base_path).mkdir(exist_ok=True)
    for resource in resources:
        try:
            resource.download()

            filepath = Path.joinpath(
                base_path,
                f'{submission.author}_{resource.hash.hexdigest()}{resource.extension}',
            )

            try:
                with open(filepath, 'wb') as new:
                    new.write(resource.content)
            except Exception as e:
                logger.error(f'Failed to write file {filepath}: {e}')

        except Exception as e:
            logger.error(f'Failed to download resource {resource.url} for submission {submission.id}: {e}')


def stream_subreddit(work):
    reddit = get_praw_client(work.client_id, work.client_secret, work.username, work.password)
    subreddit = reddit.subreddit(work.reddit_entity)

    for submission in subreddit.stream.submissions(skip_existing=True):
        try:
            process_submission(submission, work.search_terms, work.download_path)
        except exceptions.PRAWException as e:
            logger.error(f'Failed to retrieve submission: {e}')


def stream_redditor(work):
    reddit = get_praw_client(work.client_id, work.client_secret, work.username, work.password)
    redditor = reddit.redditor(work.reddit_entity)

    for submission in redditor.stream.submissions(skip_existing=True):
        process_submission(submission, work.search_terms, work.download_path)


class Work:
    def __init__(
            self,
            client_id: str,
            client_secret: str,
            username: str,
            password: str,
            reddit_entity: str,
            search_terms: List[str],
            base_download_path: Path,
    ):
        self._run = True

        self.client_id = client_id
        self.client_secret = client_secret
        self.username = username
        self.password = password
        self.reddit_entity = reddit_entity
        self.search_terms = search_terms

        self.download_path = Path.joinpath(base_download_path, reddit_entity.replace('-', '_'))

    def stop(self):
        self._run = False


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
        search_terms: str = typer.Option('', help='Comma separated string, ex: "a,b,c" or "a, b, c"'),
        base_download_path: Optional[Path] = typer.Option(".", exists=True, dir_okay=True, writable=True),
):
    subreddits = [s.strip() for s in subreddits.split(',')] if len(subreddits) > 0 else []
    redditors = [r.strip() for r in redditors.split(',')] if len(redditors) > 0 else []

    thread_pool = ThreadPool(len(subreddits) + len(redditors))

    search_terms = [s.strip for s in search_terms.split(',')] if len(search_terms) > 0 else []

    for subreddit in subreddits:
        thread_pool.apply_async(
            stream_subreddit,
            args=(
                Work(
                    client_id,
                    client_secret,
                    username,
                    password,
                    subreddit,
                    search_terms,
                    base_download_path,
                ),
            ),
        )

    for redditor in redditors:
        thread_pool.apply_async(
            stream_redditor,
            args=(
                Work(
                    client_id,
                    client_secret,
                    username,
                    password,
                    redditor,
                    search_terms,
                    base_download_path,
                ),
            ),
        )

    thread_pool.close()
    thread_pool.join()


if __name__ == '__main__':
    typer.run(main)
