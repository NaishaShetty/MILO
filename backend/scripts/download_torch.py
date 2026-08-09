"""
download_torch.py

Purpose
-------
Downloads the PyTorch wheel using Python requests instead of pip.

Why
---
Your environment can download using requests but pip's downloader
fails with SSL record layer errors.

After downloading the wheel once, we'll install it locally.
"""

import requests

url = "https://download.pytorch.org/whl/cu124/torch-2.5.1%2Bcu124-cp39-cp39-linux_x86_64.whl"

filename = "torch-2.5.1+cu124-cp39-cp39-linux_x86_64.whl"

response = requests.get(url, stream=True)

response.raise_for_status()

total = int(response.headers.get("content-length", 0))

downloaded = 0

with open(filename, "wb") as f:

    for chunk in response.iter_content(chunk_size=1024 * 1024):

        if chunk:

            f.write(chunk)

            downloaded += len(chunk)

            print(
                f"{downloaded/1024/1024:.1f} MB / {total/1024/1024:.1f} MB",
                end="\r",
            )

print("\nFinished downloading.")
