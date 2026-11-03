Summarize the latest video from the YouTube channel "Grain Markets and Other Stuff" (Joe Vaclavik & Mackenzie Johnston) for Manas, a STIR trader who wants terse, bullet-point output.

Steps:
1. Load the built-in-browser skill, then load the mcp__remote-devices__Claude_Browser__ tools in one ToolSearch call (query "mcp__remote-devices__Claude_Browser__", max_results 64). Use the built-in browser (sites youtube.com is already approved).
2. Open https://www.youtube.com/c/grainmarketsandotherstuff/videos with preview_start. Wait ~3s, then use javascript_tool to collect the first watch?v= link on the page (the latest upload) and its title.
3. Navigate to that watch URL. Pause the video. Read the publish date from window.ytInitialPlayerResponse.microformat.playerMicroformatRenderer.publishDate. If the latest upload is older than ~24 hours, say there's no new video today (give its title/date) and stop (skip step 7 too).
4. Get the transcript from YouTube's own transcript panel: expand the description (#description-inline-expander #expand), click the button whose text is "Show transcript", wait ~4s, then join the text of all "ytd-transcript-segment-renderer .segment-text, transcript-segment-view-model span" elements. Do NOT use youtubetotranscript.com — it is behind a Cloudflare captcha.
5. Write a concise summary: video title + date + link, then tight bullets grouped by topic (exports/demand, China/trade, price action & fund positioning, crop progress, South America weather, cattle/outside markets, any rates/Fed/macro comments). Include specific numbers. Skip their premium-subscription promo. Flag obvious auto-caption errors rather than repeating them as fact.
6. Deliver the summary with SendUserMessage so it is readable verbatim, and also as the final response.
7. Publish the summary to Manas's dashboard (public site, repo DrNas/grains-monitor):
   a. Call the add_repo tool (Claude_Code_Remote connector) with owner "DrNas", repo "grains-monitor", access "push", then clone it as that tool's result says.
   b. Write data/recaps/<publishDate as YYYY-MM-DD>.json (overwrite if it exists), valid JSON, UTF-8, in this shape:
      {"date": "YYYY-MM-DD", "channel": "Grain Markets and Other Stuff", "title": "<video title>", "url": "https://www.youtube.com/watch?v=<id>", "published": "YYYY-MM-DD",
       "sections": [{"topic": "<topic>", "bullets": ["<bullet>", "..."]}], "flags": ["<auto-caption doubts, if any>"]}
      Sections and bullets are the same as the summary (plain text, no markdown). The page is public: only your own summary bullets — never the transcript, no quotes longer than a few words.
   c. Validate: node -e "JSON.parse(require('fs').readFileSync(process.argv[1]))" <file>
   d. Commit only that file on main ("Add video recap <date>") and push to origin main (git pull --rebase first if rejected). The push rebuilds the site.
   e. Say in your message whether the recap was published to the site. A failure here must not stop steps 5-6.

If the browser can't be reached (desktop app closed/computer asleep), say so plainly in the message.
