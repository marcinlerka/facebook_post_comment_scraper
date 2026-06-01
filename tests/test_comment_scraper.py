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


def reply_page(text, has_next_page=False, end_cursor=None, reply_id="reply-1", parent=None):
    node = {
        "legacy_fbid": reply_id,
        "created_time": 1779607551,
        "author": {"name": "Reply Author", "id": "reply-author-id"},
        "body": {"text": text},
        "feedback": {"reactors": {"count_reduced": "0"}},
    }
    if parent:
        node["comment_direct_parent"] = parent

    return {
        "data": {
            "node": {
                "replies_connection": {
                    "edges": [
                        {"node": node}
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
    def test_fetch_post_text_from_profile_finds_matching_story(self):
        timeline_payload = {
            "data": {
                "node": {
                    "timeline_list_feed_units": {
                        "edges": [
                            {
                                "node": {
                                    "__typename": "Story",
                                    "post_id": "post-1",
                                    "comet_sections": {
                                        "content": {
                                            "story": {
                                                "message": {"text": "full post body"}
                                            }
                                        }
                                    },
                                }
                            }
                        ],
                        "page_info": {"has_next_page": False, "end_cursor": None},
                    }
                }
            }
        }

        def fake_retry_request(url, headers, data, proxies, cookies=None):
            return FakeResponse(timeline_payload)

        with patch.object(comment_scraper, "retry_request", side_effect=fake_retry_request):
            post_text = comment_scraper.fetch_post_text_from_profile("author-1", "post-1")

        self.assertEqual(post_text, "full post body")

    def test_fetch_post_text_from_profile_paginates_with_larger_pages(self):
        first_page = {
            "data": {
                "node": {
                    "timeline_list_feed_units": {
                        "edges": [],
                        "page_info": {"has_next_page": True, "end_cursor": "next-page"},
                    }
                }
            }
        }
        second_page = {
            "data": {
                "node": {
                    "timeline_list_feed_units": {
                        "edges": [
                            {
                                "node": {
                                    "__typename": "Story",
                                    "post_id": "post-1",
                                    "comet_sections": {
                                        "content": {
                                            "story": {
                                                "message": {"text": "full post body"}
                                            }
                                        }
                                    },
                                }
                            }
                        ],
                        "page_info": {"has_next_page": False, "end_cursor": None},
                    }
                }
            }
        }
        responses = [FakeResponse(first_page), FakeResponse(second_page)]
        calls = []

        def fake_retry_request(url, headers, data, proxies, cookies=None):
            calls.append(data)
            return responses.pop(0)

        with patch.object(comment_scraper, "retry_request", side_effect=fake_retry_request):
            post_text = comment_scraper.fetch_post_text_from_profile(
                "author-1",
                "post-1",
                sleep_seconds=0,
            )

        self.assertEqual(post_text, "full post body")
        self.assertEqual(len(calls), 2)
        first_variables = json.loads(calls[0]["variables"])
        second_variables = json.loads(calls[1]["variables"])
        self.assertEqual(first_variables["count"], 10)
        self.assertEqual(second_variables["cursor"], "next-page")

    def test_fetch_comments_includes_author_metadata(self):
        comment_payload = {
            "data": {
                "node": {
                    "comment_rendering_instance_for_feed_location": {
                        "comments": {
                            "edges": [
                                {
                                    "node": {
                                        "legacy_fbid": "comment-1",
                                        "created_time": 1779607551,
                                        "author": {"name": "Comment Author", "id": "comment-author-id"},
                                        "body": {"text": "comment text"},
                                        "feedback": {
                                            "id": "feedback-1",
                                            "reactors": {"count_reduced": "0"},
                                            "expansion_info": {"expansion_token": "token-1"},
                                        },
                                    }
                                }
                            ],
                            "page_info": {"end_cursor": None},
                        }
                    }
                }
            }
        }

        with patch.object(comment_scraper, "retry_request", return_value=FakeResponse(comment_payload)):
            comments, _ = comment_scraper.fetch_comments("post-feedback-id")

        self.assertEqual(comments[0]["comment_id"], "comment-1")
        self.assertEqual(comments[0]["author"], "Comment Author")
        self.assertEqual(comments[0]["author_id"], "comment-author-id")
        self.assertEqual(comments[0]["created_time"], 1779607551)
        self.assertEqual(comments[0]["created_time_iso"], "2026-05-24T07:25:51+00:00")

    def test_fetch_replies_includes_author_metadata(self):
        response = FakeResponse(reply_page("reply text", has_next_page=False))
        comment = {
            "_feedback_id": "feedback-id",
            "_expansion_token": "expansion-token",
        }

        with patch.object(comment_scraper, "retry_request", return_value=response):
            replies = comment_scraper.fetch_replies(comment)

        self.assertEqual(replies[0]["reply_id"], "reply-1")
        self.assertEqual(replies[0]["author"], "Reply Author")
        self.assertEqual(replies[0]["author_id"], "reply-author-id")
        self.assertEqual(replies[0]["created_time"], 1779607551)
        self.assertEqual(replies[0]["created_time_iso"], "2026-05-24T07:25:51+00:00")

    def test_fetch_replies_includes_direct_parent_metadata(self):
        parent = {
            "id": "Y29tbWVudDoyNzYyODI4NTA3MDEwNzAyMl8xNTA0MDU2ODE0NTk1MjA3",
            "author": {
                "name": "Parent Author",
                "id": "parent-author-id",
            },
        }
        response = FakeResponse(reply_page("reply text", parent=parent))
        comment = {
            "_feedback_id": "feedback-id",
            "_expansion_token": "expansion-token",
        }

        with patch.object(comment_scraper, "retry_request", return_value=response):
            replies = comment_scraper.fetch_replies(comment)

        self.assertEqual(
            replies[0]["parent_comment_id"],
            "Y29tbWVudDoyNzYyODI4NTA3MDEwNzAyMl8xNTA0MDU2ODE0NTk1MjA3",
        )
        self.assertEqual(replies[0]["parent_comment_legacy_id"], "1504056814595207")
        self.assertEqual(replies[0]["parent_author"], "Parent Author")
        self.assertEqual(replies[0]["parent_author_id"], "parent-author-id")

    def test_comments_payload_uses_top_level_comment_cursor(self):
        payload = comment_scraper.comments_payload("feedback-id", cursor="comment-cursor")
        variables = json.loads(payload["variables"])

        self.assertEqual(variables["commentsAfterCursor"], "comment-cursor")
        self.assertNotIn("repliesAfterCursor", variables)

    def test_fetch_replies_paginates_until_no_next_page(self):
        responses = [
            FakeResponse(reply_page("first reply", has_next_page=True, end_cursor="cursor-1", reply_id="reply-1")),
            FakeResponse(reply_page("second reply", has_next_page=False, reply_id="reply-2")),
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
