#!/usr/bin/env bash
#
# One-time backfill for the wallpaper gallery's "newest first" sort.
#
# Run this from the ROOT of a local clone of the Blapples/wallpapers repo
# (i.e. `git clone` it first, then `cd` into it and run this script from
# there). It reads your own local git history directly - there is no
# network call and no API rate limit involved at all - to find, for every
# image, the date it was first added to the repo (following renames).
#
# Output: backfill-dates.json in the current directory, shaped like:
#   { "filename.png": 1699999999000, ... }
# (values are Unix epoch milliseconds - "how JS understands a date")
#
# What to do with the output:
#   1. Open backfill-dates.json.
#   2. Open the gallery's .html file and find this line:
#        const BASELINE_CONFIRMED_DATES = {
#   3. Paste the *contents* of backfill-dates.json in between the { }
#      there (replacing the commented-out example line).
#   4. Save and re-upload/redeploy the .html file.
#
# From then on every device - including one that's never visited before -
# sorts the whole collection identically. Re-run this whenever you want to
# fold newly-learned dates permanently into the shared baseline instead of
# relying on the live GitHub check to keep re-discovering them at runtime.

set -euo pipefail

outfile="backfill-dates.json"
tmpfile="$(mktemp)"
trap 'rm -f "$tmpfile"' EXIT

if [ ! -d .git ]; then
  echo "error: run this from the root of your local clone of the repo (no .git folder found here)" >&2
  exit 1
fi

# If your wallpaper images live in a subfolder instead of the repo root,
# change "." below to that folder's path (e.g. "wallpapers").
SEARCH_DIR="."

echo "Scanning $SEARCH_DIR for images and walking git history for each one..."
echo "(this can take a little while for a large collection - it's one git-log call per file)"

count=0
find "$SEARCH_DIR" -maxdepth 1 -type f \
    \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.webp' -o -iname '*.gif' \) \
    -print0 \
  | sort -z \
  | while IFS= read -r -d '' f; do
      fname="$(basename "$f")"
      # %at = author date as a Unix timestamp in seconds. --follow tracks
      # the file across renames. --diff-filter=A restricts to commits
      # where the file was *added* (not just edited). `tail -1` takes the
      # earliest such commit, since git log lists newest-first.
      epoch_s="$(git log --follow --diff-filter=A --format=%at -- "$f" | tail -1)"
      if [ -n "$epoch_s" ]; then
        printf '%s\t%s\n' "$fname" "$((epoch_s * 1000))" >> "$tmpfile"
      else
        echo "  (skipping $fname - couldn't find an 'added' commit for it, e.g. if it was only ever renamed)" >&2
      fi
    done

{
  echo "{"
  awk -F'\t' '
    { lines[NR] = $0 }
    END {
      for (i = 1; i <= NR; i++) {
        split(lines[i], parts, "\t")
        printf("  \"%s\": %s", parts[1], parts[2])
        if (i < NR) printf(",")
        printf("\n")
      }
    }
  ' "$tmpfile"
  echo "}"
} > "$outfile"

total="$(wc -l < "$tmpfile" | tr -d ' ')"
echo "Done - wrote dates for $total file(s) to $outfile"
