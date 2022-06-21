from fastapi import BackgroundTasks, FastAPI
from pydantic import BaseModel
from http import HTTPStatus
import logging
from pathlib import Path
from bdfr.downloader import DownloadFactory
from bdfr.exceptions import NotADownloadableLinkError, SiteDownloaderError
from os import environ


from praw.models import Submission

Log_Format = "%(levelname)s %(asctime)s - %(message)s"
logger = logging.getLogger(__name__)

app = FastAPI()


class Download(BaseModel):
    url: str


def download(submission_id: str):
    submission = Submission(id=submission_id)
    base_path = Path(environ.get('RIPPL_BASE_DOWNLOAD_PATH', '.'))
    subreddit_path = Path.joinpath(base_path, submission.subreddit)

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


@app.post("/download", status_code=HTTPStatus.ACCEPTED)
async def send_notification(dl: Download, background_tasks: BackgroundTasks):
    background_tasks.add_task(download, dl.url)
    return {"message": "Download started in the background"}