import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import comment_scraper


class FakeResponse:
    def __init__(self, payload):
        self.text = json.dumps(payload)


def reply_page(text, has_next_page=False, end_cursor=None):
    return {
        "data": {
            "node": {
                "replies_connection": {
                    "edges": [
                        {
                            "node": {
                                "body": {"text": text},
                                "feedback": {"reactors": {"count_reduced": "0"}},
                            }
                        }
                    ],
                    "page_info": {
                        "has_next_page": has_next_page,
                        "end_cursor": end_cursor,
                    },
                }
            }
        }
    }


class FetchRepliesTests(unittest.TestCase):
    def test_comments_payload_uses_top_level_comment_cursor(self):
        payload = comment_scraper.comments_payload("feedback-id", cursor="comment-cursor")
        variables = json.loads(payload["variables"])

        self.assertEqual(variables["commentsAfterCursor"], "comment-cursor")
        self.assertNotIn("repliesAfterCursor", variables)

    def test_fetch_replies_paginates_until_no_next_page(self):
        responses = [
            FakeResponse(reply_page("first reply", has_next_page=True, end_cursor="cursor-1")),
            FakeResponse(reply_page("second reply", has_next_page=False)),
        ]
        calls = []

        def fake_retry_request(url, headers, data, proxies, cookies=None):
            calls.append(data)
            return responses.pop(0)

        comment = {
            "_feedback_id": "feedback-id",
            "_expansion_token": "expansion-token",
        }

        with patch.object(comment_scraper, "retry_request", side_effect=fake_retry_request):
            replies = comment_scraper.fetch_replies(comment)

        self.assertEqual([r["text"] for r in replies], ["first reply", "second reply"])
        self.assertEqual(len(calls), 2)
        second_variables = json.loads(calls[1]["variables"])
        self.assertEqual(second_variables["repliesAfterCursor"], "cursor-1")


if __name__ == "__main__":
    unittest.main()
