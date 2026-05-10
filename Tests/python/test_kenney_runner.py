import unittest

from assetboy.execution.kenney_runner import resolve_kenney_download_url


class KenneyRunnerTests(unittest.TestCase):
    def test_resolve_kenney_download_url_extracts_donation_zip(self) -> None:
        html = """
        <div id='inline-download'>
            <p class='margin-top bold'>
                <a id='donate-text'
                   href='https://kenney.nl/media/pages/assets/medieval-rts/4e1b27c3ec-1677693589/kenney_medieval-rts.zip'
                   onclick='initiateDownload()'
                   data-lity-close>Continue without donating...</a>
            </p>
        </div>
        """
        resolved = resolve_kenney_download_url(
            "https://kenney.nl/assets/medieval-rts",
            pack_id="SHARED_KENNEY_MEDIEVAL_RTS_01",
            html=html,
        )
        self.assertEqual(
            resolved,
            "https://kenney.nl/media/pages/assets/medieval-rts/4e1b27c3ec-1677693589/kenney_medieval-rts.zip",
        )


if __name__ == "__main__":
    unittest.main()
