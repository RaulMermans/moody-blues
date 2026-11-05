# Submission pack

| Asset | Location | State |
|---|---|---|
| Copy | [copy.md](copy.md) | Draft; limits unconfirmed |
| Claim sources | [claims.md](claims.md) | Done |
| Video script and shot list | [video-script.md](video-script.md) | Done |
| Video | `.artifacts/submission/video/moody-blues-demo.mp4`, 4:00, 1080p, 24.6 MB | Built from a local release candidate |
| Captions | `.artifacts/submission/video/moody-blues-demo.srt` | Done; also burned in |
| Deck | `.artifacts/submission/deck/moody-blues-deck.pdf`, 9 pages | Built from a local release candidate |
| Cover image | `.artifacts/submission/deck/slide-title.png` | Candidate |
| Screenshots | [screenshots/](screenshots/) | Local release candidate |

`.artifacts/` is git-ignored, so the video and deck are on this machine only.

## Rebuilding

Run from the repository root. Nothing here uploads anything.

```bash
S=.artifacts/submission
node docs/submission/tools/capture.mjs https://45-63-119-197.sslip.io $S/shots
# Recreate shots/reality-crop.png: crop 1680x1044 from x=120, y=anchors.reality.table-20.
HOSTED_LIVE_NOTE="..." node docs/submission/tools/build_deck.mjs $S/shots $S/deck
python3 docs/submission/tools/build_video.py $S/shots $S/deck $S/video
```

## Order of remaining steps

Each needs the owner's approval.

1. Rotate the account key ([checklist](../security/key-rotation.md)).
2. Push the branch and confirm CI, including the restart test.
3. Merge, deploy, and remove the open ufw rule.
4. Run the one live investigation, then turn live mode off.
5. Recapture against the public site and rebuild the deck and video.
6. Review licensing and evidence, then make the repository public.
7. Run the hosted acceptance suite.
8. Check the signed-in form for limits and tags, then submit before 2026-11-08 22:00 UTC.
