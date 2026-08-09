"""
test_vision.py

Purpose
-------
This script verifies that the Vision Agent can successfully retrieve
images from the simulator.

Why it is needed
----------------
Before adding AI models like Grounding DINO, we first ensure that the
Vision Agent correctly receives images from the simulator.

This confirms that the perception pipeline is functioning.
"""

from simulator.simulator import Simulator
from vision.vision_agent import VisionAgent


def main():

    simulator = Simulator()

    simulator.start()

    print("Simulator started.")

    vision = VisionAgent(simulator)

    image = vision.get_rgb_image()

    print("Image Shape")

    print(image.shape)

    vision.save_image()

    print("Vision test completed successfully.")

    simulator.stop()

    print("Finished")


if __name__ == "__main__":
    main()
