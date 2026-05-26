# TikTok Review Notes

Use this as a starting point when filling out TikTok Developer review forms. Adjust anything that is specific to your business, website, or account.

## App name

AffiliateVideoMachine

## App purpose

AffiliateVideoMachine helps a creator generate and review TikTok Shop affiliate product videos. The app imports TikTok Shop product metadata and imagery, generates compliant video ad scripts, creates AI-assisted presenter video drafts through Replicate, adds affiliate and AI content disclosures, and lets the authorized creator upload the reviewed MP4 to TikTok as an inbox draft. The creator then attaches the TikTok Shop product link inside TikTok before posting.

## User flow

1. The creator pastes a TikTok Shop product URL.
2. The app imports product metadata/images, scores the product, generates script angles, and queues a draft.
3. The creator runs the AI media pipeline to generate a vertical MP4.
4. The creator reviews the video, caption, affiliate disclosure, commercial disclosure, and AI-generated content disclosure.
5. The creator connects TikTok with Login Kit.
6. The creator uploads the reviewed MP4 to TikTok as an inbox draft.
7. The creator opens TikTok, attaches the TikTok Shop product through Add Link -> Products, and posts from TikTok.
8. The app displays TikTok upload status and tracks product-box workflow status.

## Requested scopes

- `user.info.basic`: used to identify the connected creator account and display basic account context.
- `video.upload`: used to send reviewed TikTok Shop affiliate videos to the creator's TikTok inbox as drafts.
- `video.publish`: optional future scope for direct posts that do not need product-box attachment. The TikTok Shop affiliate workflow prioritizes inbox draft upload because the creator attaches the product box inside TikTok.

## Data handling

The app stores TikTok access and refresh tokens server-side in the app database. Tokens are not shown to the user after connection. Client keys, client secrets, and Replicate keys are stored in environment variables or Streamlit secrets. The app does not sell TikTok user data. Product metadata, generated scripts, generated videos, and publish status records are used only to operate the creator's affiliate video workflow.

## Publishing controls

The app does not publish automatically without creator action. Before sending to TikTok, the creator must review the rendered video, review the caption, and check an explicit consent box. For TikTok Shop affiliate videos, the app uploads an inbox draft; final posting and product-box attachment happen inside TikTok.

## Commercial and AI disclosure

The app includes affiliate disclosure text in generated captions. The TikTok publish flow exposes branded content, own brand, and AI-generated content toggles. The creator must review these disclosures before upload.

## Compliance controls

The app checks generated text for risky terms such as medical claims, cure claims, guaranteed claims, before-and-after claims, cheapest claims, official claims, and FDA-approved claims. Items with risky copy are flagged for review before publishing.

## Redirect URI

Use the deployed HTTPS dashboard URL exactly as registered in Login Kit, for example:

```text
https://affiliatevideomachine.streamlit.app
```

Do not use `localhost` for TikTok review. Localhost is only for development.

## Demo checklist

- Show the deployed HTTPS app.
- Show Login Kit redirect URI matching the app secrets value.
- Show product entry.
- Show script generation.
- Show AI video generation or an already generated MP4.
- Show caption and disclosures.
- Show TikTok Connect flow.
- Show creator info query.
- Show upload to inbox draft.
- Show that the creator attaches the TikTok Shop product box in TikTok after draft upload.
- Show status refresh.
