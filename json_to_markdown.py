import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def markdown_escape(value):
    text = "" if value is None else str(value)
    return (
        text.replace("\\", "\\\\")
        .replace("*", "\\*")
        .replace("_", "\\_")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("`", "\\`")
    )


def mention(name):
    if not name:
        return "@Unknown"
    return f"@{markdown_escape(name)}"


def numeric_value(value, default=0):
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower().replace(",", "")
        multipliers = {
            "k": 1000,
            "m": 1000000,
        }
        suffix = normalized[-1:] if normalized else ""
        try:
            if suffix in multipliers:
                return float(normalized[:-1]) * multipliers[suffix]
            return float(normalized)
        except ValueError:
            return default
    return default


def display_reactions(value):
    count = numeric_value(value)
    if count == 0:
        return "0 reactions"
    if count == 1:
        return "1 reaction"
    if float(count).is_integer():
        return f"{int(count)} reactions"
    return f"{count:g} reactions"


def display_time(item):
    iso_time = item.get("created_time_iso")
    if iso_time:
        try:
            parsed = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        except ValueError:
            return iso_time

    created_time = item.get("created_time")
    if created_time:
        try:
            parsed = datetime.fromtimestamp(float(created_time), tz=timezone.utc)
            return parsed.strftime("%Y-%m-%d %H:%M UTC")
        except (TypeError, ValueError, OSError):
            return str(created_time)

    return "unknown time"


def item_id(item):
    return item.get("comment_id") or item.get("reply_id")


def sort_comments(comments):
    sorted_comments = sorted(
        comments,
        key=lambda comment: numeric_value(comment.get("reaction_count")),
        reverse=True,
    )

    for comment in sorted_comments:
        comment["replies"] = sorted(
            comment.get("replies", []),
            key=lambda reply: numeric_value(reply.get("created_time")),
        )

    return sorted_comments


def build_reply_tree(comment):
    replies = comment.get("replies", [])
    by_parent = defaultdict(list)
    known_ids = {comment.get("comment_id")}

    for reply in replies:
        reply_id = reply.get("reply_id")
        if reply_id:
            known_ids.add(reply_id)

    root_id = comment.get("comment_id")
    for reply in replies:
        parent_id = reply.get("parent_comment_legacy_id") or root_id
        if parent_id not in known_ids:
            parent_id = root_id
        by_parent[parent_id].append(reply)

    return by_parent


def format_text(text, indent):
    cleaned = (text or "").strip()
    if not cleaned:
        return [f"{indent}> _No text captured._"]

    lines = []
    for paragraph in cleaned.splitlines():
        paragraph = paragraph.strip()
        if paragraph:
            lines.append(f"{indent}> {markdown_escape(paragraph)}")
        else:
            lines.append(f"{indent}>")
    return lines


def render_comment_item(item, children_by_parent, depth=0):
    indent = "  " * depth
    author = mention(item.get("author"))
    parent_author = item.get("parent_author")
    parent_note = f" replying to {mention(parent_author)}" if parent_author else ""
    meta = f"{display_reactions(item.get('reaction_count'))} | {display_time(item)}"

    lines = [
        f"{indent}- **{author}**{parent_note}  ",
        f"{indent}  _{meta}_",
    ]
    lines.extend(format_text(item.get("text"), f"{indent}  "))

    for child in children_by_parent.get(item_id(item), []):
        lines.append("")
        lines.extend(render_comment_item(child, children_by_parent, depth + 1))

    return lines


def render_post_header(data):
    post_info = data.get("post_info") or {}
    post_author = post_info.get("author")
    post_text = (post_info.get("text") or "").strip()

    title = f"Facebook post {data.get('post_id', 'unknown')}"
    lines = [f"# {markdown_escape(title)}", ""]

    if post_author:
        lines.extend([f"**Author:** {mention(post_author)}", ""])
    if data.get("source_url"):
        lines.extend([f"**Source:** {data['source_url']}", ""])

    lines.append("## Post")
    lines.append("")
    if post_text:
        for paragraph in post_text.splitlines():
            paragraph = paragraph.strip()
            if paragraph:
                lines.append(markdown_escape(paragraph))
                lines.append("")
    else:
        lines.append("_No post text captured._")
        lines.append("")

    return lines


def render_markdown(data):
    lines = render_post_header(data)
    comments = sort_comments(list(data.get("comments", [])))

    lines.append("## Comments")
    lines.append("")
    if not comments:
        lines.append("_No comments captured._")
        return "\n".join(lines).rstrip() + "\n"

    for index, comment in enumerate(comments, start=1):
        lines.append(f"### {index}. {mention(comment.get('author'))}")
        lines.append("")
        children_by_parent = build_reply_tree(comment)
        lines.extend(render_comment_item(comment, children_by_parent))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def convert_json_to_markdown(input_path, output_path=None):
    input_path = Path(input_path)
    with input_path.open(encoding="utf-8") as source:
        data = json.load(source)

    markdown = render_markdown(data)
    if output_path is None:
        output_path = input_path.with_suffix(".md")
    output_path = Path(output_path)
    output_path.write_text(markdown, encoding="utf-8")
    return output_path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Convert a scraped Facebook post JSON export into nested Markdown."
    )
    parser.add_argument("input", help="Path to a scraped post JSON file.")
    parser.add_argument(
        "-o",
        "--output",
        help="Path for the generated Markdown file. Defaults to input path with .md suffix.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    output_path = convert_json_to_markdown(args.input, args.output)
    print(f"Saved Markdown to {output_path}")


if __name__ == "__main__":
    main()
