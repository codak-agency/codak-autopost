# CODAK AutoPost

AI-assisted daily social content generation and publishing for CODAK Agency.

## What it does

1. Uses Gemini to write original Egyptian Arabic marketing copy.
2. Generates a square branded visual and renders the Arabic headline with CODAK identity colors.
3. Reads active channels from BulkPublish and skips disconnected, expired, or unavailable channels.
4. Publishes an image post only when publishing has been explicitly enabled.
5. Records successful publication dates and recent topics to reduce duplicate posts.

## Required GitHub Actions secrets

- `GEMINI_API_KEY`
- `BULKPUBLISH_API_KEY`

Never place either key in source files, commits, screenshots, or chat messages.

## Optional repository variables

- `GEMINI_TEXT_MODEL` (default: `gemini-2.5-flash`)
- `GEMINI_IMAGE_MODEL` (default: `gemini-nano-banana-2.1`)
- `PUBLISH_ENABLED` (default: unset / disabled)

## Safe first test

1. Merge the reviewed pull request into `main`.
2. Open **Actions → CODAK Daily Post → Run workflow**.
3. Leave **Publish this generated post now** unchecked.
4. Open the run artifact named `codak-post-...` and inspect `post.png` and `post.json`.

The preview run calls Gemini and may incur image-generation usage, but it does not upload media to BulkPublish or publish to social channels.

## Enable scheduled publishing later

Only after approving the generated preview and confirming the BulkPublish API permissions and connected channel capabilities:

1. Open **Settings → Secrets and variables → Actions → Variables**.
2. Add repository variable `PUBLISH_ENABLED` with value `true`.
3. The daily workflow runs at 18:00 Africa/Cairo time, including seasonal clock changes.
4. To pause scheduled generation and publishing, remove the variable or change its value to anything other than `true`.

Manual runs remain preview-only unless the publish checkbox is explicitly checked.

## Current media scope

- Facebook, Instagram, LinkedIn and TikTok are eligible for image-post attempts, subject to the connected account, platform permissions, and plan.
- YouTube is deliberately excluded because this workflow generates a static image, not a video.
- TikTok photo-slideshow support must be confirmed for the connected account before relying on it.

## Important

- A successful API response is not a guarantee that every social platform accepted the post; inspect BulkPublish post status after the first live test.
- GitHub Actions cron schedules use UTC and may start a little later than the exact minute.
- Gemini image generation is a paid-tier feature for the configured model. Review current pricing and quotas before enabling daily runs.
