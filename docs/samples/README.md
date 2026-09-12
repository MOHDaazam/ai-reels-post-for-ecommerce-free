# Sample media for the GitHub README

GitHub’s README renderer **does not play** MP4 files from `docs/…` or `raw.githubusercontent.com`—only from **`github.com/user-attachments/assets/…`** ([docs](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/attaching-files)).

To refresh the README embed after re-cutting the sample:

```bash
# GitHub CLI 2.99+ required (~/.local/bin/gh)
gh issue comment 1 -R MOHDaazam/ai-reels-post-for-ecommerce-free \
  --body-file docs/samples/readme-upload-body.md \
  --attach docs/samples/sample-reel-biryani-poster.jpg \
  --attach docs/samples/sample-reel-biryani-readme.mp4
```

Copy the new `user-attachments` URLs from the comment into `README.md` (`poster=` + `src=`).

- `sample-reel-biryani-readme.mp4` — H.264 preview under 10 MB (free-plan upload limit)
- `sample-reel-biryani.mp4` — full-quality local export (not used on GitHub README)
