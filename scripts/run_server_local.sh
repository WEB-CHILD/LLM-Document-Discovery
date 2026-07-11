#!/bin/bash

uv run vllm serve google/gemma-4-E4B-it --max-model-len 131072 --gpu-memory-utilization 0.85 --tool-call-parser gemma4 --enable-auto-tool-choice
