# Slack Stand-up Summariser

A serverless automation that pulls the last 24 hours of messages from a Slack channel each morning, runs a RAG pipeline against Amazon Bedrock Claude 3 Sonnet to produce a concise five-bullet summary, and posts the result back to Slack.

## Features

* Daily summary triggered by EventBridge schedule at 07:00 UTC (08:00 UK time)
* Fully serverless using AWS Lambda and AWS SAM
* Secure token storage in AWS Secrets Manager
* RAG pipeline with in-memory retriever and Amazon Bedrock LLM for high-quality summaries
* Local development and testing with SAM CLI and Docker

## Architecture

```
Slack channel -> Lambda function (scheduled) -> Secrets Manager -> Haystack + Bedrock -> Slack channel
```

Components:

* AWS Lambda function (Python 3.12)
* Amazon EventBridge rule for daily triggers
* AWS Secrets Manager stores the Slack bot token
* Haystack RAG pipeline uses Amazon Bedrock's Claude 3 Sonnet model
* Slack SDK reads channel history and posts summaries

## Prerequisites

1. AWS account with access to Amazon Bedrock in eu-west-2 (London)
2. Slack workspace with permission to create a bot
3. Local tools if developing locally:

   * AWS CLI v2
   * AWS SAM CLI
   * Docker Desktop (for container builds)
   * Python 3.12 (optional if not using Docker)

## Setup

1. Clone this repository:

   ```bash
   git clone <repository-url>
   cd SlackSummariser/slack-summariser
   ```

2. Create and configure your Slack bot:

   * In the Slack API portal, create a new app "Slack\_Summarizr" from scratch.
   * Under OAuth and Permissions, add these bot scopes:

     * channels\:history
     * channels\:read
     * chat\:write
   * Install the app to your workspace and copy the Bot User OAuth Token.
   * Invite the bot to your channel:

     ```
     /invite @Slack_Summarizr
     ```

3. Store the Slack token in AWS Secrets Manager:

   * In the AWS Console, go to Secrets Manager and store a new secret.
   * Name the secret path `slack/bot-token`.
   * Store the JSON payload:

     ```json
     { "SLACK_BOT_TOKEN": "xoxb-..." }
     ```

4. Edit `template.yaml` and set your values:

   ```yaml
   Environment:
     Variables:
       SLACK_BOT_TOKEN_SECRET_ARN: arn:aws:secretsmanager:eu-west-2:<account-id>:secret:slack/bot-token-<suffix>
       SLACK_CHANNEL_ID: "C01234567"
       HAYSTACK_TELEMETRY_ENABLED: "false"
   Policies:
     - AWSLambdaBasicExecutionRole
     - Statement:
         Effect: Allow
         Action:
           - secretsmanager:GetSecretValue
         Resource: arn:aws:secretsmanager:eu-west-2:<account-id>:secret:slack/bot-token-<suffix>
     - Statement:
         Effect: Allow
         Action:
           - bedrock:InvokeModel
         Resource:
           - arn:aws:bedrock:eu-west-2::foundation-model/anthropic.claude-3-sonnet-20240229-v1:0
   ```

## Build and Deploy

Run the following commands from the folder containing `template.yaml`:

```bash
sam build --use-container
sam deploy --guided --profile <aws-profile>
```

Follow the prompts to confirm stack name, AWS region, and IAM role creation.

## Testing and Verification

1. Invoke the function manually:

   * In VS Code AWS Explorer, right-click the function and select "Invoke on AWS" with payload `{}`
   * In the AWS Console, go to Lambda > Functions, select your function, and click "Test" with `{}`.
2. View the logs in CloudWatch under `/aws/lambda/<function-name>`.
3. Check your Slack channel for the summary or a notice that there were no messages.

## Local Development

You can use a `.env` file for local testing (ignored by Git):

```dotenv
SLACK_BOT_TOKEN_SECRET_ARN=arn:aws:secretsmanager:...
SLACK_CHANNEL_ID=C01234567
```

Invoke locally with:

```bash
sam local invoke SlackSummaryFunction --event events/event.json
```

## Customization

* To change the schedule, update the cron expression in `template.yaml` under `DailyTrigger`.
* To use a different model, change the `model` parameter in `AmazonBedrockGenerator`.
* To adjust the summary prompt, edit the prompt string in `app.py`.

## Troubleshooting

* If the Lambda function does not appear in the console, make sure you are in the correct AWS region and profile.