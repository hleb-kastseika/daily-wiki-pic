"""AWS Lambda function for daily-wiki-pic bot."""

import mimetypes
import os
import re

import openai
import requests
from aws_lambda_powertools import Logger
from bs4 import BeautifulSoup
from mastodon import Mastodon

WIKIPEDIA_URL = "https://be.wikipedia.org/wiki/Галоўная_старонка"
DESIRED_IMAGE_SIZE = 2000  # px
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
}
TIMEOUT = 10
CAPTION_HASHTAGS = {"#wikipedia", "#photography"}
MASTODON = Mastodon(access_token=os.environ["MASTODON_TOKEN"], api_base_url=os.environ["MASTODON_URL"])
OPEN_AI = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
LOGGER = Logger()


def lambda_handler(_=None, __=None):
    """Handles API Gateway event."""
    image_url, image_caption = _fetch_wikipedia_data()
    LOGGER.info("Image URL: %s", image_url)
    LOGGER.info("Image caption: %s", image_caption)
    if image_url is None:
        LOGGER.error("Image URL was not found.")
        return

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
        srcset_items = [item.strip().split(" ") for item in image_tag["srcset"].split(",")]
        highest_res_url = srcset_items[-1][0] if srcset_items else None
        if highest_res_url:
            image_url = _adjust_image_size("https:" + highest_res_url)
    elif image_tag and "src" in image_tag.attrs:
        image_url = _adjust_image_size("https:" + image_tag["src"])

    # Get the caption
    br_tag = img_tag.find_parent("div").find("br")
    for sibling in br_tag.next_siblings:
        if sibling.name or sibling.string:
            image_caption += sibling.get_text(strip=True) if sibling.name else sibling

    if image_caption:
        image_caption = image_caption.strip()

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
    """Checks that the same image was not posted previously."""
    account_id = MASTODON.me()["id"]
    statuses_response = MASTODON.account_statuses(account_id, limit=40)

    for status in statuses_response:
        for media in status.get("media_attachments", []):
            if media.get("blurhash") == mastodon_media.get("blurhash"):
                return True

    return False


def _toot(image_url, caption):
    """Publishes image to Mastodon."""
    mastodon_media = MASTODON.media_post(
        media_file=requests.get(image_url, headers=HEADERS, timeout=TIMEOUT).content,
        mime_type=_get_mime_type(image_url),
    )

    if _is_posted(mastodon_media):
        LOGGER.info("The image was already posted some time ago")
        return

    description = _generate_image_description(image_url)
    LOGGER.info("Image description: %s", description)

    if description is not None:
        MASTODON.media_update(mastodon_media.id, description=description)

    LOGGER.info("Publishing image to Mastodon...")
    MASTODON.status_post(
        status="Выява дня: " + caption + "\n\n" + " ".join(_generate_hashtags(caption)),
        language="be",
        media_ids=[mastodon_media["id"]],
    )


def _generate_hashtags(caption):
    """Generates relevant hashtags in English from the caption."""
    LOGGER.info("Generating image hashtags...")
    hashtag_amount = 4
    try:
        response = OPEN_AI.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "user",
                    "content": f"""Generate only {hashtag_amount} relevant English hashtags in common words for posting in social media. 
                                   If some hashtag can be related to a specific name of country or city, just use that name. 
                                   It should be based on the following image caption:\n\n{caption}\n\nHashtags:""",
                }
            ],
            max_tokens=30,
        )
        CAPTION_HASHTAGS.update([t for t in response.choices[0].message.content.split() if t.startswith("#")])
    except Exception:
        LOGGER.exception("Failed to get hashtags from AI.")

    return CAPTION_HASHTAGS


def _generate_image_description(image_url):
    """Generates image description."""
    LOGGER.info("Generating image description...")
    try:
        resp = OPEN_AI.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты — асістэнт, які апісвае выявы па-беларуску (кірыліца). "
                        "Пішы каротка, простымі словамі, без англіцызмаў, без эмодзі. "
                        "ВЫХАД: роўна два сказы."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Апішы гэтую выяву ў двух простых сказах."},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                },
            ],
            max_tokens=120,
            temperature=0.2,
        )
        return resp.choices[0].message.content
    except Exception:
        LOGGER.exception("Failed to generate image description by AI")

    return None


# For local execution
if __name__ == "__main__":
    lambda_handler()
