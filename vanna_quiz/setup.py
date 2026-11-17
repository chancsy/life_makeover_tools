"""
Region Setup — Life Makeover Vvanna Quiz
Run this once per device. Regions are saved to config.json keyed by device serial,
so subsequent runs on the same device skip setup automatically.

Usage:
    python setup.py
    python setup.py --redo    ← force redo even if device is already configured
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from common.lm_tool import register_device

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')

QUIZ_REGIONS = ['question', 'A', 'B', 'C', 'D']


def main():
    result = register_device(CONFIG_PATH, QUIZ_REGIONS, 'a quiz question',
                             redo='--redo' in sys.argv)
    if result and result[3]:
        print('Setup complete. Run main.py to start the quiz.')


if __name__ == '__main__':
    main()
