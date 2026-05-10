from __future__ import annotations

import unittest

from assetboy.providers.runbooks import provider_runbook_ids, render_provider_runbook


class ProviderRunbookTests(unittest.TestCase):
    def test_provider_runbook_ids_include_key_lanes(self) -> None:
        ids = provider_runbook_ids()
        self.assertIn("chatgpt_pro", ids)
        self.assertIn("google_pro", ids)
        self.assertIn("hunyuan3d2.production", ids)
        self.assertIn("animationgpt.pilot", ids)

    def test_static_manual_provider_runbooks_are_exposed(self) -> None:
        ids = set(provider_runbook_ids())
        self.assertIn("fab", ids)
        self.assertIn("mixamo", ids)
        self.assertIn("unity_asset_store", ids)
        self.assertIn("unreal_export_bridge", ids)
        self.assertIn("legendary", ids)

    def test_render_provider_runbook_for_google_pro_includes_setup(self) -> None:
        text = render_provider_runbook("google_pro")
        self.assertIn("official_url=https://ai.google.dev/gemini-api/docs/image-generation", text)
        self.assertIn("setup_steps:", text)
        self.assertIn("progression_steps:", text)

    def test_render_provider_runbook_for_hunyuan_includes_official_repo(self) -> None:
        text = render_provider_runbook("hunyuan3d2.production")
        self.assertIn("official_url=https://github.com/Tencent-Hunyuan/Hunyuan3D-2", text)
        self.assertIn("provider_family=colab_generator", text)

    def test_render_provider_runbook_for_chatgpt_pro_includes_setup(self) -> None:
        text = render_provider_runbook("chatgpt_pro")
        self.assertIn("display_name=ChatGPT Pro", text)
        self.assertIn("setup_steps:", text)

    def test_fab_runbook_includes_login_and_packet_guidance(self) -> None:
        text = render_provider_runbook("fab")
        self.assertIn("provider_family=manual_browser", text)
        self.assertIn("fab-auth --reuse-profile", text)
        self.assertIn("--allow-browser", text)
        self.assertIn("reviewed packet", text)

    def test_unreal_export_runbook_calls_out_partial_install_roots(self) -> None:
        text = render_provider_runbook("unreal_export_bridge")
        self.assertIn("provider_family=engine_bridge", text)
        self.assertIn("usable command path", text)
        self.assertIn("version root exists", text.lower())
