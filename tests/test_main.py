import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import save_post_files, sort_comments_for_export


class SortCommentsForExportTests(unittest.TestCase):
    def test_sorts_comments_by_reactions_and_replies_by_time(self):
        comments = [
            {
                "comment_id": "low",
                "reaction_count": "2",
                "replies": [
                    {"reply_id": "late", "created_time": 30},
                    {"reply_id": "early", "created_time": 10},
                ],
            },
            {
                "comment_id": "high",
                "reaction_count": "24",
                "replies": [
                    {"reply_id": "second", "created_time": 20},
                    {"reply_id": "first", "created_time": 5},
                ],
            },
        ]

        sorted_comments = sort_comments_for_export(comments)

        self.assertEqual([c["comment_id"] for c in sorted_comments], ["high", "low"])
        self.assertEqual([r["reply_id"] for r in sorted_comments[0]["replies"]], ["first", "second"])
        self.assertEqual([r["reply_id"] for r in sorted_comments[1]["replies"]], ["early", "late"])

    def test_save_post_files_downloads_attachment_files(self):
        class FakeResponse:
            content = b"image-bytes"
            headers = {"content-type": "image/jpeg"}

            def raise_for_status(self):
                return None

        post_info = {
            "attachments": [
                {"file_url": "https://example.com/image"}
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("main.requests.get", return_value=FakeResponse()):
                save_post_files(tmpdir, "post-1", post_info)

            output_path = Path(tmpdir) / "files" / "post-1_attachment_1.jpg"
            self.assertEqual(output_path.read_bytes(), b"image-bytes")
            self.assertEqual(post_info["attachments"][0]["saved_file"], "files/post-1_attachment_1.jpg")


if __name__ == "__main__":
    unittest.main()
