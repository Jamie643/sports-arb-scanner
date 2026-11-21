# Offline feed samples

Drop a raw captured JSON response into the matching file:

- `samples/betpawa/events.json`
- `samples/bet9ja/events.json`

Set the corresponding feed URL in `.env` to that file's absolute `file://` URI
(for example, `BETPAWA_FEED_URL=file:///absolute/path/to/repo/samples/betpawa/events.json`).
The scraper loads the JSON locally and passes it through the same provider
adapter used for HTTP feeds, so offline tests do not require a network request.

The provider-specific response formats are not assumed. If the capture is not
already in the normalized `matches` format documented in the root README, map
it in the provider's `parse_payload` native parser before expecting scanner
records.
