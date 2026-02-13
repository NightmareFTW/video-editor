#!/usr/bin/env python3
"""Edição automática de vídeo com corte, zoom e marca de água.

Exemplos:
    python3 main.py --input video.mp4 --logo logo.png
    python3 main.py --gui
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox


START_SECOND = 5
END_SECOND = 15
ZOOM_FACTOR = 1.10
WATERMARK_WIDTH_RATIO = 0.12
PADDING_PX = 20
SUPPORTED_VIDEO_EXTENSIONS = {".mp4"}
SUPPORTED_IMAGE_EXTENSIONS = {".png"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Recorta o vídeo entre 5s e 15s, aplica zoom de 110% e adiciona "
            "marca de água no canto inferior direito."
        )
    )
    parser.add_argument("--input", help="Caminho do vídeo .mp4 original")
    parser.add_argument("--logo", help="Caminho da imagem .png da marca de água")
    parser.add_argument(
        "--output",
        default="edited_video.mp4",
        help="Nome/caminho do vídeo editado (padrão: edited_video.mp4)",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Abre interface gráfica para selecionar vídeo/logo/saída.",
    )
    return parser.parse_args()


def resolve_ffmpeg_binary() -> str:
    ffmpeg_in_path = shutil.which("ffmpeg")
    if ffmpeg_in_path:
        return ffmpeg_in_path

    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        raise RuntimeError(
            "ffmpeg não encontrado no sistema. Instale o FFmpeg e adicione ao PATH "
            "(no Windows, prefira winget/choco/scoop) ou instale `imageio-ffmpeg` via pip."
        )


def validate_input_file(path: Path, valid_extensions: set[str], label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} não encontrado: {path}")
    if not path.is_file():
        raise ValueError(f"{label} inválido (não é ficheiro): {path}")
    if path.suffix.lower() not in valid_extensions:
        allowed = ", ".join(sorted(valid_extensions))
        raise ValueError(f"{label} deve ter uma destas extensões: {allowed}")


def has_audio_stream(video_path: Path, ffmpeg_binary: str) -> bool:
    cmd = [ffmpeg_binary, "-i", str(video_path)]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    combined_output = f"{result.stdout}\n{result.stderr}"
    return re.search(r"Stream #\d+:\d+.*Audio:", combined_output) is not None


def resolve_ffprobe_binary(ffmpeg_binary: str) -> str | None:
    ffprobe_in_path = shutil.which("ffprobe")
    if ffprobe_in_path:
        return ffprobe_in_path

    ffmpeg_path = Path(ffmpeg_binary)
    sibling_ffprobe = ffmpeg_path.with_name("ffprobe")
    if sibling_ffprobe.exists():
        return str(sibling_ffprobe)

    if ffmpeg_path.suffix:
        sibling_ffprobe_with_suffix = ffmpeg_path.with_name(f"ffprobe{ffmpeg_path.suffix}")
        if sibling_ffprobe_with_suffix.exists():
            return str(sibling_ffprobe_with_suffix)

    return None


def parse_duration_from_ffmpeg_probe_output(output: str) -> float | None:
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
    if not match:
        return None

    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = float(match.group(3))
    duration = hours * 3600 + minutes * 60 + seconds
    return duration if duration > 0 else None


def get_video_duration_seconds(
    video_path: Path,
    ffmpeg_binary: str,
    ffprobe_binary: str | None,
) -> float:
    duration: float | None = None

    if ffprobe_binary:
        cmd = [
            ffprobe_binary,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(video_path),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            payload = json.loads(result.stdout or "{}")
            duration_raw = payload.get("format", {}).get("duration")
            if duration_raw is not None:
                duration = float(duration_raw)

    if duration is None:
        fallback_cmd = [ffmpeg_binary, "-i", str(video_path)]
        fallback_result = subprocess.run(fallback_cmd, capture_output=True, text=True, check=False)
        combined_output = f"{fallback_result.stdout}\n{fallback_result.stderr}"
        duration = parse_duration_from_ffmpeg_probe_output(combined_output)

    if duration is None or duration <= 0:
        raise RuntimeError(
            "Não foi possível obter a duração do vídeo. Verifique se o ficheiro não está corrompido."
        )

    return duration


def compute_trim_window(video_duration_seconds: float) -> tuple[float, float]:
    start = min(START_SECOND, max(video_duration_seconds - 0.001, 0.0))
    end = min(END_SECOND, video_duration_seconds)

    if end <= start:
        start = 0.0
        end = video_duration_seconds

    return start, end


def build_ffmpeg_command(
    ffmpeg_binary: str,
    input_video: Path,
    logo: Path,
    output_video: Path,
    include_audio: bool,
    start_second: float,
    end_second: float,
) -> list[str]:
    crop_width_expr = f"iw/{ZOOM_FACTOR}"
    crop_height_expr = f"ih/{ZOOM_FACTOR}"

    video_chain = (
        f"[0:v]scale=iw*{ZOOM_FACTOR}:ih*{ZOOM_FACTOR},"
        f"crop={crop_width_expr}:{crop_height_expr}:(in_w-out_w)/2:(in_h-out_h)/2[base];"
        f"[1:v][base]scale2ref=w=main_w*{WATERMARK_WIDTH_RATIO}:h=-1[wm][base2];"
        f"[base2][wm]overlay=W-w-{PADDING_PX}:H-h-{PADDING_PX}[vout]"
    )

    filter_complex = video_chain

    command = [
        ffmpeg_binary,
        "-y",
        "-ss",
        f"{start_second:.3f}",
        "-to",
        f"{end_second:.3f}",
        "-i",
        str(input_video),
        "-loop",
        "1",
        "-i",
        str(logo),
    ]

    if include_audio:
        filter_complex = f"{video_chain};[0:a]asetpts=PTS-STARTPTS[aout]"

    command += [
        "-filter_complex",
        filter_complex,
        "-map",
        "[vout]",
    ]

    if include_audio:
        command += ["-map", "[aout]", "-c:a", "aac"]

    command += [
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-shortest",
        "-movflags",
        "+faststart",
        str(output_video),
    ]
    return command


def ensure_output_path(output_video: Path) -> None:
    if output_video.suffix.lower() != ".mp4":
        raise ValueError("O ficheiro de saída deve ter extensão .mp4")

    output_parent = output_video.parent
    output_parent.mkdir(parents=True, exist_ok=True)


def collect_paths_gui(default_output: str) -> tuple[str, str, str] | None:
    selections: dict[str, str] = {}

    root = tk.Tk()
    root.title("Video Editor")
    root.geometry("620x220")
    root.resizable(False, False)

    input_var = tk.StringVar()
    logo_var = tk.StringVar()
    output_var = tk.StringVar(value=default_output)

    def choose_input() -> None:
        path = filedialog.askopenfilename(
            title="Selecionar vídeo",
            filetypes=[("Vídeo MP4", "*.mp4")],
        )
        if path:
            input_var.set(path)

    def choose_logo() -> None:
        path = filedialog.askopenfilename(
            title="Selecionar logo",
            filetypes=[("Imagem PNG", "*.png")],
        )
        if path:
            logo_var.set(path)

    def choose_output() -> None:
        path = filedialog.asksaveasfilename(
            title="Guardar vídeo editado",
            defaultextension=".mp4",
            filetypes=[("Vídeo MP4", "*.mp4")],
            initialfile=Path(output_var.get()).name,
        )
        if path:
            output_var.set(path)

    def submit() -> None:
        if not input_var.get() or not logo_var.get() or not output_var.get():
            messagebox.showerror("Campos em falta", "Preencha os três campos antes de continuar.")
            return
        selections["input"] = input_var.get()
        selections["logo"] = logo_var.get()
        selections["output"] = output_var.get()
        root.destroy()

    def cancel() -> None:
        root.destroy()

    labels = [
        ("Vídeo (.mp4)", input_var, choose_input),
        ("Logo (.png)", logo_var, choose_logo),
        ("Saída (.mp4)", output_var, choose_output),
    ]

    for row, (label, variable, callback) in enumerate(labels):
        tk.Label(root, text=label, anchor="w").grid(row=row, column=0, padx=10, pady=10, sticky="w")
        tk.Entry(root, textvariable=variable, width=58).grid(row=row, column=1, padx=10, pady=10)
        tk.Button(root, text="Escolher", command=callback, width=12).grid(row=row, column=2, padx=10, pady=10)

    buttons_frame = tk.Frame(root)
    buttons_frame.grid(row=4, column=0, columnspan=3, pady=18)
    tk.Button(buttons_frame, text="Processar", command=submit, width=16).pack(side="left", padx=10)
    tk.Button(buttons_frame, text="Cancelar", command=cancel, width=16).pack(side="left", padx=10)

    root.mainloop()

    if not selections:
        return None

    return selections["input"], selections["logo"], selections["output"]


def resolve_paths(args: argparse.Namespace) -> tuple[Path, Path, Path] | None:
    wants_gui = args.gui or not args.input or not args.logo

    if wants_gui:
        gui_result = collect_paths_gui(args.output)
        if gui_result is None:
            return None
        input_path, logo_path, output_path = gui_result
    else:
        input_path = args.input
        logo_path = args.logo
        output_path = args.output

    return (
        Path(input_path).expanduser().resolve(),
        Path(logo_path).expanduser().resolve(),
        Path(output_path).expanduser().resolve(),
    )


def main() -> int:
    args = parse_args()

    try:
        paths = resolve_paths(args)
        if paths is None:
            print("Operação cancelada pelo utilizador.")
            return 1

        input_video, logo, output_video = paths

        ffmpeg_binary = resolve_ffmpeg_binary()
        ffprobe_binary = resolve_ffprobe_binary(ffmpeg_binary)
        if ffprobe_binary is None:
            print("⚠️ ffprobe não encontrado; a usar fallback de duração via ffmpeg.")
        validate_input_file(input_video, SUPPORTED_VIDEO_EXTENSIONS, "Vídeo de entrada")
        validate_input_file(logo, SUPPORTED_IMAGE_EXTENSIONS, "Logo")
        ensure_output_path(output_video)

        video_duration = get_video_duration_seconds(input_video, ffmpeg_binary, ffprobe_binary)
        start_second, end_second = compute_trim_window(video_duration)

        include_audio = has_audio_stream(input_video, ffmpeg_binary)
        ffmpeg_cmd = build_ffmpeg_command(
            ffmpeg_binary,
            input_video,
            logo,
            output_video,
            include_audio,
            start_second,
            end_second,
        )

        print("Executando:", " ".join(ffmpeg_cmd))
        subprocess.run(ffmpeg_cmd, check=True)

        if include_audio:
            print(f"✅ Vídeo editado gerado com áudio em: {output_video}")
        else:
            print(f"✅ Vídeo editado gerado (entrada sem áudio) em: {output_video}")
        return 0
    except subprocess.CalledProcessError as exc:
        print(f"❌ Falha ao processar vídeo. Código: {exc.returncode}", file=sys.stderr)
        if exc.stderr:
            print(exc.stderr, file=sys.stderr)
        return exc.returncode
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
