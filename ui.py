import os
import sys

from PyQt6.QtCore import QProcess, QTimer
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QProgressBar, QPushButton, QApplication, QCheckBox, \
    QGridLayout, QGroupBox, QComboBox, QSpinBox

import main
from main import VideoProperties, TranscodeOptions, Command, SISuffix


class TranscodeWindow(QWidget):
    def __init__(self, cmd: list[Command], paired: bool):
        super().__init__()
        self.cmd = cmd
        self.paired = paired
        for cmd in self.cmd:
            cmd.add_progress_options()
        if self.paired and len(self.cmd) % 2 != 0:
            raise ValueError("Command amount must be an even number when paired")
        self.current_cmd_index: int = -1

        self.setWindowTitle("FFmpeg Transcoder")

        layout = QVBoxLayout(self)

        self.label = QLabel("Ready")
        layout.addWidget(self.label)

        self.size = len(self.cmd)
        if self.paired:
            self.size //= 2
        self.count_progress = QProgressBar()
        self.count_progress.setRange(0, self.size)
        self.count_progress.setFormat("%v/%m")
        self.count_progress.setValue(0)
        layout.addWidget(self.count_progress)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)

        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.handle_output)
        self.process.finished.connect(self.finished)

        QTimer.singleShot(100, self.start_next_command)
        self.setMinimumSize(300, 150)

    def start_next_command(self):
        self.current_cmd_index += 1
        self.cmd[self.current_cmd_index].start_qprocess(self.process)
        self.label.setText(f"Transcoding {self.cmd[self.current_cmd_index].video.path.name}")

    def handle_output(self):
        data = (self.process.readAllStandardOutput()
                .data()
                .decode())

        for line in data.splitlines():
            if line.startswith("out_time_ms="):
                out_time_ms = line.split("=")[1]
                if out_time_ms == "N/A":
                    break
                seconds = int(out_time_ms) / 1_000_000
                progress = (seconds / self.cmd[self.current_cmd_index].video.duration)
                if self.paired:
                    progress *= 50
                    if self.current_cmd_index % 2 != 0:
                        progress += 50
                else:
                    progress *= 100
                # print("Current progress: ", out_time_ms, seconds, progress, self.paired, self.current_cmd_index % 2 != 0)
                self.progress.setValue(int(progress))
                break

    def finished(self):
        self.cmd[self.current_cmd_index].on_finish()
        self.progress.setValue(100)
        if not self.paired or self.current_cmd_index % 2 != 0:
            self.count_progress.setValue(self.count_progress.value() + 1)
        if self.count_progress.value() == self.size:
            self.label.setText("Finished")
            if self.paired:
                # remove compressing cache
                for cmd in self.cmd:
                    if cmd.output is None: continue
                    p = cmd.output.parent
                    log = p / "ffmpeg2pass-0.log"
                    if log.exists(): os.remove(log)
                    log = p / "ffmpeg2pass-0.log.mbtree"
                    if log.exists(): os.remove(log)
            QTimer.singleShot(1000, QApplication.quit)
        else:
            if not self.paired or self.current_cmd_index % 2 != 0:
                self.progress.setValue(0)
            else:
                self.progress.setValue(50)
            self.start_next_command()


def _transcoder_of(videos: list[VideoProperties], with_size: bool):
    if len(videos) == 1:
        v = videos[0]
        size = v.size if with_size else -1
        return TranscodeOptions(True, True, main.audio_codec_pcm, v.fps, v.height, True, False, size)
    max_fps = 0
    max_res = 0
    size = -1
    for v in videos:
        max_fps = max(max_fps, v.fps)
        max_res = max(max_res, v.height)
        if with_size:
            size = min(size, v.size)
    return TranscodeOptions(True, True, main.audio_codec_pcm, max_fps, max_res, True, True, size)


class CustomizeWindow(QWidget):
    def __init__(self, videos: list[VideoProperties]):
        super().__init__()
        self.videos = videos
        self.transcoder: TranscodeOptions = _transcoder_of(videos, False)
        self.process_window: TranscodeWindow | None = None
        self.transcoder.target_size = -1

        self.setWindowTitle("FFmpeg Transcoder")

        layout = QVBoxLayout(self)

        self._start_grid = QWidget()
        grid = QGridLayout(self._start_grid)
        layout.addWidget(self._start_grid)

        self.transcode_audio_button = QCheckBox()
        self.transcode_audio_button.setChecked(self.transcoder.transcode_audio)
        self.transcode_audio_button.stateChanged.connect(self.on_change_transcode_audio)
        self.transcode_audio_type = QComboBox()
        self.transcode_audio_type.addItem(main.audio_codec_aac)
        self.transcode_audio_type.addItem(main.audio_codec_pcm)
        self.transcode_audio_type.setCurrentText(self.transcoder.audio_codec)
        self.transcode_audio_type.currentTextChanged.connect(self.on_audio_codec)
        grid.addWidget(QLabel("Transcode audio"), 0, 0)
        grid.addWidget(self.transcode_audio_button, 0, 1)
        grid.addWidget(QLabel("to"), 0, 2)
        grid.addWidget(self.transcode_audio_type, 0, 3)

        self.transcode_video_button = QCheckBox()
        self.transcode_video_button.setChecked(self.transcoder.transcode_video)
        self.transcode_video_button.stateChanged.connect(self.on_change_transcode_video)
        grid.addWidget(QLabel("Transcode video: "), 1, 0)
        grid.addWidget(self.transcode_video_button, 1, 1)

        self.options_box = QGroupBox("Video options")
        grid = QGridLayout(self.options_box)
        layout.addWidget(self.options_box)

        fps_options = [24, 29.97, 30.0, 59.94, 60.0]
        if self.transcoder.fps not in fps_options:
            fps_options.append(self.transcoder.fps)
        self.fps_dropdown = QComboBox()
        for fps in fps_options: self.fps_dropdown.addItem(str(fps))
        self.fps_dropdown.setCurrentText(str(self.transcoder.fps))
        self.fps_dropdown.currentTextChanged.connect(self.on_fps_changed)
        grid.addWidget(QLabel("FPS: "), 0, 0)
        grid.addWidget(self.fps_dropdown, 0, 1)

        res_options = [144, 360, 504, 720, 1080, 1440, 2160]
        if self.transcoder.resolution not in res_options:
            res_options.append(self.transcoder.resolution)
        self.res_dropdown = QComboBox()
        for res in res_options: self.res_dropdown.addItem(str(res))
        self.res_dropdown.setCurrentText(str(self.transcoder.resolution))
        self.res_dropdown.currentTextChanged.connect(self.on_res_changed)
        grid.addWidget(QLabel("Resolution: "), 1, 0)
        grid.addWidget(self.res_dropdown, 1, 1)

        self.backup_button = QCheckBox()
        self.backup_button.setChecked(self.transcoder.do_backup)
        self.backup_button.stateChanged.connect(self.on_change_backup)
        grid.addWidget(QLabel("Backup file: "), 2, 0)
        grid.addWidget(self.backup_button, 2, 1)

        self.backup_folder_button = QCheckBox()
        self.backup_folder_button.setChecked(self.transcoder.backup_folder)
        self.backup_folder_button.stateChanged.connect(self.on_change_backup_folder)
        self.backup_folder_label = QLabel("Backup in folder: ")
        grid.addWidget(self.backup_folder_label, 3, 0)
        grid.addWidget(self.backup_folder_button, 3, 1)

        self.start_button = QPushButton("Start transcoding")
        self.start_button.clicked.connect(self.start_process)
        self.start_button.setEnabled(self.transcoder.transcode_audio or self.transcoder.transcode_video)
        layout.addWidget(self.start_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(QApplication.quit)
        layout.addWidget(self.cancel_button)

        self.on_change_transcode_audio(self.transcoder.transcode_audio)
        self.on_change_transcode_video(self.transcoder.transcode_video)
        self.on_change_backup(self.transcoder.do_backup)

        self.setMinimumSize(300, 300)

    def on_change_transcode_audio(self, checked: bool):
        checked = bool(checked)
        self.transcoder.transcode_audio = checked
        self.start_button.setEnabled(self.transcoder.transcode_audio or self.transcoder.transcode_video)

    def on_change_transcode_video(self, checked: bool):
        checked = bool(checked)
        self.transcoder.transcode_video = checked
        self.start_button.setEnabled(self.transcoder.transcode_audio or self.transcoder.transcode_video)
        self.options_box.setEnabled(checked)

    def on_audio_codec(self, text):
        self.transcoder.audio_codec = str(text)

    def on_fps_changed(self, text):
        self.transcoder.fps = float(text)

    def on_res_changed(self, text):
        self.transcoder.resolution = int(text)

    def on_change_backup(self, checked):
        checked = bool(checked)
        self.transcoder.do_backup = checked
        self.backup_folder_button.setEnabled(checked)
        self.backup_folder_label.setEnabled(checked)

    def on_change_backup_folder(self, checked):
        checked = bool(checked)
        self.transcoder.backup_folder = checked

    def start_process(self):
        # close window and open new window
        cmds = [self.transcoder.transcode_command(x) for x in self.videos]
        self.process_window = TranscodeWindow([x for x in cmds if x is not None], False)
        self.process_window.show()
        self.close()


class CompressWindow(QWidget):
    def __init__(self, videos: list[VideoProperties]):
        super().__init__()
        self.videos = videos
        self.transcoder: TranscodeOptions = _transcoder_of(videos, True)
        self.process_window: TranscodeWindow | None = None
        self.transcoder.do_backup = False
        self.transcoder.backup_folder = False
        self.transcoder.transcode_audio = True
        self.transcoder.transcode_video = False
        self.transcoder.audio_codec = main.audio_codec_aac

        self.setWindowTitle("FFmpeg Transcoder")

        layout = QVBoxLayout(self)

        self._start_grid = QWidget()
        grid = QGridLayout(self._start_grid)
        layout.addWidget(self._start_grid)

        self.transcode_audio_type = QComboBox()
        self.transcode_audio_type.addItem(main.audio_codec_aac)
        self.transcode_audio_type.addItem(main.audio_codec_pcm)
        self.transcode_audio_type.setCurrentText(self.transcoder.audio_codec)
        self.transcode_audio_type.currentTextChanged.connect(self.on_audio_codec)
        grid.addWidget(QLabel("Transcode audio to"), 0, 0)
        grid.addWidget(self.transcode_audio_type, 0, 1)

        self.transcode_video_button = QCheckBox()
        self.transcode_video_button.setChecked(self.transcoder.transcode_video)
        self.transcode_video_button.stateChanged.connect(self.on_change_transcode_video)
        grid.addWidget(QLabel("Transcode video: "), 1, 0)
        grid.addWidget(self.transcode_video_button, 1, 1)

        self.options_box = QGroupBox("Video options")
        grid = QGridLayout(self.options_box)
        layout.addWidget(self.options_box)

        fps_options = [24, 29.97, 30.0, 59.94, 60.0]
        if self.transcoder.fps not in fps_options:
            fps_options.append(self.transcoder.fps)
        self.fps_dropdown = QComboBox()
        for fps in fps_options: self.fps_dropdown.addItem(str(fps))
        self.fps_dropdown.setCurrentText(str(self.transcoder.fps))
        self.fps_dropdown.currentTextChanged.connect(self.on_fps_changed)
        grid.addWidget(QLabel("FPS: "), 0, 0)
        grid.addWidget(self.fps_dropdown, 0, 1)

        res_options = [144, 360, 504, 720, 1080, 1440, 2160]
        if self.transcoder.resolution not in res_options:
            res_options.append(self.transcoder.resolution)
        self.res_dropdown = QComboBox()
        for res in res_options: self.res_dropdown.addItem(str(res))
        self.res_dropdown.setCurrentText(str(self.transcoder.resolution))
        self.res_dropdown.currentTextChanged.connect(self.on_res_changed)
        grid.addWidget(QLabel("Resolution: "), 1, 0)
        grid.addWidget(self.res_dropdown, 1, 1)

        self.target_size_box = QGroupBox("Target Size")
        grid = QGridLayout(self.target_size_box)
        layout.addWidget(self.target_size_box)

        target_size_si = main.get_si_suffix(self.transcoder.target_size)
        self.target_size_field = QSpinBox()
        self.target_size_field.setRange(1, 999)
        self.target_size_field.setValue(self.transcoder.target_size // target_size_si.factor + 1)
        self.target_size_field.valueChanged.connect(self.on_target_size_changed)
        grid.addWidget(self.target_size_field, 0, 0)

        self.target_size_si_dropdown = QComboBox()
        for si in SISuffix: self.target_size_si_dropdown.addItem(si.symbol + "B")
        self.target_size_si_dropdown.setCurrentText(target_size_si.symbol + "B")
        self.target_size_si_dropdown.currentIndexChanged.connect(self.on_target_size_changed)
        grid.addWidget(self.target_size_si_dropdown, 0, 1)

        self.start_button = QPushButton("Start transcoding")
        self.start_button.clicked.connect(self.start_process)
        self.start_button.setEnabled(self.transcoder.transcode_audio or self.transcoder.transcode_video)
        layout.addWidget(self.start_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(QApplication.quit)
        layout.addWidget(self.cancel_button)

        self.on_change_transcode_video(self.transcoder.transcode_video)

        self.setMinimumSize(300, 300)

    def on_change_transcode_video(self, checked: bool):
        checked = bool(checked)
        self.transcoder.transcode_video = checked
        self.start_button.setEnabled(self.transcoder.transcode_audio or self.transcoder.transcode_video)
        self.options_box.setEnabled(checked)

    def on_audio_codec(self, text):
        self.transcoder.audio_codec = str(text)

    def on_fps_changed(self, text):
        self.transcoder.fps = float(text)

    def on_res_changed(self, text):
        self.transcoder.resolution = int(text)

    def on_target_size_changed(self, _):
        self.transcoder.target_size = int(
            self.target_size_field.value() * SISuffix(self.target_size_si_dropdown.currentIndex() + 1).factor)

    def start_process(self):
        # close window and open new window
        cmds = []
        for vid in self.videos:
            c = self.transcoder.transcode_compress_command(vid)
            if c is not None:
                cmds.append(c[0])
                cmds.append(c[1])
        if len(cmds) > 0:
            self.process_window = TranscodeWindow(cmds, True)
            self.process_window.show()
            self.close()
            return
        print("No valid transcode commands created")
        QApplication.quit()


def create_customizable_window(vids: list[VideoProperties], compress: bool):
    app = QApplication(sys.argv)
    if compress:
        window = CompressWindow(vids)
    else:
        window = CustomizeWindow(vids)
    window.show()
    sys.exit(app.exec())


def create_transcoder_window(cmd: list[Command]):
    app = QApplication(sys.argv)
    window = TranscodeWindow(cmd, False)
    window.show()
    sys.exit(app.exec())
