# Deploying to Amazon Bedrock AgentCore Runtime

This agent is deployed, not opened. There is intentionally no persistent
client — only scheduled triggers and escalation replies.

## 0. Prerequisites

- AWS account with Bedrock model access enabled for the model in
  `GNA_MODEL_ID` (default: an Anthropic Claude model on Bedrock).
- Python 3.10+, Docker (or Finch/Podman), boto3, AWS credentials configured.
- `pip install bedrock-agentcore-starter-toolkit` for the fastest path
  (`agentcore configure` / `agentcore launch`), or build the container
  manually with `agentcore/Dockerfile` if you'd rather manage the pipeline
  yourself (Terraform/CDK).

## 1. Seed the datastore once

The demo/production datastore (SQLite by default) needs the schema created
and, for a real deployment, real org data loaded instead of `seed_data.py`'s
demo scenario:

```bash
python -m goodneighbor.cli init-db
python -m goodneighbor.cli seed   # demo only — replace with real data loading
```

For production, either bake a persisted volume/EFS mount into the container
so the SQLite file survives across invocations, or swap `db.py`'s
connection helper for RDS/Aurora — the rest of the codebase only depends on
the `get_conn()` context manager, so this is a one-file change.

## 2. Build & push the container

```bash
export AWS_ACCOUNT_ID=<account-id>
export AWS_REGION=us-east-1
export ECR_REPO=goodneighbor-agent

aws ecr create-repository --repository-name $ECR_REPO --region $AWS_REGION
aws ecr get-login-password --region $AWS_REGION \
  | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

docker buildx build --platform linux/arm64 \
  -t $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO:latest \
  --push -f agentcore/Dockerfile .
```

## 3. Create the AgentCore Runtime

Using the starter toolkit (recommended for a first deployment):

```bash
pip install bedrock-agentcore-starter-toolkit
agentcore configure --entrypoint agentcore/app.py --name goodneighbor-agent
agentcore launch
```

Or point an AgentCore Runtime resource (console or IaC) at the pushed image
URI directly. Either way, you get back an `agentRuntimeArn` — this is what
EventBridge and any manual test calls target via `InvokeAgentRuntime`.

Required IAM permissions for the Runtime's execution role: `bedrock:InvokeModel`
for the configured model id, plus whatever the datastore needs (e.g. RDS
Data API, or none for a local SQLite file baked into the container/EFS).

## 4. Schedule the background cycles (this replaces "opening the app")

Create one EventBridge Scheduler rule per cycle, each invoking the Runtime
via `InvokeAgentRuntime` with a fixed payload:

| Rule | Cadence | Payload |
|---|---|---|
| `goodneighbor-volunteers` | every 4 hours | `{"mode": "cycle", "cycle": "volunteers"}` |
| `goodneighbor-inventory` | daily, 6am local | `{"mode": "cycle", "cycle": "inventory"}` |
| `goodneighbor-donations` | every 30 min | `{"mode": "cycle", "cycle": "donations"}` |
| `goodneighbor-digest` | weekly, Monday 8am | `{"mode": "digest"}` |

```bash
aws scheduler create-schedule \
  --name goodneighbor-volunteers \
  --schedule-expression "rate(4 hours)" \
  --target "Arn=<agentRuntimeArn>,RoleArn=<scheduler-invoke-role>,Input='{\"mode\":\"cycle\",\"cycle\":\"volunteers\"}'" \
  --flexible-time-window "Mode=OFF"
```

(Repeat for the other three rules with their cadence/payload from the table.)

## 5. Wire up escalation delivery

Every `escalate_to_human` tool call writes a row to the `escalations` table
during a cycle invocation. To actually reach a coordinator's phone:

- Add a small Lambda triggered by the cycle's response (or poll
  `{"mode": "list_escalations"}` on a short EventBridge schedule) that
  formats each new pending escalation with
  `goodneighbor.escalation.format_escalation_for_sms` and publishes it to an
  SNS topic (SMS) or a Slack incoming webhook.
- A coordinator's reply ("2") maps back to `{"mode": "resolve_escalation",
  "escalation_id": <id>, "resolution": "Option 2: ..."}` invoked against the
  same Runtime — this is the only two-way, human-initiated traffic the
  system has.

## 6. Observability

AgentCore Runtime integrates with CloudWatch automatically for logs,
metrics, and traces of every invocation (each cycle run, each tool call).
Enable CloudWatch Transaction Search once per account to see full traces —
this is where you'd verify, for a demo or in production, exactly which
tools the agent called and why it did or didn't escalate on a given run.

## Local testing without any of the above

```bash
python agentcore/app.py
# in another terminal:
curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"mode": "cycle", "cycle": "volunteers"}'
```
