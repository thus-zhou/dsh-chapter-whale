"""ModelGateway：唯一出口、隐私域、op_id、空输出与诊断脱敏。"""
import asyncio
import tempfile
import unittest
from pathlib import Path

from integration import model_gateway as mg


class FakeService:
    def __init__(self, reply="好的"):
        self.reply = reply
        self.model = "fake-model"
        self.retry_count = 0
        self.calls = []

    async def chat(self, messages, **kwargs):
        self.calls.append(messages)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def config(privacy="private_api", protocol="openai"):
    return {
        "multi_model": False,
        "providers": {"p1": {"id": "p1", "name": "主模型", "base_url": "https://api.example.com/v1",
                             "protocol": protocol, "privacy": privacy},
                      "p2": {"id": "p2", "name": "免费池", "base_url": "https://free.example.com/v1",
                             "protocol": "free_pool", "privacy": "free_pool_shared"}},
        "default_binding": {"provider_id": "p1", "model_id": "m1"},
        "roles": {},
    }


class GatewayTest(unittest.TestCase):
    def test_invoke_requires_op_id_and_returns_text(self):
        service = FakeService("候选正文")
        gateway = mg.ModelGateway(config=config(), service_factory=lambda role, cfg: service)
        with self.assertRaises(mg.GatewayError):
            gateway.invoke_sync("C", [{"role": "user", "content": "x"}])
        text = gateway.invoke_sync("C", [{"role": "user", "content": "x"}], op_id="op-1")
        self.assertEqual(text, "候选正文")
        self.assertEqual(len(gateway.diagnostics), 1)
        diag = gateway.diagnostics[0]
        self.assertTrue(diag["redacted"])
        self.assertEqual(diag["model"], "fake-model")
        self.assertNotIn("x", str(diag))

    def test_empty_output_is_error_not_silent_success(self):
        gateway = mg.ModelGateway(config=config(),
                                  service_factory=lambda role, cfg: FakeService("   "))
        with self.assertRaises(mg.GatewayError) as caught:
            gateway.invoke_sync("C", [{"role": "user", "content": "x"}], op_id="op-empty")
        self.assertEqual(caught.exception.code, "empty_model_output")

    def test_privacy_downgrade_is_refused(self):
        cfg = config(privacy="local_offline")
        gateway = mg.ModelGateway(config=cfg, service_factory=lambda role, c: FakeService())
        with self.assertRaises(mg.PrivacyViolation):
            gateway.invoke_sync("C", [{"role": "user", "content": "x"}], op_id="op-p",
                                override_binding={"provider_id": "p2", "model_id": "free"})
        # 同等隐私域允许
        gateway.check_binding("C", {"provider_id": "p1", "model_id": "m2"})

    def test_free_pool_cannot_silently_upgrade_to_private(self):
        cfg = config(privacy="free_pool_shared", protocol="free_pool")
        cfg["default_binding"] = {"provider_id": "p2", "model_id": "free"}
        gateway = mg.ModelGateway(config=cfg, service_factory=lambda role, c: FakeService())
        # 免费池 -> 私有付费是“更严格”的域，按契约允许显式单步换模型，但不得自动降级。
        self.assertTrue(mg.privacy_allowed("free_pool_shared", "private_api"))
        self.assertFalse(mg.privacy_allowed("private_api", "free_pool_shared"))
        self.assertFalse(mg.privacy_allowed("local_offline", "private_api"))

    def test_pause_blocks_new_calls(self):
        gateway = mg.ModelGateway(config=config(), service_factory=lambda role, c: FakeService(),
                                  pause_check=lambda: True)
        with self.assertRaises(mg.GatewayError) as caught:
            gateway.invoke_sync("C", [{"role": "user", "content": "x"}], op_id="op-pause")
        self.assertEqual(caught.exception.code, "ai_paused")

    def test_annotation_prompt_isolates_untrusted_material(self):
        service = FakeService("<replacement>改好了</replacement>")
        gateway = mg.ModelGateway(config=config(), service_factory=lambda role, c: service)
        generator = gateway.annotation_generator(Path("/tmp/book"), 3)
        text = generator({"id": "ann_1", "variant": 0},
                         {"instruction": "更克制", "current_text": "他说：我很害怕。",
                          "range": [3, 7]})
        self.assertIn("改好了", text)
        prompt = service.calls[0][-1]["content"]
        self.assertIn("<UNTRUSTED_MATERIAL>", prompt)
        self.assertIn("<TARGET>我很害怕</TARGET>", prompt)
        self.assertIn("不可信资料", service.calls[0][0]["content"])

    def test_service_failure_propagates(self):
        gateway = mg.ModelGateway(config=config(),
                                  service_factory=lambda role, c: FakeService(RuntimeError("boom")))
        with self.assertRaises(RuntimeError):
            gateway.invoke_sync("C", [{"role": "user", "content": "x"}], op_id="op-fail")


if __name__ == "__main__":
    unittest.main()
