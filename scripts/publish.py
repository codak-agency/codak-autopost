from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
STATE_FILE = ROOT / "state" / "history.json"
API_BASE = os.getenv("BULKPUBLISH_API_BASE", "https://app.bulkpublish.com/api").rstrip("/")
TIMEZONE = os.getenv("TIMEZONE", "Africa/Cairo")

# YouTube is intentionally excluded: this workflow creates a single image post,
# while BulkPublish's YouTube publishing formats require a video or Short.
SUPPORTED_IMAGE_PLATFORMS = {"facebook", "instagram", "linkedin", "tiktok"}


def api_headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


def request_json(method: str, path: str, api_key: str, **kwargs) -> dict:
    response = requests.request(
        method, f"{API_BASE}{path}", headers=api_headers(api_key), timeout=90, **kwargs
    )
    if not response.ok:
        try:
            body = response.json()
            message = body.get("error", {}).get("message") or body.get("message") or str(body)
        except (ValueError, AttributeError):
            message = response.text[:700]
        raise RuntimeError(f"BulkPublish {method} {path} failed (HTTP {response.status_code}): {message}")
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"BulkPublish returned invalid JSON for {path}.") from exc


def read_state() -> dict:
    if not STATE_FILE.exists():
        return {"published_dates": [], "topics": [], "published_posts": []}
    value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    value.setdefault("published_dates", [])
    value.setdefault("topics", [])
    value.setdefault("published_posts", [])
    return value


def save_published_state(state: dict, post: dict, post_id: int, channels: list[dict]) -> None:
    date_key = post["date"]
    if date_key not in state["published_dates"]:
        state["published_dates"].append(date_key)
    state["topics"].append(post["topic"])
    state["topics"] = state["topics"][-60:]
    state["published_dates"] = state["published_dates"][-180:]
    state["published_posts"].append({
        "date": date_key,
        "post_id": post_id,
        "topic": post["topic"],
        "platforms": sorted({channel["platform"] for channel in channels}),
        "published_at": datetime.now(ZoneInfo(TIMEZONE)).isoformat(),
    })
    state["published_posts"] = state["published_posts"][-180:]
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    post_file, image_file = OUT / "post.json", OUT / "post.png"
    if not post_file.exists():
        raise RuntimeError("Missing out/post.json. Run scripts/generate.py first.")
    post = json.loads(post_file.read_text(encoding="utf-8"))
    if post.get("already_published"):
        print("Already published today; nothing to do.")
        return
    if not image_file.exists():
        raise RuntimeError("Missing out/post.png.")

    api_key = os.getenv("BULKPUBLISH_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing BULKPUBLISH_API_KEY repository secret.")

    channel_response = request_json("GET", "/channels", api_key, params={"active": "true"})
    all_channels = channel_response.get("channels", [])
    eligible = [
        channel for channel in all_channels
        if channel.get("platform") in SUPPORTED_IMAGE_PLATFORMS
        and channel.get("isActive") is True
        and channel.get("platformAvailable", True) is True
        and channel.get("needsReconnect") is not True
        and channel.get("tokenStatus") != "expired"
        and channel.get("id") is not None
    ]
    excluded = [
        channel for channel in all_channels
        if channel.get("platform") in SUPPORTED_IMAGE_PLATFORMS and channel not in eligible
    ]
    unsupported = sorted({
        channel.get("platform", "unknown")
        for channel in all_channels
        if channel.get("platform") not in SUPPORTED_IMAGE_PLATFORMS
    })

    print("Connected eligible channels:")
    for channel in eligible:
        print(f"- {channel.get('platform')}: {channel.get('accountName', 'connected')} (ID {channel['id']})")
    for channel in excluded:
        print(f"- Skipped {channel.get('platform')} channel {channel.get('accountName', '')}: inactive, unavailable, expired, or reconnect required.")
    if "youtube" in unsupported:
        print("- YouTube is connected but skipped: this workflow creates image posts, not videos.")
    if not eligible:
        raise RuntimeError("No eligible connected image-post channels found. Connect a supported channel in BulkPublish.")

    capabilities = channel_response.get("capabilities", {})
    if capabilities.get("canCreatePosts") is False or capabilities.get("canPublishPosts") is False:
        raise RuntimeError("The BulkPublish API key does not have permission to create and publish posts.")

    publish_enabled = os.getenv("PUBLISH_ENABLED", "false").strip().lower() == "true"
    if not publish_enabled:
        print("PREVIEW ONLY: PUBLISH_ENABLED is not true. No media upload or social post was created.")
        print(f"Preview is ready for {len(eligible)} channel(s); image: out/post.png")
        return

    state = read_state()
    if post["date"] in state.get("published_dates", []):
        print(f"CODAK already has a published post for {post['date']}; duplicate prevented.")
        return

    with image_file.open("rb") as image_handle:
        upload = requests.post(
            f"{API_BASE}/media",
            headers=api_headers(api_key),
            files={"file": ("codak-daily-post.png", image_handle, "image/png")},
            timeout=120,
        )
    if not upload.ok:
        try:
            message = upload.json().get("error", {}).get("message", upload.text[:500])
        except ValueError:
            message = upload.text[:500]
        raise RuntimeError(f"BulkPublish media upload failed (HTTP {upload.status_code}): {message}")
    media_id = upload.json().get("file", {}).get("id")
    if not media_id:
        raise RuntimeError("BulkPublish accepted the upload but did not return a media file ID.")

    channel_targets = [
        {"channelId": int(channel["id"]), "platform": channel["platform"]}
        for channel in eligible
    ]
    post_type_overrides, platform_specific = {}, {}
    for platform in {channel["platform"] for channel in eligible}:
        if platform == "instagram":
            post_type_overrides[platform] = "feed_photo"
            platform_specific[platform] = {"isAiGenerated": True}
        elif platform == "tiktok":
            post_type_overrides[platform] = "photo_slideshow"
            platform_specific[platform] = {"isAigc": True}
        else:
            post_type_overrides[platform] = "post"

    payload = {
        "content": post["caption"],
        "channels": channel_targets,
        "mediaFiles": [int(media_id)],
        "status": "draft",
        "postFormat": "post",
        "postTypeOverrides": post_type_overrides,
        "platformSpecific": platform_specific,
    }
    created = request_json("POST", "/posts", api_key, json=payload)
    created_post = created.get("post", created)
    post_id = created_post.get("id") if isinstance(created_post, dict) else None
    if not post_id:
        raise RuntimeError("BulkPublish created a post but returned no post ID; it was not published automatically.")

    request_json("POST", f"/posts/{int(post_id)}/publish", api_key)
    save_published_state(state, post, int(post_id), eligible)
    platforms = ", ".join(sorted({channel["platform"] for channel in eligible}))
    print(f"Published CODAK daily post {post_id} to: {platforms}")
    print("Publication history updated; workflow will commit the daily state.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"PUBLISH_FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
