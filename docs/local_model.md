# Running MILO with a free local language model

MILO can work out new tasks with a model running on your own machine through [Ollama](https://ollama.com), with no API key and no cost. This page covers setup, how the model was chosen, how it shares the GPU with AI2-THOR, and what to do when something goes wrong. No result on this page comes from Claude.

**Chosen model: `qwen2.5:7b` (Q4_K_M).** It was the most accurate of four models on the DEV set, by 19 points.

## The machine (`results/hardware.json`, 2026-11-25)

| | |
|---|---|
| Laptop | ASUS TUF Gaming F16, Windows 11, MILO in WSL 2 |
| GPU | NVIDIA GeForce RTX 4050 Laptop GPU, 6 GB VRAM (5.9 GB free at rest) |
| CPU | 13th Gen Intel Core i7-13620H, 16 threads |
| RAM visible to WSL | 7.6 GB |
| Ollama | 0.40.16 on Windows |

## How the model was chosen (`make model-bakeoff`, 2026-11-25)

Each model ran the 30 DEV commands (`backend/novel/dev_set.py`) three times: seeds 0, 1 and 2, temperature 0, an 8,192-token context, and the same prompt and JSON schema. The 60-command TEST set was not used. A command counts as correct if:

- its plan runs and its goal checks pass in the synthetic home, or
- for an ambiguous command, MILO asks one question without acting, or
- for an impossible one, MILO refuses without acting.

| Model (Ollama tag, quantisation) | Correct (mean, spread over 3 runs) | Valid JSON | Plans passing the validator | Model calls per command | Seconds per command | Tokens per second | Peak VRAM |
|---|---|---|---|---|---|---|---|
| **qwen2.5:7b** (Q4_K_M) | **55.6%** (3.3 pts) | 95% | 83% | 1.51 | 12.2 | 23.8 | 4.0 GB |
| llama3.1:8b (Q4_K_M) | 36.7% (0) | 69% | 71% | 1.70 | 60.9 | 17.0 | 4.6 GB* |
| gemma4:e2b-it-qat | 33.3% (0) | 100% | 75% | 1.57 | **4.5** | **61.8** | **2.9 GB** |
| qwen3.5:4b (Q4_K_M) | 23.3% (0) | 100% | 62% | 1.62 | 6.2 | 39.5 | 4.7 GB* |

- **Pick:** correctness first, then speed, so qwen2.5:7b. Neither newer model beat it on this task. Gemma 4 e2b is about 3× faster and the smallest; it is the fallback if VRAM is tight, at 22 points less accuracy.
- **Truncation:** no prompt filled the context window. The largest was 1,924 tokens.
- **Peak VRAM** is sampled across the whole GPU (`nvidia-smi`). *For llama3.1 and qwen3.5 it varied by 1.2 GB between runs, most likely the previous model still loaded when a run started.
- **Discarded attempt:** a first bake-off used Ollama's default 4,096-token context. Some prompts were cut, so it was thrown away; none of its numbers are used.
- Per-run detail is in `results/bakeoff/`.

## Sharing the 6 GB GPU with AI2-THOR (smoke test, 2026-11-26)

`scripts/smoke_mission_with_model.py` ran one real AI2-THOR mission ("stash the apple in the fridge", FloorPlan1) with Grounding DINO, SAM2 and qwen2.5:7b all on the GPU. The model planned it, the script approved the plan preview as a user would, and MILO carried it out.

| `MILO_OLLAMA_KEEP_ALIVE` | Result | Time | Peak VRAM (of 6.14 GB) |
|---|---|---|---|
| `5m` (model stays loaded) | succeeded, 8 steps | 52.4 s | 5.87 GB |
| `0` (unload after each answer) | succeeded, 8 steps | 20.3 s | 5.77 GB |

Both fit, with little headroom. **Recommendation:** use `MILO_OLLAMA_KEEP_ALIVE=0` whenever AI2-THOR runs. The model leaves VRAM as soon as it has answered, and the vision models get it back. Each row is a single run; the faster unload run most likely benefited from the model file already sitting in the OS file cache.

## Setup

**1. Install Ollama.** On Windows, install it from ollama.com. On Linux or inside WSL, use the install script from the same site.

**2. Pull the model.**

```bash
ollama pull qwen2.5:7b
```

**3. Let WSL reach Ollama (Windows only).** Ollama on Windows listens on `127.0.0.1`, which WSL can't reach by default. Pick one of these:

- **Mirrored networking (simplest).** Add the following to `%UserProfile%\.wslconfig`, then run `wsl --shutdown`. After that, `http://localhost:11434` works from WSL.

  ```ini
  [wsl2]
  networkingMode=mirrored
  ```

- **A second Ollama server bound only to the WSL adapter.** In PowerShell:

  ```powershell
  $env:OLLAMA_HOST = "172.24.160.1:11434"   # the WSL adapter address: `ip route` in WSL shows it as "default via ..."
  & "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" serve
  ```

  Then set `MILO_OLLAMA_URL=http://172.24.160.1:11434` in WSL. This is how the numbers below were measured. Don't bind to `0.0.0.0`: that opens the model to your whole network.

- **Install Ollama inside WSL** and use `localhost`.

**4. Check the GPU and the connection.**

```bash
python scripts/detect_hardware.py
```

This writes `results/hardware.json`. Check that `ollama.running` is `true` and that your model is listed.

**5. Set the environment** in `backend/.env`:

| Setting | Value | What it does |
|---|---|---|
| `MILO_NOVEL_PROVIDER` | `ollama` | New tasks use the local model; falls back to offline if it can't be reached |
| `MILO_OLLAMA_MODEL` | `qwen2.5:7b` | Which model |
| `MILO_OLLAMA_URL` | `http://localhost:11434` | Where Ollama is |
| `MILO_OLLAMA_KEEP_ALIVE` | `5m` (`0` with AI2-THOR, see below) | How long the model stays in VRAM after an answer |
| `MILO_OLLAMA_NUM_CTX` | `8192` | Context window. Ollama's own default of 4,096 silently cut long prompts |

**6. Run one mission** with everything on the GPU:

```bash
cd backend
VISION_ENABLE_SIMULATOR=true MILO_NOVEL_PROVIDER=ollama MILO_OLLAMA_KEEP_ALIVE=0 uvicorn api.app:app --port 8000
# in another terminal, from the repo root:
python scripts/smoke_mission_with_model.py "stash the apple in the fridge"
```

The smoke script prints the outcome, the time and the peak VRAM.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| CUDA out of memory, or AI2-THOR crashes when a new task starts | The model and the vision models don't both fit in 6 GB | `MILO_OLLAMA_KEEP_ALIVE=0` unloads the model after each answer; or use a smaller model; or keep the model on the CPU (slower) |
| The first answer takes 30-60 s | The model is loading from disk | Normal the first time; later loads come from the OS cache and take a few seconds |
| Every answer is slow | Part of the model runs on the CPU because it didn't fit in VRAM | Free VRAM, or use a 4B model |
| Odd answers that ignore the instructions | The prompt is longer than the context window, so its start is cut | Keep `MILO_OLLAMA_NUM_CTX` at 8192 or more; the bake-off reports `context_full` |
| An answer runs for ~40 s and is rejected | The model rambled to the 1,024-token cap (`num_predict`) | It is retried and counted; a known weakness of small models with forced JSON |
| "isn't installed (run: ollama pull ...)" | The model isn't pulled | Run the command it gives |
| MILO says it can't work out new tasks offline | Ollama isn't reachable, so MILO fell back to offline | Check `MILO_OLLAMA_URL` and run `scripts/detect_hardware.py` |
