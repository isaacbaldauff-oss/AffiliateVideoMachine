# Deployment and Production Setup

This app can run locally for product setup, script generation, product asset prep, and video rendering. TikTok connection and app review require a public HTTPS deployment, so the production path is GitHub plus Streamlit Community Cloud or another HTTPS host.

## 1. Put the project on GitHub

1. Create a new private GitHub repository named `AffiliateVideoMachine`.
2. From the project folder, initialize Git if needed.
3. Commit the code.
4. Push the current branch to GitHub.

Do not commit `.streamlit/secrets.toml`, local database files, logs, generated project folders, exports, or real API keys.

## 2. Deploy to Streamlit Community Cloud

1. Open Streamlit Community Cloud.
2. Choose the GitHub repo and branch.
3. Set the main file path to `app/main.py`.
4. Deploy the app.
5. Copy the final app URL, for example `https://affiliatevideomachine.streamlit.app`.

This deployed URL is the value you use for TikTok Login Kit redirect URI. Use the root app URL without query parameters.

## 3. Add Streamlit secrets

In the Streamlit Cloud app settings, add secrets like this:

```toml
REPLICATE_API_TOKEN = "your_replicate_token"
TIKTOK_CLIENT_KEY = "your_tiktok_client_key"
TIKTOK_CLIENT_SECRET = "your_tiktok_client_secret"
TIKTOK_REDIRECT_URI = "https://affiliatevideomachine.streamlit.app"
```

For local testing, copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill in values. Keep that real secrets file private.

## 4. Configure Replicate

1. Create or log into your Replicate account.
2. Create an API token.
3. Add it as `REPLICATE_API_TOKEN` in Streamlit secrets or your local environment.
4. In the app, open Export Queue and run the autonomous media pipeline.

Replicate creates the actual generated presenter video from product reference images and the generated ad prompt. The local fallback renderer only creates an edited MP4 from images and captions.

## 5. Configure TikTok Developer

1. Create the TikTok app as type `Other`.
2. Add Login Kit.
3. Add the exact deployed Streamlit URL as the redirect URI.
4. Add Content Posting API.
5. Request these scopes:
   - `user.info.basic`
   - `video.upload`
   - `video.publish`
6. Submit for review with a demo showing Connect, generated video selection, caption/disclosure review, upload, and status tracking.

TikTok requires HTTPS redirect URIs for web Login Kit. The redirect URI must be static, absolute, and registered in the app configuration.

## 6. First working workflow

1. Add a TikTok Shop or affiliate product URL on Products.
2. Generate scripts.
3. Add the best script to Export Queue.
4. Run the autonomous media pipeline.
5. Review the generated MP4.
6. Open TikTok, then Connect.
7. Authorize the account. TikTok redirects back to the deployed dashboard with a code.
8. Save the TikTok account.
9. Query creator info.
10. Publish as inbox draft first.
11. After review approval, test direct post using `SELF_ONLY`.
12. Move to broader privacy only when TikTok allows it.

## Current limitations

- Streamlit Community Cloud storage is not durable enough for a serious production media archive. Use it for MVP review and testing, then move database and media storage to durable services.
- TikTok public Content Posting API uploads videos and creates drafts/direct posts. It does not provide a universal public API field for attaching a TikTok Shop affiliate product card to a post.
- Full zero-touch public posting depends on TikTok approval, connected creator consent, privacy rules returned by TikTok, and commercial disclosure requirements.

Official references:

- TikTok Login Kit for Web: https://developers.tiktok.com/doc/login-kit-web
- TikTok access token management: https://developers.tiktok.com/doc/login-kit-manage-user-access-tokens
- TikTok Content Posting API: https://developers.tiktok.com/products/content-posting-api
- TikTok Direct Post reference: https://developers.tiktok.com/doc/content-posting-api-reference-direct-post
