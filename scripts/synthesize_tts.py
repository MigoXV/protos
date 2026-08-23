#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import sys
import tempfile
import wave
from pathlib import Path
from types import ModuleType

import grpc
from grpc_tools import protoc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="调用 TtsService 克隆音色并合成 WAV")
    parser.add_argument("--reference", type=Path, required=True, help="PCM 16-bit 单声道 WAV")
    parser.add_argument("--output", type=Path, required=True, help="输出 WAV 路径")
    parser.add_argument("--text", required=True, help="待合成文本")
    parser.add_argument("--ref-text", default="", help="参考音频转写；未知时可留空")
    parser.add_argument("--language", default="Chinese", help="合成语言")
    parser.add_argument("--decoder-chunk-size", type=int, default=12)
    parser.add_argument("--target", default="127.0.0.1:50004")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--proto",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "protos" / "tts" / "tts.proto",
    )
    return parser.parse_args()


def compile_proto(proto: Path, output_dir: Path) -> tuple[ModuleType, ModuleType]:
    result = protoc.main(
        [
            "grpc_tools.protoc",
            f"-I{proto.parent}",
            f"--python_out={output_dir}",
            f"--grpc_python_out={output_dir}",
            str(proto),
        ]
    )
    if result != 0:
        raise RuntimeError(f"生成 TTS gRPC 客户端失败，protoc 退出码：{result}")

    sys.path.insert(0, str(output_dir))
    try:
        return importlib.import_module("tts_pb2"), importlib.import_module("tts_pb2_grpc")
    finally:
        sys.path.pop(0)


def read_reference(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise ValueError("参考音频必须是 PCM 16-bit 单声道 WAV")
        if source.getcomptype() != "NONE":
            raise ValueError("参考音频必须是未压缩 PCM WAV")
        return source.readframes(source.getnframes()), source.getframerate()


def write_output(path: Path, pcm: bytes, sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm)


def main() -> None:
    args = parse_args()
    reference_pcm, reference_rate = read_reference(args.reference)

    with tempfile.TemporaryDirectory(prefix="tts-grpc-") as generated_dir:
        pb2, pb2_grpc = compile_proto(args.proto.resolve(), Path(generated_dir))
        request = pb2.SynthesizeRequest(
            voice=pb2.VoiceSource(
                reference_voice=pb2.ReferenceVoice(
                    pcm_s16le=reference_pcm,
                    sample_rate=reference_rate,
                    ref_text=args.ref_text,
                )
            ),
            text=args.text,
            language=args.language,
            decoder_chunk_size=args.decoder_chunk_size,
        )

        chunks: list[bytes] = []
        sample_rate: int | None = None
        with grpc.insecure_channel(args.target) as channel:
            grpc.channel_ready_future(channel).result(timeout=args.timeout)
            stub = pb2_grpc.TtsServiceStub(channel)
            for chunk in stub.Synthesize(request, timeout=args.timeout):
                if sample_rate is None:
                    sample_rate = chunk.sample_rate
                elif chunk.sample_rate != sample_rate:
                    raise RuntimeError(
                        f"服务在同一次响应中返回了不同采样率：{sample_rate} 与 {chunk.sample_rate}"
                    )
                chunks.append(chunk.pcm_s16le)

    if not chunks or sample_rate is None:
        raise RuntimeError("TTS 服务未返回音频")
    pcm = b"".join(chunks)
    if len(pcm) % 2:
        raise RuntimeError("TTS 服务返回的 PCM S16LE 字节数不是偶数")
    write_output(args.output, pcm, sample_rate)
    print(
        f"已写入 {args.output}：{sample_rate} Hz，{len(pcm) // 2 / sample_rate:.2f} 秒，"
        f"{len(chunks)} 个数据块"
    )


if __name__ == "__main__":
    main()
