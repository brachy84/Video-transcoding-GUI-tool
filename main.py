import json
import os
import subprocess
import sys
from dataclasses import dataclass
from subprocess import CalledProcessError

import aenum
from pathlib import Path
from PyQt6.QtCore import QProcess

import ui


audio_codec_aac = "aac"
audio_codec_flac = "flac"
audio_codec_pcm = "pcm_s16le"


class SISuffix(aenum.AutoNumberEnum):
    _init_ = 'symbol factor'
    NONE = "", 1
    KILO = 'k', 1_000
    MEGA = 'M', 1_000_000
    GIGA = 'G', 1_000_000_000
    TERRA = 'T', 1_000_000_000_000


def _get_output(path: Path):
    return path.parent / Path(path.stem + ".mov")

def get_si_suffix(n: float) -> SISuffix:
    for i in range(len(SISuffix)):
        si = SISuffix(len(SISuffix) - i - 1)
        if n > si.factor:
            return si
    return SISuffix.TERRA


@dataclass
class VideoProperties:
    path: Path
    size: int
    video_codec: str
    fps: float
    width: int
    height: int
    audio_codec: str
    duration: float
    video_bitrate: int
    audio_bitrate: int

    def get_total_bit_rate(self):
        return self.size * 8 / self.duration

    def get_container_bit_rate(self):
        return self.get_total_bit_rate() - self.video_bitrate - self.audio_bitrate


@dataclass
class Command:
    video: VideoProperties
    backup: Path | None
    cmd: str
    options: list[str]
    output: Path | None
    delete_on_finish: bool

    def get_cmd(self, additional_options: list[str] | None = None):
        cmd = [self.cmd]
        [cmd.append(x) for x in self.options]
        if additional_options is not None:
            [cmd.append(x) for x in additional_options]
        if self.output is not None:
            cmd.append(str(self.output))
        return cmd

    def run_with(self, additional_options: list[str] | None = None):
        subprocess.run(self.get_cmd(additional_options))

    def run(self):
        self.run_with()

    def add_progress_options(self):
        self.options.append("-progress")
        self.options.append("pipe:1")
        self.options.append("-nostats")

    def start_qprocess(self, process: QProcess):
        print(f"Running: {self}")
        options = [x for x in self.options]
        if self.output is not None:
            options.append(str(self.output))
        process.start(self.cmd, options)

    def on_finish(self):
        if self.delete_on_finish and self.backup and self.backup.exists():
            os.remove(self.backup)

    def __str__(self):
        return " ".join(self.get_cmd())


@dataclass
class TranscodeOptions:
    transcode_audio: bool
    transcode_video: bool
    audio_codec: str
    fps: float
    resolution: int
    do_backup: bool
    backup_folder: bool
    target_size: int

    def transcode_command(self, prop: VideoProperties) -> Command | None:
        do_transcode_a = self.transcode_audio and prop.audio_codec != self.audio_codec
        do_transcode_v = self.transcode_video and (prop.fps != self.fps or prop.width != self.resolution)
        if not do_transcode_a and not do_transcode_v:
            print(f"Skipping {prop.path}. Nothing to transcode.")
            return None

        backup = None
        cmd = ["-i"]
        if self.do_backup and self.backup_folder:
            backup = prop.path.parent / "backup"
            backup.mkdir(exist_ok=True)
            input = backup / prop.path.name
            if input.exists():
                os.remove(input)
            prop.path.move(input)
            delete_on_finish = False
        else:
            n = prop.path.stem + "_backup" + prop.path.suffix
            input = prop.path.parent / n
            backup = prop.path.replace(input)
            delete_on_finish = not self.do_backup

        cmd.append(str(input))

        self._add_video_options(prop, do_transcode_v, cmd, False)
        self._add_audio_options(prop, do_transcode_a, cmd, False)

        return Command(prop, backup, "ffmpeg", cmd, prop.path, delete_on_finish)

    def transcode_compress_command(self, vid: VideoProperties) -> list[Command] | None:
        do_transcode_a = self.transcode_audio and vid.audio_codec != self.audio_codec
        do_transcode_v = self.transcode_video and (vid.fps != self.fps or vid.width != self.resolution)
        do_compress = self.target_size < vid.size
        if not do_transcode_a and not do_transcode_v and not do_compress:
            print(f"Skipping {vid.path}. Nothing to transcode.")
            return None

        cmd1 = ["-y", "-i"]
        cmd2 = ["-i"]
        cmd1.append(str(vid.path))
        cmd2.append(str(vid.path))

        self._add_video_options(vid, do_transcode_v, cmd1, True)
        self._add_video_options(vid, do_transcode_v, cmd2, True)

        audio_bitrate = vid.audio_bitrate
        if self.audio_codec == audio_codec_aac:
            audio_bitrate = 128_000

        bit_rate = str(self.calc_bitrate(vid.duration, audio_bitrate))
        cmd1.append("-b:v")
        cmd2.append("-b:v")
        cmd1.append(bit_rate)
        cmd2.append(bit_rate)

        cmd1.append("-pass")
        cmd2.append("-pass")
        cmd1.append("1")
        cmd2.append("2")

        cmd1.append("-an")
        cmd1.append("-f")
        cmd1.append("null")
        cmd1.append("/dev/null")

        self._add_audio_options(vid, do_transcode_a, cmd2, True)
        if self.audio_codec == audio_codec_aac:
            cmd2.append("-b:a")
            cmd2.append("128k")

        si_suffix = get_si_suffix(self.target_size)
        s = self.target_size / si_suffix.factor
        if abs(s - int(s)) < 0.1:
            size_text = str(round(s))
        else:
            size_text = f"{s:.2f}".replace(".", "_")
        size_text += si_suffix.symbol + "B"
        output = vid.path.parent / Path(vid.path.stem + "_" + size_text + vid.path.suffix)
        if output.exists():
            print(f"Output {output} already exists")
            return None
        return [Command(vid, "ffmpeg", cmd1, None, False), Command(vid, "ffmpeg", cmd2, output, False)]

    def _add_video_options(self, vid: VideoProperties, do_transcode: bool, opt: list[str], compress: bool):
        opt.append("-c:v")
        if do_transcode:
            opt.append("libx264")
            opt.append("-vf")
            scale = self.resolution / vid.height
            w = int(vid.width * scale)
            h = int(self.resolution)
            opt.append(f"scale={w}:{h},fps={self.fps}")
            if not compress:
                opt.append("-crf")
                opt.append("18")
                opt.append("-preset")
                opt.append("medium")
        elif compress:
            opt.append("libx264")
        else:
            opt.append("copy")

    def _add_audio_options(self, vid: VideoProperties, do_transcode: bool, opt: list[str], always_codec: bool):
        opt.append("-c:a")
        if do_transcode or always_codec:
            opt.append(self.audio_codec)
        else:
            opt.append("copy")

    def calc_bitrate(self, duration: float, audio_bitrate: int):
        #cbr = video.get_container_bit_rate() + 50_000  # safety
        #return self.target_size * 8 / video.duration - video.audio_bitrate - cbr
        return self.target_size * 8 / duration - audio_bitrate - 50_000


def _get_raw_properties(path: Path):
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams", "-show_format",
        str(path)
    ]
    try:
        result = subprocess.check_output(cmd)
        return json.loads(result)
    except CalledProcessError:
        print(f"Error trying to read properties of {path}")
        return None


def _get_duration_properties(path: Path) -> str | None:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path)
    ]
    try:
        result = subprocess.check_output(cmd)
        return json.loads(result)
    except CalledProcessError:
        print(f"Error trying to read duration of {path}")
        return None


def _get_raw_type_data(data: dict, type: str):
    return next(
        s for s in data["streams"]
        if s["codec_type"] == type
    )


def parse_video_properties(path: Path, data: dict | None = None) -> VideoProperties | None:
    if data is None:
        data = _get_raw_properties(path)
        if data is None: return None
    size = os.path.getsize(path)
    duration = float(data["format"]["duration"])
    video_stream = _get_raw_type_data(data, "video")

    video_codec = video_stream["codec_name"]
    width = int(video_stream["width"])
    height = int(video_stream["height"])

    mp4 = path.suffix == ".mp4"
    if mp4:
        video_bitrate = int(video_stream["bit_rate"])
    else:
        video_bitrate = int(data["format"]["bit_rate"])

    # FPS is stored as fraction like "60000/1001"
    fps_str = video_stream["r_frame_rate"]
    num, den = map(int, fps_str.split("/"))
    fps = num / den

    audio_stream = _get_raw_type_data(data, "audio")
    audio_codec = audio_stream["codec_name"]
    if mp4:
        audio_bitrate = int(audio_stream["bit_rate"])
    else:
        # other formats done expose bit rate per stream, so we need to guess
        if audio_codec == audio_codec_aac:
            audio_bitrate = 128_000
        else:
            audio_bitrate = 1_536_000
        video_bitrate -= audio_bitrate

    return VideoProperties(path, size, video_codec, fps, width, height, audio_codec, duration, video_bitrate,
                           audio_bitrate)


def _run_command(cmd: list[str] | None):
    if cmd is None: return

    print("Running:")
    print(" ".join(cmd))
    subprocess.run(cmd)


def _parse_path_list(arg: str):
    return [Path(raw_path if raw_path.startswith("/") else "/" + raw_path) for raw_path in arg.split(" /")]


def _reload_from_backup(path: Path):
    # Remove transcoded file and move backup back into place for testing
    backup1 = path.parent / "backup" / path.name
    backup2 = path.parent / Path(path.stem + "_backup" + path.suffix)
    b1 = backup1.exists()
    b2 = backup2.exists()
    if b1 or b2:
        out = path
        if path.exists():
            os.remove(path)
        if out.exists():
            os.remove(out)
        if b1:
            backup1.move(path)
        elif b2:
            backup2.move(path)
    pass


def run_transcoder(paths: list[Path], codec: str, backup: bool):
    commands: list[Command] = []
    for path in paths:
        #_reload_from_backup(path)
        prop = parse_video_properties(path)
        if prop is None: continue
        if prop.audio_codec == codec:
            print(f"Video {path} already has {codec} audio codec")
            continue
        print(f"Video: {prop}")
        transcoder = TranscodeOptions(True, False, codec, prop.fps, prop.width, backup, backup, -1)
        cmd = transcoder.transcode_command(prop)
        if cmd is None: continue
        commands.append(cmd)

    if len(commands) == 0:
        print("Nothing to process")
        return
    ui.create_transcoder_window(commands)


def run_customizable_transcoder(paths: list[Path], compress: bool):
    videos: list[VideoProperties] = []
    for path in paths:
        #_reload_from_backup(path)
        prop = parse_video_properties(path)
        if prop is None: continue
        print(f"Video: {prop}")
        videos.append(prop)
    if len(videos) == 0:
        print("Nothing to process")
        return
    ui.create_customizable_window(videos, compress)


def run():
    if len(sys.argv) < 3:
        print("No input file and type argument provided.")
        return

    paths = _parse_path_list(sys.argv[1])
    type = sys.argv[2]
    if type == "quick_to_davinci":
        run_transcoder(paths, audio_codec_pcm, True)
    elif type == "quick_from_davinci":
        run_transcoder(paths, audio_codec_aac, False)
    elif type == "custom":
        run_customizable_transcoder(paths, False)
    elif type == "compress":
        run_customizable_transcoder(paths, True)
    else:
        raise NameError(f"No transcoder type {type}")


if __name__ == "__main__":
    run()
