"""
Run the game from anywhere:

    python -m husk            (from the project root)
    python husk/__main__.py   (or the editor's Run button on this file)

The second form runs this file as a plain script, where the package-relative
imports inside husk/ would fail — so the project root goes on sys.path first.
"""

import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from husk.app import Game

if __name__ == "__main__":
    Game().run()
