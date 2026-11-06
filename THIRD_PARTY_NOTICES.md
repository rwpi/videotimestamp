# Third-Party Notices

VTS is licensed under the GNU General Public License v3.0. See [LICENSE](LICENSE).
The application bundle carries the components below, each under its own license.

| Component | License | Source |
| --- | --- | --- |
| FFmpeg (static builds by Martin Riedl) | GPL v3 (built with `--enable-gpl --enable-version3`) | <https://ffmpeg.martin-riedl.de/> and <https://ffmpeg.org/download.html> |
| ExifTool | Artistic License or GPL | <https://exiftool.org/> |
| Python (python-build-standalone) | Python Software Foundation License | <https://www.python.org/> and <https://github.com/astral-sh/python-build-standalone> |
| PyQt5 | GPL v3 | <https://www.riverbankcomputing.com/software/pyqt/> |
| Qt 5 | LGPL v3 | <https://www.qt.io/> |
| OpenCV | Apache License 2.0 | <https://opencv.org/> |
| NumPy | BSD 3-Clause | <https://numpy.org/> |
| PyInstaller bootloader | GPL v2 with a bootloader exception | <https://pyinstaller.org/> |

The exact FFmpeg build configuration is printed by the bundled tool:

```sh
/Applications/VTS.app/Contents/Resources/engine-tools/ffmpeg -version
```
