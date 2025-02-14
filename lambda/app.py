"""AWS Lambda function for daily-wiki-pic bot."""

import logging
import mimetypes
import os
import re

import openai
import requests
from bs4 import BeautifulSoup
from mastodon import Mastodon

WIKIPEDIA_URL = "https://be.wikipedia.org/wiki/Галоўная_старонка"
DESIRED_IMAGE_SIZE = 2000  # px
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
}
TIMEOUT = 10
CAPTION_HASHTAGS = {"#Wikipedia", "#Picture"}
MASTODON = Mastodon(
    access_token=os.environ["MASTODON_TOKEN"], api_base_url=os.environ["MASTODON_URL"]
)
OPEN_AI = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
LOGGER = logging.getLogger(__name__)
logging.getLogger().setLevel(logging.INFO)


def lambda_handler(_=None, __=None):
    """Handles API Gateway event."""
    image_url, image_caption = _fetch_wikipedia_data()
    if image_url is None:
        LOGGER.error("Image URL was not found.")
        return

    LOGGER.info("Image URL: %s", image_url)
    LOGGER.info("Caption: %s", image_caption)
    _toot(image_url, image_caption)


def _fetch_wikipedia_data():
    """Grabs image URL and caption from Wikipedia."""
    LOGGER.info("Fetching Wikipedia data...")
    image_url = None
    image_caption = ""

    response = requests.get(WIKIPEDIA_URL, headers=HEADERS, timeout=TIMEOUT)
    soup = BeautifulSoup(response.content, "html.parser")

    potd_header = None
    for h2 in soup.find_all("h2"):
        if "Выява дня" in h2.get_text():
            potd_header = h2
            break

    if not potd_header:
        return image_url, image_caption

    img_tag = potd_header.find_next("div").find("img")
    if not img_tag:
        return image_url, image_caption

    filename = img_tag.find_parent("a")["href"].split(":")[-1]
    media_page_url = f"{WIKIPEDIA_URL}#/media/Файл:{filename}"

    media_response = requests.get(media_page_url, headers=HEADERS, timeout=TIMEOUT)
    media_soup = BeautifulSoup(media_response.content, "html.parser")
    image_tag = media_soup.find("h2", id="Выява_дня").find_next("img")
    if image_tag and "srcset" in image_tag.attrs:
        image_url = _adjust_image_size(
            "https:" + image_tag["srcset"].split(",")[-1].split(" ")[1]
        )

    # Get the caption
    br_tag = img_tag.find_parent("div").find("br")
    for sibling in br_tag.next_siblings:
        if sibling.name or sibling.string:
            image_caption += sibling.get_text(strip=True) if sibling.name else sibling

    if image_caption:
        image_caption = image_caption.strip()
        image_caption = image_caption + "\n\n" + " ".join(_generate_hashtags(image_caption))

    return image_url, image_caption


def _adjust_image_size(url):
    """Compares the size of the image with desired value and takes bigger value if needed."""
    match = re.search(r"/(\d+)px-", url)
    if match:
        pixel_size = int(match.group(1))
        if pixel_size < DESIRED_IMAGE_SIZE:
            url = re.sub(r"/\d+px-", f"/{DESIRED_IMAGE_SIZE}px-", url)

    return url


def _get_mime_type(url):
    """Returns the mime type of the file from a link."""
    mime_type, _ = mimetypes.guess_type(url.split("/")[-1])
    return mime_type


def _is_posted(mastodon_media):
    """Checks that the same image was not posted already last time."""
    account_id = MASTODON.me()["id"]
    statuses_response = MASTODON.account_statuses(account_id, limit=1)
    if len(statuses_response) == 0 or len(statuses_response[0]["media_attachments"]) == 0:
        return False

    return statuses_response[0]["media_attachments"][0]["blurhash"] == mastodon_media["blurhash"]


def _toot(image_url, caption):
    """Publishes image to Mastodon."""
    LOGGER.info("Publishing image to Mastodon...")
    mastodon_media = MASTODON.media_post(
        media_file=requests.get(image_url, headers=HEADERS, timeout=TIMEOUT).content,
        mime_type=_get_mime_type(image_url),
        description=caption,
    )

    if _is_posted(mastodon_media):
        LOGGER.error("The image was already posted last time. Image URL: %s", image_url)
        return

    MASTODON.status_post(
        status="🖼️ Выява дня: " + caption,
        language="be",
        media_ids=[mastodon_media["id"]],
    )


def _generate_hashtags(caption):
    """Generates relevant hashtags in English from the caption."""
    required_amount = 2
    try:
        response = OPEN_AI.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "user",
                    "content": f"Generate only {required_amount} relevant English hashtags in common words for posting in social media based on the following image caption:\n\n{caption}\n\nHashtags:",
                }
            ],
            max_tokens=30,
        )
        CAPTION_HASHTAGS.update(
            [t for t in response.choices[0].message.content.split() if t.startswith("#")]
        )
    except Exception:
        LOGGER.exception("Failed to get hashtags from AI.")

    return CAPTION_HASHTAGS


# For local execution
if __name__ == "__main__":
    lambda_handler()
