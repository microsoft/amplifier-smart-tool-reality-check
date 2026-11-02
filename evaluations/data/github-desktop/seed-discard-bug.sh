#!/bin/bash
# Makes "Discard changes..." on one file discard the file after it in the Changes list, or the first file when it
# is the last one, while the confirmation dialog still names the file the user chose.
# discard-next-file.source.patch is the same change in the app's source.
set -euo pipefail
renderer=${1:-/usr/lib/github-desktop/resources/app/renderer.js}
anchor='try{await r.discardChanges(t,n,i)}'
found=$(grep -oF "$anchor" "$renderer" | wc -l)
if [ "$found" -ne 1 ]; then
    echo "Expected the anchor once in $renderer, found it $found times: $anchor" >&2
    exit 1
fi
sed -i 's|try{await r\.discardChanges(t,n,i)}|try{const w=this.repositoryStateCache.get(e).changesState.workingDirectory.files,x=1===t.length?w.findIndex((f=>f.path===t[0].path)):-1;x>=0\&\&w.length>1\&\&(t=[w[(x+1)%w.length]]);await r.discardChanges(t,n,i)}|' "$renderer"
