# slack_summary/app.py

import os
os.environ["HAYSTACK_TELEMETRY_ENABLED"] = "false"
import json
import time
import logging
import boto3

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from haystack_integrations.components.generators.amazon_bedrock import AmazonBedrockGenerator

# Optional: load .env when running locally
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
    # 1. Credentials & channel
    secret_arn = os.environ["SLACK_BOT_TOKEN_SECRET_ARN"]
    channel_id = os.environ["SLACK_CHANNEL_ID"]

    try:
        slack_token = get_secret(secret_arn)["SLACK_BOT_TOKEN"]
    except Exception as e:
        log.error("Unable to retrieve Slack token: %s", e)
        raise

    slack = WebClient(token=slack_token)

    # 2. Fetch last 24h of messages
    now = time.time()
    oldest = str(now - 24 * 3600)
    try:
        resp = slack.conversations_history(channel=channel_id, oldest=oldest, limit=200)
        messages = resp.get("messages", [])
    except SlackApiError as e:
        log.error("Error fetching Slack history: %s", e.response["error"])
        raise

    texts = [m.get("text", "") for m in messages if m.get("text")]
    if not texts:
        log.info("No messages to summarise.")
        return {"statusCode": 200, "body": "No messages to summarise."}

    # Safety cap for Bedrock input
    joined = "\n\n".join(texts)
    prompt_input = joined[-12000:]

    # 3. Call the LLM
    prompt = (
        "Summarise the following stand-up updates into exactly five concise "
        "bullet points. Omit greetings and small talk:\n\n"
        + prompt_input
    )
    try:
        result = generator.run(prompt=prompt)
    except Exception as e:
        log.error("LLM call failed: %s", e)
        raise

    # Extract replies and validate
    raw_replies = result.get("replies")
    if not isinstance(raw_replies, list) or not raw_replies:
        log.error("Unexpected LLM response format: %s", result)
        raise RuntimeError("Invalid LLM responses")

    summary = raw_replies[0].strip()

    # 4. Post summary back
    post_text = f"*Stand-up summary for <#{channel_id}> ({time.strftime('%Y-%m-%d')}):*\n{summary}"
    try:
        slack.chat_postMessage(channel=channel_id, text=post_text)
    except SlackApiError as e:
        log.error("Error posting to Slack: %s", e.response["error"])
        raise

    log.info("Summary posted successfully.")
    return {"statusCode": 200, "body": json.dumps({"message": "Summary posted"})}
