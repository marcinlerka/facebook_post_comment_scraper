import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from json_to_markdown import fill_missing_post_text, render_markdown


class JsonToMarkdownTests(unittest.TestCase):
    def test_renders_sorted_comments_and_nested_replies(self):
        data = {
            "post_id": "post-1",
            "source_url": "https://example.com/post",
            "post_info": {
                "author": "Adam Example",
                "text": "Full post text",
            },
            "comments": [
                {
                    "comment_id": "low",
                    "author": "Low Commenter",
                    "text": "Less popular",
                    "created_time": 3,
                    "reaction_count": "2",
                    "replies": [],
                },
                {
                    "comment_id": "high",
                    "author": "High Commenter",
                    "text": "Most popular",
                    "created_time": 1,
                    "reaction_count": "24",
                    "replies": [
                        {
                            "reply_id": "reply-late",
                            "author": "Late Reply",
                            "text": "Late sibling",
                            "created_time": 30,
                            "parent_comment_legacy_id": "high",
                            "parent_author": "High Commenter",
                            "reaction_count": "1",
                        },
                        {
                            "reply_id": "reply-first",
                            "author": "First Reply",
                            "text": "First sibling",
                            "created_time": 10,
                            "parent_comment_legacy_id": "high",
                            "parent_author": "High Commenter",
                            "reaction_count": "3",
                        },
                        {
                            "reply_id": "nested",
                            "author": "Nested Reply",
                            "text": "Reply to reply",
                            "created_time": 20,
                            "parent_comment_legacy_id": "reply-first",
                            "parent_author": "First Reply",
                            "reaction_count": "0",
                        },
                    ],
                },
            ],
        }

        markdown = render_markdown(data)

        self.assertLess(markdown.index("### 1. @High Commenter"), markdown.index("### 2. @Low Commenter"))
        self.assertLess(markdown.index("@First Reply"), markdown.index("@Late Reply"))
        self.assertIn("    - **@Nested Reply** replying to @First Reply", markdown)
        self.assertIn("_24 reactions", markdown)
        self.assertIn("**Author:** @Adam Example", markdown)

    def test_fills_missing_post_text_from_source_url(self):
        data = {
            "source_url": "https://example.com/post",
            "post_info": {
                "author": "Adam Example",
                "text": None,
            },
            "comments": [],
        }

        fill_missing_post_text(data, fetcher=lambda url: f"Fetched from {url}")

        self.assertEqual(data["post_info"]["text"], "Fetched from https://example.com/post")


if __name__ == "__main__":
    unittest.main()
