#!/usr/bin/env python3
import os
from openpilot.common.basedir import BASEDIR
from openpilot.system.ui.lib.multilang import TRANSLATIONS_DIR, multilang
from openpilot.selfdrive.ui.translations.potools import extract_strings, generate_pot, merge_po, init_po

LANGUAGES_FILE = os.path.join(str(TRANSLATIONS_DIR), "languages.json")
POT_FILE = os.path.join(str(TRANSLATIONS_DIR), "app.pot")

# Directories that may contain tr()/trn()/tr_noop() calls. Every UI tree that
# ships user-visible text must be listed here, otherwise its strings never make
# it into app.pot and get dropped from the .po files on the next merge.
SCAN_DIRS = [
  "system/ui",
  os.path.join("selfdrive", "ui", "widgets"),
  os.path.join("selfdrive", "ui", "layouts"),
  os.path.join("selfdrive", "ui", "onroad"),
  os.path.join("selfdrive", "ui", "sunnypilot"),
  os.path.join("selfdrive", "ui", "mici"),
  os.path.join("selfdrive", "ui", "bp"),
  os.path.join("selfdrive", "ui", "body"),
  os.path.join("selfdrive", "ui", "feedback"),
  os.path.join("selfdrive", "ui", "installer"),
  "bluepilot",
]


def update_translations():
  files = []
  for rel in SCAN_DIRS:
    for root, _, filenames in os.walk(os.path.join(BASEDIR, rel)):
      for filename in filenames:
        if filename.endswith(".py"):
          files.append(os.path.relpath(os.path.join(root, filename), BASEDIR))

  # Extract translatable strings and generate .pot template
  entries = extract_strings(files, BASEDIR)
  generate_pot(entries, POT_FILE)

  # Generate/update translation files for each language
  for name in multilang.languages.values():
    po_file = os.path.join(TRANSLATIONS_DIR, f"app_{name}.po")
    if os.path.exists(po_file):
      merge_po(po_file, POT_FILE)
    else:
      init_po(POT_FILE, po_file, name)


if __name__ == "__main__":
  update_translations()
