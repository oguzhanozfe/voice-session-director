"""Wire-level provider contracts verified without a network call or paid credential."""

import io
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import providers


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.messages = [
            {"role": "system", "content": "Cite evidence."},
            {"role": "user", "content": "[]"},
        ]

    def inspect_chat(self, config):
        answer = {"choices": [{"message": {"content": " Measured answer "}}]}
        with (
            patch.dict(os.environ, config),
            patch.object(
                providers.urllib.request,
                "urlopen",
                return_value=io.BytesIO(json.dumps(answer).encode()),
            ) as send,
        ):
            self.assertEqual(providers.complete(self.messages), "Measured answer")
        req = send.call_args.args[0]
        payload = json.loads(req.data)
        self.assertEqual(
            (req.get_method(), payload["model"], payload["messages"]),
            ("POST", config["MODEL_ID"], self.messages),
        )
        return req.full_url, {k.lower(): v for k, v in req.header_items()}, payload

    def test_azure_v1_deployment_and_resource_key(self):
        for base in (
            "https://unit.openai.azure.com",
            "https://unit.openai.azure.com/openai/v1/",
        ):
            with self.subTest(base=base):
                url, h, payload = self.inspect_chat(
                    {
                        "MODEL_PROVIDER": "azure",
                        "MODEL_ID": "deployment",
                        "MODEL_BASE_URL": base,
                        "MODEL_API_KEY": "fake",
                    }
                )
                self.assertEqual(
                    url, "https://unit.openai.azure.com/openai/v1/chat/completions"
                )
                self.assertEqual(h["api-key"], "fake")
                self.assertNotIn("authorization", h)
                self.assertIn("max_completion_tokens", payload)

    def test_bearer_api_and_optional_local_key(self):
        for mode, base in (
            ("api", "https://stub.test/v1"),
            ("local", "http://127.0.0.1:1234/v1"),
        ):
            url, h, payload = self.inspect_chat(
                {
                    "MODEL_PROVIDER": mode,
                    "MODEL_ID": "test",
                    "MODEL_BASE_URL": base,
                    "MODEL_API_KEY": "fake",
                }
            )
            self.assertEqual(url, base + "/chat/completions")
            self.assertEqual(h["authorization"], "Bearer fake")
            self.assertIn("max_tokens", payload)
        url, h, _ = self.inspect_chat({"MODEL_PROVIDER": "local", "MODEL_ID": "test"})
        self.assertEqual(url, "http://127.0.0.1:11434/v1/chat/completions")
        self.assertNotIn("authorization", h)

    def test_bedrock_sdk_contract_and_error_handling(self):
        boto = MagicMock()
        client = boto.client.return_value
        client.converse.return_value = {
            "output": {"message": {"content": [{"text": "One."}, {"text": "Two."}]}}
        }
        with (
            patch.dict(sys.modules, {"boto3": boto}),
            patch.dict(
                os.environ,
                {
                    "MODEL_PROVIDER": "bedrock",
                    "MODEL_ID": "profile",
                    "AWS_REGION": "eu-west-1",
                },
            ),
        ):
            self.assertEqual(providers.complete(self.messages), "One.\nTwo.")
            boto.client.assert_called_once_with(
                "bedrock-runtime", region_name="eu-west-1"
            )
            client.converse.assert_called_once_with(
                modelId="profile",
                system=[{"text": "Cite evidence."}],
                messages=[{"role": "user", "content": [{"text": "[]"}]}],
                inferenceConfig={"maxTokens": 1024},
            )
            client.converse.side_effect = RuntimeError("private SDK details")
            with self.assertRaises(providers.ModelError) as raised:
                providers.complete(self.messages)
            self.assertNotIn("private SDK details", str(raised.exception))

    def test_configuration_rejected_before_network(self):
        for config in (
            {"MODEL_PROVIDER": "off"},
            {"MODEL_PROVIDER": "local"},
            {"MODEL_PROVIDER": "api", "MODEL_ID": "named"},
            {
                "MODEL_PROVIDER": "azure",
                "MODEL_ID": "named",
                "MODEL_BASE_URL": "https://unit.test",
            },
            {
                "MODEL_PROVIDER": "api",
                "MODEL_ID": "named",
                "MODEL_BASE_URL": "http://unit.test",
                "MODEL_API_KEY": "demo",
            },
        ):
            with (
                self.subTest(config=config),
                patch.dict(os.environ, config),
                patch.object(providers.urllib.request, "urlopen") as send,
            ):
                with self.assertRaises(providers.ModelError):
                    providers.complete(self.messages)
                send.assert_not_called()

    def test_empty_wire_response_is_an_error(self):
        with (
            patch.dict(os.environ, {"MODEL_PROVIDER": "local", "MODEL_ID": "example"}),
            patch.object(
                providers.urllib.request,
                "urlopen",
                return_value=io.BytesIO(b'{"choices":[{"message":{"content":""}}]}'),
            ),
        ):
            self.assertRaises(providers.ModelError, providers.complete, self.messages)
