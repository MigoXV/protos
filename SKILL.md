---
name: protos
description: 使用 grpcio-tools 和 mypy-protobuf 从 .proto 文件生成 Python gRPC 与 Protobuf 代码。适用于需要查找 proto 文件、编写或修复 scripts/run_grpcio_tools.sh、生成 *_pb2.py、*_pb2.pyi、*_pb2_grpc.py、*_pb2_grpc.pyi、用 pip 而不是 poetry add 安装缺失生成工具，或确保 grpcio-tools 版本与已安装 grpcio 版本完全一致的场景。
---

# Protos

## 工作流程

1. 修改前先检查目标项目：找到 `.proto` 文件、包结构、已有生成文件、`pyproject.toml` 和现有生成脚本。
2. 如果已有 `scripts/run_grpcio_tools.sh`，优先在原脚本上修改；只有项目没有生成脚本时才创建新脚本。
3. 使用当前项目的 Python 环境执行命令。Poetry 项目中，Python 命令使用 `poetry run python`。
4. 缺少生成工具时使用 `python -m pip install ...` 安装；不要用 `poetry add` 安装 `grpcio-tools` 或 `mypy-protobuf`。
5. 确保 `grpcio-tools` 版本与已安装的 `grpcio` 版本完全一致。
6. 修改后在可行时运行脚本，并检查生成文件位置是否正确。

## 内置 proto 说明

本技能目录下的 `protos/` 包含一组常用语音服务协议，理解用途后再选择生成或接入：

- `protos/engine.proto`：综合引擎协议，包含 VAD、SID 特征提取、训练、比对、聚类和扩展分析。由于各方法之间存在较大冗余，接入时建议优先只使用 `Feature`，它主要用于基于 `sidAlg` 从 PCM 提取 SID 特征；`Compare` 可能有效，可按实际服务验证后使用；`FeatureWav`、`CompareWav` 等 Wav 系列以及其他方法一般不建议使用。`Extended` 可结合 `lidAlg`、`gidAlg` 做扩展结果输出。
- `protos/lid.proto`：语言识别协议，`Process` 输入 PCM 及采样参数后直接返回分类结果 `lang` 和置信分数 `score`；`GetLanguages` 返回可用语言映射。
- `protos/ux_vad.proto`：语音活动检测协议，支持离线 `Detect` 和在线双向流式 `StreamingDetect`。在线接口可能是同步帧级输出：某一帧输入后如果暂时找不到语音开始或结束，返回的左边界或右边界可能小于 0，常见值为 `-1`。
- `protos/ux_speech.proto`：流式语音识别协议，首包发送 `StreamingRecognitionConfig`，后续发送音频；响应包含转写文本、词级时间戳、临时/最终结果标记，以及说话人、语种、说话人切换和轮次完成等扩展信息。
- `protos/ux_denoise.proto`：语音降噪协议，支持离线 `Denoise` 和流式 `StreamingDenoise`，输入输出都通过编码和采样率配置描述，音频负载为 PCM bytes。
- `protos/ux_speaker_diarization.proto`：说话人分离协议，支持 PCM bytes 和 wav 路径输入，输出多个带开始时间、结束时间和 speaker 编号的片段。
- `protos/text_postprocess.proto`：文本后处理协议，输入原始文本，输出处理后的文本，适合标点、格式规整、文本规范化等后处理链路。

## 依赖规则

从当前 Python 环境读取包元数据：

- 确保已安装 `grpcio`；如果缺失，使用 `python -m pip install grpcio` 安装。
- 读取已安装的 `grpcio` 版本。
- 确保 `grpcio-tools` 与 `grpcio` 版本一致；如果缺失或版本不一致，安装 `grpcio-tools==${GRPCIO_VERSION}`。
- 确保已安装 `mypy-protobuf`；如果缺失，使用 `python -m pip install mypy-protobuf` 安装。

Poetry 项目也遵循同样规则，但 Python 命令需要通过 Poetry 执行：

```bash
poetry run python -m pip install grpcio
poetry run python -m pip install "grpcio-tools==${GRPCIO_VERSION}"
poetry run python -m pip install mypy-protobuf
```

不要执行：

```bash
poetry add grpcio-tools mypy-protobuf
```

## 脚本模式

`scripts/run_grpcio_tools.sh` 推荐使用以下结构，并根据项目布局调整 `PROTO_ROOT` 和 `OUT_DIR`：

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

if command -v poetry >/dev/null 2>&1 && [[ -f "pyproject.toml" ]]; then
  PYTHON=(poetry run python)
else
  PYTHON=(python)
fi

python_pkg_version() {
  "${PYTHON[@]}" - "$1" <<'PY'
from __future__ import annotations

import importlib.metadata
import sys

try:
    print(importlib.metadata.version(sys.argv[1]))
except importlib.metadata.PackageNotFoundError:
    raise SystemExit(1)
PY
}

ensure_package() {
  local package_name="$1"
  local install_spec="${2:-$1}"

  if ! python_pkg_version "${package_name}" >/dev/null 2>&1; then
    "${PYTHON[@]}" -m pip install "${install_spec}"
  fi
}

ensure_package grpcio
GRPCIO_VERSION="$(python_pkg_version grpcio)"

if ! GRPCIO_TOOLS_VERSION="$(python_pkg_version grpcio-tools 2>/dev/null)"; then
  "${PYTHON[@]}" -m pip install "grpcio-tools==${GRPCIO_VERSION}"
elif [[ "${GRPCIO_TOOLS_VERSION}" != "${GRPCIO_VERSION}" ]]; then
  "${PYTHON[@]}" -m pip install "grpcio-tools==${GRPCIO_VERSION}"
fi

ensure_package mypy-protobuf

PROTO_ROOT="${PROTO_ROOT:-protos}"
OUT_DIR="${OUT_DIR:-src}"

mkdir -p "${OUT_DIR}"
mapfile -t PROTO_FILES < <(find "${PROTO_ROOT}" -type f -name '*.proto' | sort)

if [[ "${#PROTO_FILES[@]}" -eq 0 ]]; then
  echo "No proto files found under ${PROTO_ROOT}" >&2
  exit 1
fi

"${PYTHON[@]}" -m grpc_tools.protoc \
  -I "${PROTO_ROOT}" \
  --python_out="${OUT_DIR}" \
  --grpc_python_out="${OUT_DIR}" \
  --mypy_out="${OUT_DIR}" \
  --mypy_grpc_out="${OUT_DIR}" \
  "${PROTO_FILES[@]}"
```

## 路径选择

- 对于 `protos/*.proto` 且生成代码放在 `src` 下的项目，使用 `PROTO_ROOT=protos` 和 `OUT_DIR=src`。
- 对于 `src/<package>/protos/**/*.proto`，通常使用 `PROTO_ROOT=src` 和 `OUT_DIR=src`，让生成文件保留在包路径内。
- 选择 include root 时，应让 `.proto` 内部 import 能正常解析；除非用户明确要求重构，否则不要改写 proto import。

## 验证

在网络和环境条件允许时，修改后运行生成脚本：

```bash
bash scripts/run_grpcio_tools.sh
```

检查每个输入 `.proto` 是否生成：

- `*_pb2.py`
- `*_pb2.pyi`
- `*_pb2_grpc.py`
- `*_pb2_grpc.pyi`
