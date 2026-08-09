"""
test_navigation.py

Purpose
-------
Simple integration test for the simulator wrapper.

This script verifies that:

- Unity launches
- The robot can move
- The wrapper methods work correctly
- RGB images and metadata are accessible

Run this before building the planner or vision system.
"""

import time

from simulator.simulator import Simulator


def main():

    sim = Simulator()

    sim.start()

    print("Simulator started.")

    time.sleep(2)

    print("Move Ahead")
    sim.move_ahead()
    time.sleep(1)

    print("Turn Left")
    sim.turn_left()
    time.sleep(1)

    print("Move Ahead")
    sim.move_ahead()
    time.sleep(1)

    print("Turn Right")
    sim.turn_right()
    time.sleep(1)

    metadata = sim.get_metadata()

    print()

    print("Agent Position")

    print(metadata["agent"]["position"])

    print()

    print("Agent Rotation")

    print(metadata["agent"]["rotation"])

    rgb = sim.get_rgb()

    print()

    print("RGB Shape")

    print(rgb.shape)

    sim.stop()

    print()

    print("Finished")


if __name__ == "__main__":
    main()
