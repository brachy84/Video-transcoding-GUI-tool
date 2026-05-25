# Video transcoding GUI Tool

This is a Python script that allows transcoding video files via a GUI.

The script can be run with
```shell
python3 main.py "%F" <option>
```
Where `%F` is a list of absolute file paths separated by a space.
`<option>` can one of these:
- `quick`: Transcodes the audio of the file from AAC to PCM. This is useful for Davinci Resolve on Linux. This also creates a backup of your files.
- `custom`: Opens a GUI to change audio codec, video fps and resolution. You also have the option to create backups automatically.
- `compress`: Similar to `custom`, but you can select a target file size. The new file will have the size appended in the name.
  For example compressing `input.mp4` to 10MB becomes `input_10MB.mp4`. The old file is not deleted.

## KDE integration
1. Copy `ffmpeg_helper.desktop` to `~/.local/share/kio/servicemenus/`.
2. There are 3 Exec= lines which contain a path to a python executable and the `main.py` file. These need to be adjusted to your paths.

## Requirements
See `requirements.txt`. Of course this also requires ffmpeg and ffprobe installed.