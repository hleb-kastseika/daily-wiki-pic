# daily-wiki-pic
This is a small Python bot that fetches the picture of the day from Belarusian Wikipedia and posts it to Mastodon.
It also generates suitable hashtags from the image caption using ChatGPT.
It's implemented as an AWS Lambda function which is scheduled to run daily. Also it can be run locally.

## Requirements
 - Python 3.12 or higher
 - AWS SAM

## How to run locally
 1 configure and activate Python virtual environment:
```bash
python -m venv venv
source venv/bin/activate
```
 2 install Python dependencies:
```bash
pip install -r lambda/requirements.txt
```
 3 configure required environment variables:
```bash
export MASTODON_URL=your_value
export MASTODON_TOKEN=your_value
export OPENAI_API_KEY=your_value
```
 4 run the script:
```bash
python lambda/app.py
```

## How to build and deploy to AWS
```bash
sam build
sam deploy --guided
```
