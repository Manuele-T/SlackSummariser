# slack_summary/app.py

import os
# disable Haystack telemetry before any haystack import
os.environ["HAYSTACK_TELEMETRY_ENABLED"] = "false"

import json
import time
import logging
import boto3

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from haystack_integrations.components.generators.amazon_bedrock import AmazonBedrockGenerator

# optional: load .env when running locally
if os.getenv("AWS_LAMBDA_FUNCTION_NAME") is None:
    from dotenv import load_dotenv
    load_dotenv()

# ── Logging ─────────────────────────────────────────────────────────────
log = logging.getLogger()
log.setLevel(logging.INFO)

# ── AWS clients ─────────────────────────────────────────────────────────
sm = boto3.client("secretsmanager")

def get_secret(arn: str) -> dict:
    """Fetch and parse a JSON secret from AWS Secrets Manager."""
    resp = sm.get_secret_value(SecretId=arn)
    return json.loads(resp["SecretString"])

# ── Bedrock LLM component ───────────────────────────────────────────────
generator = AmazonBedrockGenerator(
    model="anthropic.claude-3-sonnet-20240229-v1:0"
)

# ── Lambda entry point ─────────────────────────────────────────────────
def handler(event, context):
    """
    Daily Slack stand-up summariser:
    1) Load Slack token & channel ID from env/secrets
    2) Pull last 24h of messages
    3) Summarise into 5 bullets via Bedrock
    4) Post summary back to Slack
    """
    # 1. Load credentials & channel ID
    secret_arn = os.environ["SLACK_BOT_TOKEN_SECRET_ARN"]
    channel_id = os.environ["SLACK_CHANNEL_ID"]
    try:
        slack_token = get_secret(secret_arn)["SLACK_BOT_TOKEN"]
    except Exception as e:
        log.error("Unable to retrieve Slack token: %s", e)
        raise

    slack = WebClient(token=slack_token)

    # 2. Fetch last 24h of messages (integer timestamp)
    now = int(time.time())
    oldest = str(now - 24 * 3600)
    log.info("Fetching Slack history since %s", oldest)

    try:
        resp = slack.conversations_history(
            channel=channel_id,
            oldest=oldest,
            limit=200
        )
        log.info("Raw Slack response: %s", resp)
        messages = resp.get("messages", [])
        log.info("Fetched %d raw messages", len(messages))
    except SlackApiError as e:
        log.error("Error fetching Slack history: %s", e.response["error"])
        raise

    # extract text and log
    texts = [m.get("text", "") for m in messages if m.get("text")]
    log.info("Extracted %d text messages: %s", len(texts), texts)

    # handle empty history
    if not texts:
        post_text = (
            f"*Stand-up summary for <#{channel_id}> ({time.strftime('%Y-%m-%d')}):*\n"
            "_There are no stand-up messages to summarise today._"
        )
        try:
            slack.chat_postMessage(channel=channel_id, text=post_text)
            log.info("Posted 'no messages' notice to Slack.")
        except SlackApiError as e:
            log.error("Error posting 'no messages' notice: %s", e.response["error"])
            raise
        return {"statusCode": 200, "body": "Posted 'no messages' notice."}

    # 3. Call the LLM with a max_tokens parameter
    joined = "\n\n".join(texts)[-12000:]  # cap at last 12k chars
    prompt = (
        "Summarise the following stand-up updates into exactly five concise "
        "bullet points. Omit greetings and small talk:\n\n"
        + joined
    )
    try:
        result = generator.run(
            prompt=prompt,
            generation_kwargs={"max_tokens": 512}
        )
    except Exception as e:
        log.error("LLM call failed: %s", e)
        raise

    # validate response
    raw_replies = result.get("replies")
    if not isinstance(raw_replies, list) or not raw_replies:
        log.error("Unexpected LLM response format: %s", result)
        raise RuntimeError("Invalid LLM responses")

    summary = raw_replies[0].strip()

    # 4. Post summary back
    post_text = (
        f"*Stand-up summary for <#{channel_id}> ({time.strftime('%Y-%m-%d')}):*\n"
        f"{summary}"
    )
    try:
        slack.chat_postMessage(channel=channel_id, text=post_text)
        log.info("Summary posted successfully!")
    except SlackApiError as e:
        log.error("Error posting summary to Slack: %s", e.response["error"])
        raise

    return {"statusCode": 200, "body": json.dumps({"message": "Summary posted"})}