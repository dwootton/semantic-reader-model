#!/usr/bin/env bash
# Invoked inside the private training container after a successful student run.
set -euo pipefail
TRAIN_PYTHON="$1"
TRAIN_RUN="$2"
EXPORT_OUTPUT="$3"
LLAMA_REVISION=5f436dddb440a288ee5611d7d1eca564a6aca9f4
EXPORT_ROOT=$(mktemp -d /tmp/semantic-reader-export.XXXXXX)
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends git cmake build-essential libcurl4-openssl-dev
git init -q "$EXPORT_ROOT/llama.cpp"
git -C "$EXPORT_ROOT/llama.cpp" remote add origin https://github.com/ggml-org/llama.cpp.git
git -C "$EXPORT_ROOT/llama.cpp" fetch -q --depth=1 origin "$LLAMA_REVISION"
git -C "$EXPORT_ROOT/llama.cpp" checkout -q --detach FETCH_HEAD
cmake -S "$EXPORT_ROOT/llama.cpp" -B "$EXPORT_ROOT/llama.cpp/build" \
  -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=OFF -DGGML_NATIVE=OFF \
  -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_TOOLS=ON
cmake --build "$EXPORT_ROOT/llama.cpp/build" --config Release --target llama-quantize -j 8
"$TRAIN_PYTHON" -m venv "$EXPORT_ROOT/venv"
EXPORT_PYTHON="$EXPORT_ROOT/venv/bin/python"
# The converter pins a different torch/transformers pair. Keep it separate from training.
"$EXPORT_PYTHON" -m pip install --disable-pip-version-check \
  torch==2.11.0 --index-url https://download.pytorch.org/whl/cpu
"$EXPORT_PYTHON" -m pip install --disable-pip-version-check \
  -r "$EXPORT_ROOT/llama.cpp/requirements/requirements-convert_hf_to_gguf.txt" \
  peft==0.19.1 accelerate==1.12.0
"$EXPORT_PYTHON" -m training.export --run "$TRAIN_RUN" --output "$EXPORT_OUTPUT" \
  --llama-cpp "$EXPORT_ROOT/llama.cpp" --llama-cpp-revision "$LLAMA_REVISION" --apply
