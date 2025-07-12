# slack_summary/app.py

import os
import json
import time
import boto3
from slack_sdk import WebClient
from haystack import Pipeline
from haystack.components.generators.bedrock import BedrockGenerator
from haystack.components.retrievers.in_memory import InMemoryEmbeddingRetriever

# 1️⃣ Initialize AWS clients & RAG pipeline at cold start
sm = boto3.client("secretsmanager")

# Build your Haystack RAG pipeline
generator = BedrockGenerator(model="anthropic.claude-3-sonnet-20240229-v1:0")
retriever = InMemoryEmbeddingRetriever(embedding_model="amazon.titan-embed-text-v2:0")
pipe = (
    Pipeline()
    .add_component("retrieve", retriever)
    .add_component("generate", generator)
    .connect("retrieve", "generate")
)

def get_secret(arn: str) -> dict:
    """Fetch and parse a JSON secret from AWS Secrets Manager."""
    resp = sm.get_secret_value(SecretId=arn)
    return json.loads(resp["SecretString"])

def handler(event, context):
    """
    Lambda entry point for Slack Stand-up Summariser.

    1. Load Slack bot token from Secrets Manager.
    2. Pull last 24 h of messages from the target Slack channel.
    3. Run RAG pipeline to generate a 5-bullet summary.
    4. Post the summary back to Slack.
    """

    # ── 1. Fetch credentials & channel info ───────────────────────────────
    secret_arn      = os.environ["SLACK_BOT_TOKEN_SECRET_ARN"]
    slack_token     = get_secret(secret_arn)["SLACK_BOT_TOKEN"]
    channel_id      = os.environ["SLACK_CHANNEL_ID"]       # e.g. "C01234567"

    client = WebClient(token=slack_token)

    # ── 2. Pull last 24h of messages ────────────────────────────────────
    now       = time.time()
    yesterday = now - 24 * 3600
    history   = client.conversations_history(
        channel=channel_id,
        oldest=str(yesterday),
        limit=200
    )["messages"]

    texts     = [m.get("text","") for m in history if "text" in m]
    full_text = "\n\n".join(texts)

    # ── 3. Run the RAG pipeline for a 5-bullet summary ───────────────────
    result = pipe.run(
        query=(
            "Summarise the following stand-up messages into exactly "
            "5 concise bullet points:\n\n" + full_text
        ),
        params={
            "generate": {"max_length": 150, "min_length": 50}
        }
    )
    summary = result["generate"][0]["generated_text"].strip()

    # ── 4. Post back to Slack ─────────────────────────────────────────────
    post_text = f"*Stand-up summary for <#{channel_id}> ({time.strftime('%Y-%m-%d')}):*\n{summary}"
    client.chat_postMessage(channel=channel_id, text=post_text)

    return {"statusCode": 200, "body": json.dumps({"message": "Summariser ran"})}
