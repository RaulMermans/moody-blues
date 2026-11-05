# Submission pack

| Asset | Location | State |
|---|---|---|
| Copy | [copy.md](copy.md) | Draft; limits unconfirmed |
| Claim sources | [claims.md](claims.md) | Done |
| Video script and shot list | [video-script.md](video-script.md) | Done |
| Video | `.artifacts/submission/video/moody-blues-demo.mp4`, 4:30, 1080p, 28.3 MB | Built from the public site |
| Captions | `.artifacts/submission/video/moody-blues-demo.srt` | Done; also burned in |
| Deck | `.artifacts/submission/deck/moody-blues-deck.pdf`, 9 pages | Built from the public site |
| Cover image | `.artifacts/submission/deck/slide-title.png` | Candidate |
| Screenshots | [screenshots/](screenshots/) | From the public site |

`.artifacts/` is git-ignored, so the video and deck are on this machine only.

## Rebuilding

Run from the repository root. Nothing here uploads anything.

```bash
S=.artifacts/submission
# The live view needs MOODY_HOSTED_OPERATOR_TOKEN in the environment.
node docs/submission/tools/capture.mjs https://45-63-119-197.sslip.io $S/shots
# Recreate shots/reality-crop.png: crop 1680x1044 from x=120, y=anchors.reality.table-20.
node docs/submission/tools/build_deck.mjs $S/shots $S/deck
python3 docs/submission/tools/build_video.py $S/shots $S/deck $S/video
```

## Remaining owner steps

1. Rotate the account key ([checklist](../security/key-rotation.md)).
2. Sign in to lablab, check limits and tags against [copy.md](copy.md), attach the video and deck, and submit
   before 2026-11-08 22:00 UTC.
