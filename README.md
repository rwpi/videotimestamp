# Video Timestamp For Private Investigators (VTS)

# **[*Download VTS 2.0 for macOS*](https://github.com/rwpi/videotimestamp/releases/latest)**

VTS prepares camcorder and covert-camera footage for investigators. It adds a visible
date and time to your video using the recording time stored in each file, then
gives you the everyday tools for getting that footage ready to deliver.

Version 2.0 is a new native Mac app. Open it from the menu bar, or right-click videos
in Finder and run a tool directly.

## Tools

- **Import Camera Media:** copy footage for a chosen date from a camera card, skipping
  clips you already imported
- **Timestamp Videos:** burn the recording date and time into each clip, with
  corrections for daylight saving and misconfigured camera clocks
- **Remove Audio:** make video-only copies without re-encoding
- **Trim Clips:** set the start and end of each clip with frame-level controls
- **Merge Clips:** join clips in chronological order, with optional compression
- **Transcode Videos:** convert quality and resolution, with an optional file-size limit
- **Calculate Runtime:** count clips and total their running time
- **Order Clips:** rename LawMate clips by recording time and number clips in order

VTS never edits a camera card. Footage has to be imported first, and originals are
kept in an `originals` folder beside your working files.

## Supported cameras

VTS reads AVCHD (`.MTS`) and MP4 footage from Sony and Panasonic camcorders, and handles
LawMate covert cameras and VIOFO dash cams. If your camera isn't supported, please open
an issue with the make, model and a short sample clip.

## Install

**Requires a Mac with Apple silicon running macOS 27 or later.**

1. Download `VTS_macOS_ARM.pkg` from the [latest release](https://github.com/rwpi/videotimestamp/releases/latest).
2. Open it and follow the installer. An earlier VTS is replaced, and your settings carry over.
3. Open VTS from Applications. To add its tools to Finder's right-click menu, open
   Settings and choose Finder Integration.

Using an older Mac, or Windows? Version 1.1.2 is still available on the
[releases page](https://github.com/rwpi/videotimestamp/releases/tag/VTS-1.1.2).

## Build from source

See [docs/building.md](docs/building.md).

## License

Created and maintained by Robert Webber. Licensed under the GNU General Public License
v3.0; see [LICENSE](LICENSE). Bundled components keep their own licenses; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
