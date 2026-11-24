# withoutvisit — copy something, send it on.

import os
import sys

_APP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app")
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from clip_app import main_clip


if __name__ == "__main__":
    main_clip()
