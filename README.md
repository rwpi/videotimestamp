# Private Investigator Video Timestamp (VTS)

## Installation

[![Download Here](https://img.shields.io/badge/-Download%20Here-brightgreen?style=for-the-badge&logo=appveyor)](https://github.com/rwpi/videotimestamp/releases/latest)

Follow these steps to install VTS:

1. Click on the "Download Here" button above to go to the latest release page.
2. Download the appropriate version for your operating system.

For **Windows** users:
- You will receive a .EXE file in a zip folder.
- Extract the zip folder and move `VTS.exe` to your preferred location, such as your desktop.

For **macOS** users:
- You will receive a .pkg installer file.
- Open the .pkg file and follow the guided installer instructions.

![Screenshot of the application](https://github.com/rwpi/videotimestamp/blob/91617447c764ed805648242485d335d75eb3b4d9/media/Screenshot_1_0_1.png)

## Overview
Private Investigator Video Timestamp (VTS) is a cross-platform Python-based application that adds timestamp overlays to camcorder video files. It leverages the metadata within a file to extract date and time information, which is then overlaid onto the video files.

Currently, VTS supports AVCHD (.MTS) video files from Sony and Panasonic camcorders. If your camera or video file format is not supported, please file an issue on GitHub with the camera make/model and a small sample video file. We are continually expanding our support and your contribution will help us improve.

VTS is currently optimized for MacOS computers with builds for M1 and Intel available. We are actively working on expanding compatibility to include Windows and Linux systems in the near future. An experimental Windows build is now available.

## Usage
The application provides four options for users to configure before initiating the timestamping process:

1. **Choose Input Files**
    - Select the video files to be timestamped.
    - The selected files will be added to a list.
    - To add more files, simply click the button again.
    - If a mistake is made while creating the list, click 'reset' to start over.

2. **Choose Output Folder**
    - Specify the destination for the new timestamped files.
    - You can select an existing folder or create a new one.
    - Upon completion, the timestamped files will be located in the chosen folder.

3. **Enable Hardware Acceleration**
    - Check this box to enable hardware acceleration, which can dramatically increase the speed of video processing.
    - Hardware acceleration is currently supported on Windows computers with Intel or AMD processors, and on all macOS computers.
    - If your computer is compatible and the box is checked, the application will automatically use your computer's graphics card for video encoding.
    - If the box is unchecked, or if your computer is not compatible, the application will use software encoding (libx264), which is slower.
    
4. **Remove Audio**
    - If you prefer to have the audio removed from your timestamped video file, ensure this box is checked.

5. **Timestamp Video**
    - After configuring the above options, click the "Timestamp Video" button to start the process.
    - A progress bar will appear and fill up as the video is processed.
    - Once the progress bar is fully filled, your timestamped video is ready for viewing in the specified output folder.

## Licenses and Acknowledgements

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

This application is built with Python and PyQt5, and it includes FFmpeg and Exiftool. 

- [Python](https://www.python.org/): Python is licensed under the [Python Software Foundation License](https://docs.python.org/3/license.html).
- [PyQt5](https://www.riverbankcomputing.com/software/pyqt/intro): PyQt5 is licensed under the [GPLv3](https://www.gnu.org/licenses/gpl-3.0.html) and its source can be downloaded [here](https://www.riverbankcomputing.com/software/pyqt/download).
- [FFmpeg](https://ffmpeg.org/): FFmpeg is licensed under the [LGPLv2.1](http://www.gnu.org/licenses/old-licenses/lgpl-2.1.html) and its source can be downloaded [here](http://ffmpeg.org/download.html).
- [ExifTool](https://exiftool.org/): ExifTool is licensed under the [Artistic License](https://opensource.org/licenses/Artistic-2.0) and its source can be downloaded [here](https://github.com/exiftool/exiftool).

Please note that each component is licensed under its own respective license.

This application is distributed as a binary, which includes the Python interpreter.