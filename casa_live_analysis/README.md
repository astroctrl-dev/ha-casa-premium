# CASA Live Analysis – Home Assistant app (beta)

Feature #14: read-only diagnostics, live view, 15-minute recording, CSV.

## Install from HA app repository

1. Home Assistant **Settings → Apps → App store → ⋮ → Repositories**.
2. Add: `https://github.com/astroctrl-dev/ha-casa-premium`
3. Find **CASA Live Analysis**, install, start, then **Open Web UI**.
4. No long-lived access token is needed in the UI. The app uses the Home Assistant Supervisor token internally, with `homeassistant_api: true`.

The app is packaged in `casa_live_analysis/`, with `repository.yaml` at the repository root. It runs a separate HTTP UI behind Home Assistant Ingress, and polls the existing `casa_premium/diagnostics` WebSocket command. **No second connection to the PUSR gateway and no device writes.**

## Scope and caveats

- Needs CASA Premium v1.3.0b1 (or newer compatible beta) installed and its diagnostics WebSocket API registered.
- Live TCP connectivity, received byte count, valid telegrams, decoded frames, CRC errors, event stream.
- 15-minute capture and CSV export in the browser. **Recording stops if the page is closed or refreshed**; this first beta is not a background recorder.
- Events are observed HA timestamps, not physical RS-485 bit timestamps.
- Current diagnostics API does not expose raw telegram payload bytes; CSV contains the event JSON only.
- The app retains at most 12,000 events in RAM; HA integration has a separate 4,096-event buffer. Buffer loss is reported.
- The app uses a Python Alpine base image; installing requires container image download and build access.
- No HA-QA installation or runtime test has been performed. Check app log, API auth, live events and CSV on HA-QA before marking verified.
- Existing CASA Premium v1.2.0 production installation is unchanged.

## Troubleshooting

If the app opens but shows **Venter på diagnostikk-API**, open the app's Log tab. Look for `auth_invalid`, `not_found`, or connection errors. Check that the integration beta is loaded, and that the add-on has Supervisor API access. Do not paste tokens into logs or issues.

## Rollback

Stop/uninstall **CASA Live Analysis** in Settings → Apps. The integration and CASA gateway are unaffected.
