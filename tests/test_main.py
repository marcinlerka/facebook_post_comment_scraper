import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import sort_comments_for_export


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


if __name__ == "__main__":
    unittest.main()
