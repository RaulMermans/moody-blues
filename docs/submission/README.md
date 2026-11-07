# Submission pack

| Asset | Location | State |
|---|---|---|
| Copy | [FINAL-SUBMISSION.md](FINAL-SUBMISSION.md), which supersedes [copy.md](copy.md) | Final; limits from the official guidelines |
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

The authoritative entry, with the checked form limits, is [FINAL-SUBMISSION.md](FINAL-SUBMISSION.md). Its "Submitting"
section lists the steps. The repository has been public since 2026-11-06.
