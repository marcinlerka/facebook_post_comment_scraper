import requests
import json
import time
import os
import base64
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

GRAPHQL = "https://www.facebook.com/api/graphql/"
PROFILE_TIMELINE_DOC_ID = "25430544756617998"

# Base headers for all requests
BASE_HEADERS = {
    "user-agent": "Mozilla/5.0",
    "content-type": "application/x-www-form-urlencoded"
}

# Get proxy configuration
PROXY = os.getenv('PROXY')
PROXIES = {'http': PROXY, 'https': PROXY} if PROXY else None

# FB_DTSG token (set by UI when provided)
FB_DTSG = ""

if PROXY:
    print(f"Using proxy: {PROXY}")


def created_time_iso(created_time):
    if created_time is None:
        return None
    return datetime.fromtimestamp(created_time, timezone.utc).isoformat()


def extract_legacy_comment_id(comment_id):
    if not comment_id:
        return None

    try:
        decoded = base64.b64decode(comment_id).decode("utf-8")
    except Exception:
        return None

    _, _, legacy_id = decoded.rpartition("_")
    return legacy_id or None

# ========= RETRY HELPER =========
def retry_request(url, headers, data, proxies, cookies=None, max_retries=5):
    """Make a POST request with retry logic"""
    global PROXIES
    from proxy_utils import rotate_static_proxy, is_proxy_infra_error, is_ip_blocked

    for attempt in range(1, max_retries + 1):
        try:
            r = requests.post(url, headers=headers, data=data, proxies=proxies, cookies=cookies, timeout=30)
            if r.status_code == 200:
                return r
            if is_proxy_infra_error(status_code=r.status_code):
                print(f"  🚫 Attempt {attempt}/{max_retries}: Proxy auth failed (HTTP {r.status_code}) — rotating static proxy...")
                new_p = rotate_static_proxy()
                if new_p:
                    proxies = new_p
                    PROXIES = new_p
            elif is_ip_blocked(status_code=r.status_code, response_text=r.text):
                print(f"  🛑 Attempt {attempt}/{max_retries}: Facebook blocked this IP (HTTP {r.status_code}) — rotating static proxy...")
                new_p = rotate_static_proxy()
                if new_p:
                    proxies = new_p
                    PROXIES = new_p
            else:
                print(f"  ⚠️ Attempt {attempt}/{max_retries}: Status {r.status_code}")
        except requests.exceptions.ProxyError as e:
            print(f"  🚫 Attempt {attempt}/{max_retries}: Proxy unreachable — rotating static proxy...")
            new_p = rotate_static_proxy()
            if new_p:
                proxies = new_p
                PROXIES = new_p
        except Exception as e:
            if is_proxy_infra_error(exc=e):
                print(f"  🚫 Attempt {attempt}/{max_retries}: Proxy connection error — rotating static proxy...")
                new_p = rotate_static_proxy()
                if new_p:
                    proxies = new_p
                    PROXIES = new_p
            else:
                print(f"  ⚠️ Attempt {attempt}/{max_retries}: {str(e)}")

        if attempt < max_retries:
            wait_time = attempt * 2
            print(f"  ⏳ Retrying in {wait_time} seconds...")
            time.sleep(wait_time)

    raise Exception(f"Failed after {max_retries} attempts")

# ===== PAYLOADS =====

def comments_payload(feedback_id, cursor=None, cookies=None):
    # Extract user ID from cookies if available
    user_id = "0"
    if cookies and "c_user" in cookies:
        user_id = cookies["c_user"]
    
    return {
        "av": user_id,
        "__user": user_id,
        "__a": "1",
        "fb_dtsg": FB_DTSG if FB_DTSG else "",
        "doc_id": "25550760954572974",
        "variables": json.dumps({
            "commentsAfterCount": -1,
            "commentsAfterCursor": cursor,
            "commentsIntentToken": "REVERSE_CHRONOLOGICAL_UNFILTERED_INTENT_V1",
            "feedLocation": "DEDICATED_COMMENTING_SURFACE",
            "focusCommentID": None,
            "scale": 2,
            "useDefaultActor": False,
            "id": feedback_id
        })
    }


def replies_payload(comment_feedback_id, expansion_token, cookies=None, cursor=None):
    # Extract user ID from cookies if available
    user_id = "0"
    if cookies and "c_user" in cookies:
        user_id = cookies["c_user"]
    
    return {
        "av": user_id,
        "__user": user_id,
        "__a": "1",
        "fb_dtsg": FB_DTSG if FB_DTSG else "",
        "doc_id": "26570577339199586",
        "variables": json.dumps({
            "clientKey": None,
            "expansionToken": expansion_token,
            "feedLocation": "POST_PERMALINK_DIALOG",
            "focusCommentID": None,
            "repliesAfterCursor": cursor,
            "scale": 2,
            "useDefaultActor": False,
            "id": comment_feedback_id
        })
    }


def profile_posts_payload(profile_id, cursor=None, cookies=None, count=3):
    user_id = "0"
    if cookies and "c_user" in cookies:
        user_id = cookies["c_user"]

    return {
        "av": user_id,
        "__user": user_id,
        "__a": "1",
        "fb_dtsg": FB_DTSG if FB_DTSG else "",
        "doc_id": PROFILE_TIMELINE_DOC_ID,
        "variables": json.dumps({
            "count": count,
            "cursor": cursor,
            "id": profile_id,
            "feedLocation": "TIMELINE",
            "renderLocation": "timeline",
            "scale": 2,
            "useDefaultActor": False
        })
    }

# ===== FETCH COMMENTS =====
import json

def fb_json(response_text):
    """
    Facebook GraphQL sometimes returns:
    for (;;);
    {json}
    {json}

    This extracts the first valid JSON object safely.
    """
    text = response_text.strip()

    # Remove for (;;);
    if text.startswith("for (;;);"):
        text = text[len("for (;;);"):]

    # Keep only first JSON object
    first = text.split("\n")[0].strip()

    return json.loads(first)


def extract_data_blocks(raw_text):
    blocks = []
    i = 0
    n = len(raw_text)

    while True:
        idx = raw_text.find('"data"', i)
        if idx == -1:
            break

        brace_start = raw_text.find('{', idx)
        if brace_start == -1:
            break

        depth = 0
        for j in range(brace_start, n):
            if raw_text[j] == '{':
                depth += 1
            elif raw_text[j] == '}':
                depth -= 1
                if depth == 0:
                    block_text = raw_text[brace_start:j + 1]
                    try:
                        blocks.append(json.loads(block_text))
                    except Exception:
                        pass
                    i = j + 1
                    break
        else:
            break

    return blocks


def extract_story_nodes(blocks):
    story_nodes = []
    timeline_block = None
    page_info = None

    for block in blocks:
        if not isinstance(block, dict):
            continue

        if "page_info" in block:
            page_info = block.get("page_info")
            continue

        node = block.get("node", {})
        node_typename = node.get("__typename")

        if "timeline_list_feed_units" in node:
            timeline_block = block
            edges = node["timeline_list_feed_units"].get("edges", [])
            for edge in edges:
                edge_node = edge.get("node")
                if edge_node and edge_node.get("__typename") == "Story":
                    story_nodes.append(edge_node)
        elif node_typename == "Story":
            story_nodes.append(node)

    return story_nodes, timeline_block, page_info


def story_text(node):
    return (
        node.get("comet_sections", {})
        .get("content", {})
        .get("story", {})
        .get("message", {})
        .get("text")
    )


def story_created_time(node):
    timestamp_story = (
        node.get("comet_sections", {})
        .get("timestamp", {})
        .get("story", {})
    )
    metadata = (
        node.get("comet_sections", {})
        .get("context_layout", {})
        .get("story", {})
        .get("comet_sections", {})
        .get("metadata", [])
    )
    context_timestamp_story = (
        metadata[0].get("story", {})
        if metadata
        else {}
    )

    return timestamp_story.get("creation_time") or context_timestamp_story.get("creation_time")


def story_attachments(node):
    attachments = []

    for attachment in node.get("attachments") or []:
        media = attachment.get("media") or {}
        styled_media = (
            attachment.get("styles", {})
            .get("attachment", {})
            .get("media", {})
        )
        media = {**media, **styled_media}

        file_url = (
            media.get("photo_image", {}).get("uri")
            or media.get("image", {}).get("uri")
            or media.get("viewer_image", {}).get("uri")
        )
        media_id = media.get("id")

        if not file_url and not media_id:
            continue

        attachments.append({
            "media_id": media_id,
            "type": media.get("__typename"),
            "url": media.get("url"),
            "file_url": file_url,
            "width": media.get("photo_image", {}).get("width"),
            "height": media.get("photo_image", {}).get("height"),
            "accessibility_caption": media.get("accessibility_caption"),
        })

    return attachments


def fetch_post_details_from_profile(
    profile_id,
    post_id,
    cookies=None,
    max_pages=50,
    page_size=3,
    sleep_seconds=0.25,
):
    cursor = None
    page_num = 0

    while page_num < max_pages:
        page_num += 1
        headers = {**BASE_HEADERS, "x-fb-friendly-name": "ProfileCometTimelineFeedRefetchQuery"}
        r = retry_request(
            GRAPHQL,
            headers,
            profile_posts_payload(profile_id, cursor, cookies, count=page_size),
            PROXIES,
            cookies=cookies
        )

        blocks = extract_data_blocks(r.text)
        story_nodes, timeline_block, page_info = extract_story_nodes(blocks)

        for node in story_nodes:
            if str(node.get("post_id")) == str(post_id):
                created_time = story_created_time(node)
                return {
                    "text": story_text(node),
                    "created_time": created_time,
                    "created_time_iso": created_time_iso(created_time),
                    "attachments": story_attachments(node),
                    "source_url": node.get("permalink_url"),
                }

        page_info = page_info or {}
        if timeline_block:
            page_info = (
                timeline_block.get("node", {})
                .get("timeline_list_feed_units", {})
                .get("page_info", {})
            ) or page_info

        cursor = page_info.get("end_cursor")
        if not cursor:
            break

        if sleep_seconds:
            time.sleep(sleep_seconds)

    return {}


def fetch_post_text_from_profile(
    profile_id,
    post_id,
    cookies=None,
    max_pages=50,
    page_size=3,
    sleep_seconds=0.25,
):
    details = fetch_post_details_from_profile(
        profile_id,
        post_id,
        cookies=cookies,
        max_pages=max_pages,
        page_size=page_size,
        sleep_seconds=sleep_seconds,
    )
    return details.get("text")


def fetch_comments(feedback_id, cookies=None):
    results = []
    cursor = None
    response_count = 0
    post_info = None  # Store parent post info from first response

    while True:
        headers = {**BASE_HEADERS, "x-fb-friendly-name": "CommentsListComponentsPaginationQuery"}
        r = retry_request(
            GRAPHQL,
            headers,
            comments_payload(feedback_id, cursor, cookies),
            PROXIES,
            cookies=cookies
        )
        j = fb_json(r.text)
        
        # Save each JSON response for inspection
        response_count += 1
        # with open(f"response_{response_count}.json", "w", encoding="utf-8") as f:
        #     json.dump(j, f, ensure_ascii=False, indent=2)
        # print(f"💾 Saved response_{response_count}.json")
        
        comments_block = (
            j.get("data", {})
             .get("node", {})
             .get("comment_rendering_instance_for_feed_location", {})
             .get("comments", {})
        )

        edges = comments_block.get("edges", [])
        if not edges:
            break

        for e in edges:
            n = e["node"]
            fb = n["feedback"]
            author = n.get("author") or {}

            # Extract parent_post_story info from first response
            if response_count == 1 and post_info is None:
                parent_post_story = n.get("parent_post_story", {})
                
                if parent_post_story:
                    parent_feedback = n.get("parent_feedback", {})
                    owning_profile = parent_feedback.get("owning_profile", {})
                    post_id = parent_feedback.get("share_fbid")
                    post_info = {
                        "post_story_id": parent_post_story.get("id"),
                        "media_id": None,
                        "post_id": post_id,
                        "author": owning_profile.get("name"),
                        "author_id": owning_profile.get("id"),
                        "text": None,
                        "created_time": None,
                        "created_time_iso": None,
                        "attachments": [],
                    }
                    
                    # Extract first media ID
                    attachments = parent_post_story.get("attachments", [])
                    for attachment in attachments:
                        media = attachment.get("media", {})
                        if media and media.get("id"):
                            post_info["media_id"] = media.get("id")
                            break  # Only get first one

                    if post_info["author_id"] and post_info["post_id"]:
                        post_details = fetch_post_details_from_profile(
                            post_info["author_id"],
                            post_info["post_id"],
                            cookies=cookies
                        )
                        post_info.update({
                            key: value
                            for key, value in post_details.items()
                            if value not in (None, "", [])
                        })

                        if post_info["attachments"] and not post_info["media_id"]:
                            post_info["media_id"] = post_info["attachments"][0].get("media_id")
                    
                    print(f"📎 Extracted post info: {post_info}")

            # Extract reaction count
            reactors = fb.get("reactors", {})
            total_reactions = reactors.get("count_reduced", "0")

            results.append({
                "comment_id": n.get("legacy_fbid"),
                "author": author.get("name"),
                "author_id": author.get("id"),
                "text": (n.get("body") or {}).get("text", ""),
                "created_time": n.get("created_time"),
                "created_time_iso": created_time_iso(n.get("created_time")),
                "reaction_count": total_reactions,
                "_feedback_id": fb["id"],  # Internal use only (for fetching replies)
                "_expansion_token": fb["expansion_info"]["expansion_token"]  # Internal use only
            })

        cursor = comments_block.get("page_info", {}).get("end_cursor")
        #break
        if not cursor:
            break

        #time.sleep(0.4)

    return results, post_info

# ===== FETCH REPLIES =====

def fetch_replies(comment, cookies=None):
    replies = []
    cursor = None
    seen_cursors = set()
    seen_replies = set()

    while True:
        headers = {**BASE_HEADERS, "x-fb-friendly-name": "Depth1CommentsListPaginationQuery"}
        r = retry_request(
            GRAPHQL,
            headers,
            replies_payload(comment["_feedback_id"], comment["_expansion_token"], cookies, cursor),
            PROXIES,
            cookies=cookies
        )

        j = fb_json(r.text)

        replies_connection = (
            j.get("data", {})
             .get("node", {})
             .get("replies_connection", {})
        )

        edges = replies_connection.get("edges", [])

        for e in edges:
            n = e["node"]
            fb = n.get("feedback", {})
            author = n.get("author") or {}
            direct_parent = n.get("comment_direct_parent") or {}
            direct_parent_author = direct_parent.get("author") or {}

            # Extract reaction count
            reactors = fb.get("reactors", {})
            total_reactions = reactors.get("count_reduced", "0")

            reply_text = (n.get("body") or {}).get("text", "")
            reply_key = n.get("legacy_fbid") or fb.get("id") or reply_text
            if reply_key in seen_replies:
                continue
            seen_replies.add(reply_key)

            replies.append({
                "reply_id": n.get("legacy_fbid"),
                "author": author.get("name"),
                "author_id": author.get("id"),
                "text": reply_text,
                "created_time": n.get("created_time"),
                "created_time_iso": created_time_iso(n.get("created_time")),
                "parent_comment_id": direct_parent.get("id"),
                "parent_comment_legacy_id": extract_legacy_comment_id(direct_parent.get("id")),
                "parent_author": direct_parent_author.get("name"),
                "parent_author_id": direct_parent_author.get("id"),
                "reaction_count": total_reactions
            })

        page_info = replies_connection.get("page_info", {}) or {}
        cursor = page_info.get("end_cursor")
        if not page_info.get("has_next_page") or not cursor or cursor in seen_cursors:
            break
        seen_cursors.add(cursor)

    return replies

# ===== RUN =====

if __name__ == "__main__":
    POST_FEEDBACK_ID = "ZmVlZGJhY2s6MTg3NDE2NTYxMzI0NjAwMw=="
    POST_ID = "1420269302790428"  # The actual post ID

    all_data = []

    comments, post_info = fetch_comments(POST_FEEDBACK_ID)
    
    # Add post info to the output
    output = {
        "post_info": post_info,
        "comments": []
    }

    for c in comments:
        # print(f"\n🗨️ {c['author']}: {c['text']}")
        c["replies"] = fetch_replies(c)

        # for r in c["replies"]:
        #     print(f"   ↳ {r['author']}: {r['text']}")

        output["comments"].append(c)

    # Create directory for this post
    os.makedirs(f"simple_post/{POST_ID}", exist_ok=True)
    
    # Save as {post_id}.json
    output_file = f"simple_post/{POST_ID}/{POST_ID}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"💬 Saved to {output_file}")
