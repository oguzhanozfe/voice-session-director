"""Server-side chat transports for evidence-linked recommendations."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request


class ModelError(Exception):
    pass


def active_provider():
    return os.environ.get("MODEL_PROVIDER", "off").strip().lower()


def chat_request(provider, model, messages):
    base = os.environ.get("MODEL_BASE_URL", "").strip().rstrip("/")
    if not base and provider == "local":
        base = "http://127.0.0.1:11434/v1"
    if not base and provider == "api":
        base = "https://api.openai.com/v1"
    parsed = urllib.parse.urlsplit(base)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise ModelError(
            "Set MODEL_BASE_URL to the API root, without a query or embedded credentials."
        )
    key = os.environ.get("MODEL_API_KEY", "").strip()
    if provider in ("azure", "api") and parsed.scheme != "https":
        raise ModelError(
            "Hosted API connections require HTTPS. Use the local provider for a local endpoint."
        )
    headers = {"Content-Type": "application/json"}
    if provider == "azure":
        if not key:
            raise ModelError("Set MODEL_API_KEY to your Azure resource key.")
        if parsed.path in ("", "/"):
            base += "/openai/v1"
        headers["api-key"] = key
    elif key:
        headers["Authorization"] = "Bearer " + key
    elif provider == "api":
        raise ModelError("Set MODEL_API_KEY for your API provider.")
    limit = (
        "max_completion_tokens"
        if provider == "azure" or parsed.hostname == "api.openai.com"
        else "max_tokens"
    )
    body = {
        "model": model,
        "messages": messages,
        limit: 3072 if provider == "local" else 1024,
    }
    return urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(body).encode(),
        headers=headers,
        method="POST",
    )


def complete(messages):
    provider = active_provider()
    if provider not in ("local", "azure", "bedrock", "api"):
        raise ModelError("Choose MODEL_PROVIDER=local, azure, bedrock or api.")
    model = os.environ.get("MODEL_ID", "").strip()
    if not model:
        raise ModelError(
            "Set MODEL_ID to an installed model, Azure deployment, Bedrock model ID or inference profile."
        )
    if provider == "bedrock":
        try:
            import boto3
        except ImportError as exc:
            raise ModelError(
                "Install the Bedrock dependency with python -m pip install -r requirements.txt."
            ) from exc
        try:
            client = boto3.client(
                "bedrock-runtime", region_name=os.environ.get("AWS_REGION") or None
            )
            response = client.converse(
                modelId=model,
                system=[{"text": messages[0]["content"]}],
                messages=[
                    {"role": "user", "content": [{"text": messages[1]["content"]}]}
                ],
                inferenceConfig={"maxTokens": 1024},
            )
            answer = "\n".join(
                block["text"]
                for block in response["output"]["message"]["content"]
                if "text" in block
            )
        except Exception as exc:
            raise ModelError(
                "Bedrock request failed. Check the region, AWS identity, model access and Converse support."
            ) from exc
    else:
        request = chat_request(provider, model, messages)
        try:
            with urllib.request.urlopen(request, timeout=100) as response:
                payload = json.load(response)
            answer = payload["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as exc:
            raise ModelError(
                f"Model endpoint returned HTTP {exc.code}. Check the endpoint, model and credentials."
            ) from exc
        except (OSError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise ModelError(
                "No usable chat response. Check the model server and its OpenAI-compatible API root."
            ) from exc
    if not isinstance(answer, str) or not answer.strip():
        raise ModelError("The model returned no visible text.")
    return answer.strip()
