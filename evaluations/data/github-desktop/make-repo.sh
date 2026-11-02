#!/bin/bash
# The notes-app repository at $1: 4 commits by 2 authors, 2 more branches, 2 modified files, and 1 untracked file.
set -euo pipefail
mkdir -p "$1"
cd "$1"
git init -q

commit() {
    GIT_AUTHOR_NAME=$1 GIT_AUTHOR_EMAIL=$2 GIT_AUTHOR_DATE=$3 \
        GIT_COMMITTER_NAME=$1 GIT_COMMITTER_EMAIL=$2 GIT_COMMITTER_DATE=$3 git commit -qm "$4"
}

printf '# Notes App\n\nA tiny notes app.\n' > README.md
git add .
commit "Alice Admin" alice@example.com 2026-09-01T10:00:00 "Initial commit"

mkdir src
printf 'def add_note(notes, text):\n    notes.append(text)\n    return notes\n' > src/notes.py
git add .
commit "Bob Builder" bob@example.com 2026-09-05T11:00:00 "Add note storage"

printf 'def count(notes):\n    return len(notes)\n' > src/stats.py
git add .
commit "Alice Admin" alice@example.com 2026-09-10T12:00:00 "Add stats helper"

git branch feature/search
git branch fix/typo

printf '*.pyc\n__pycache__/\n' > .gitignore
git add .
commit "Bob Builder" bob@example.com 2026-09-12T09:30:00 "Ignore Python caches"

printf '# Notes App\n\nA tiny notes app for quick notes.\n' > README.md
printf 'def add_note(notes, text):\n    notes.append(text.strip())\n    return notes\n' > src/notes.py
printf 'Meeting notes\n- ship v1\n' > "meeting notes.txt"
