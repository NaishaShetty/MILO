"""
test_sam2.py

Purpose
-------
Verifies that SAM2 loads correctly.

Checks

- processor
- model
- CUDA
- ModelManager integration

No segmentation yet.
"""

import torch

from vision.segmenters.sam2_segmenter import SAM2Segmenter


def main():

    SAM2Segmenter()

    print()

    print("CUDA Available :", torch.cuda.is_available())

    if torch.cuda.is_available():
        print("GPU :", torch.cuda.get_device_name(0))

    print()

    print("SAM2 initialized successfully.")


if __name__ == "__main__":
    main()
