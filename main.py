#!/usr/bin/env python3
"""Edição automática de vídeo com corte, zoom e marca de água.

Exemplo:
    python3 main --input video.mp4 --logo logo.png
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


START_SECOND = 5
END_SECOND = 15
ZOOM_FACTOR = 1.10
WATERMARK_WIDTH_RATIO = 0.12
PADDING_PX = 20


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Recorta o vídeo entre 5s e 15s, aplica zoom de 110% e adiciona "
            "marca de água no canto inferior direito."
        )
    )
    parser.add_argument("--input", required=True, help="Caminho do vídeo .mp4 original")
    parser.add_argument("--logo", required=True, help="Caminho da imagem .png da marca de água")
    parser.add_argument(
        "--output",
        default="edited_video.mp4",
        help="Nome/caminho do vídeo editado (padrão: edited_video.mp4)",
    )
    return parser.parse_args()


def ensure_dependencies() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg não encontrado no sistema.")
    if shutil.which("ffprobe") is None:
        raise RuntimeError("ffprobe não encontrado no sistema.")


def has_audio_stream(video_path: Path) -> bool:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=index",
        "-of",
        "csv=p=0",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return bool(result.stdout.strip())


def build_ffmpeg_command(input_video: Path, logo: Path, output_video: Path, include_audio: bool) -> list[str]:
    crop_width_expr = f"iw/{ZOOM_FACTOR}"
    crop_height_expr = f"ih/{ZOOM_FACTOR}"

    video_chain = (
        f"[0:v]trim=start={START_SECOND}:end={END_SECOND},"
        "setpts=PTS-STARTPTS,"
        f"scale=iw*{ZOOM_FACTOR}:ih*{ZOOM_FACTOR},"
        f"crop={crop_width_expr}:{crop_height_expr}:(in_w-out_w)/2:(in_h-out_h)/2[base];"
        f"[1:v][base]scale2ref=w=main_w*{WATERMARK_WIDTH_RATIO}:h=-1[wm][base2];"
        f"[base2][wm]overlay=W-w-{PADDING_PX}:H-h-{PADDING_PX}[vout]"
    )

    filter_complex = video_chain

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_video),
        "-i",
        str(logo),
    ]

    if include_audio:
        audio_chain = (
            f"[0:a]atrim=start={START_SECOND}:end={END_SECOND},"
            "asetpts=PTS-STARTPTS[aout]"
        )
        filter_complex = f"{video_chain};{audio_chain}"

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
        str(output_video),
    ]
    return command


def main() -> int:
    args = parse_args()
    input_video = Path(args.input).expanduser().resolve()
    logo = Path(args.logo).expanduser().resolve()
    output_video = Path(args.output).expanduser().resolve()

    try:
        ensure_dependencies()

        if not input_video.exists():
            raise FileNotFoundError(f"Vídeo de entrada não encontrado: {input_video}")
        if input_video.suffix.lower() != ".mp4":
            raise ValueError("O vídeo de entrada deve ser um arquivo .mp4")
        if not logo.exists():
            raise FileNotFoundError(f"Logo não encontrado: {logo}")
        if logo.suffix.lower() != ".png":
            raise ValueError("A marca de água deve ser um arquivo .png")

        include_audio = has_audio_stream(input_video)
        ffmpeg_cmd = build_ffmpeg_command(input_video, logo, output_video, include_audio)

        print("Executando:", " ".join(ffmpeg_cmd))
        subprocess.run(ffmpeg_cmd, check=True)

        if include_audio:
            print(f"✅ Vídeo editado gerado com áudio em: {output_video}")
        else:
            print(f"✅ Vídeo editado gerado (entrada sem áudio) em: {output_video}")
        return 0
    except subprocess.CalledProcessError as exc:
        print(f"❌ Falha ao processar vídeo. Código: {exc.returncode}", file=sys.stderr)
        return exc.returncode
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
