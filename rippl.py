from fastapi import BackgroundTasks, FastAPI, Depends
from pydantic import BaseModel, BaseSettings
from http import HTTPStatus
import logging
from pathlib import Path
from bdfr.downloader import DownloadFactory
from bdfr.exceptions import NotADownloadableLinkError, SiteDownloaderError
from functools import lru_cache
import uvicorn.workers.UvicornWorker

from praw import Reddit
from praw.models import Submission

logger = logging.getLogger(__name__)

app = FastAPI()


class Download(BaseModel):
    submission_id: str


class Settings(BaseSettings):
    rippl_client_id: str
    rippl_client_secret: str
    rippl_username: str
    rippl_password: str
    rippl_base_download_path: Path

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings():
    return Settings()


def download(submission_id: str, settings: Settings):
    r = Reddit(
        client_id=settings.rippl_client_id,
        client_secret=settings.rippl_client_secret,
        password=settings.rippl_password,
        user_agent="rippl v1",
        username=settings.rippl_username,
    )

    submission = Submission(r, id=submission_id)
    subreddit_path = Path.joinpath(settings.rippl_base_download_path, submission.subreddit.display_name)

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

            filepath = Path.joinpath(subreddit_path, f'{submission.author}_{resource.hash.hexdigest()}{ext}')

            try:
                Path(subreddit_path).mkdir(exist_ok=True)

                with open(filepath, 'wb') as new:
                    new.write(resource.content)

                logger.info(f'Downloaded: {filepath}')
            except Exception as e:
                logger.error(f'Failed to write file {filepath}: {e}')

        except Exception as e:
            logger.error(f'Failed to download resource {resource.url} for submission {submission.id}: {e}')


@app.post("/", status_code=HTTPStatus.ACCEPTED)
async def accept_download(dl: Download, background_tasks: BackgroundTasks, settings: Settings = Depends(get_settings)):
    background_tasks.add_task(download, dl.submission_id, settings)

    return {"message": "Downloading in background"}
