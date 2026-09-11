# Contributing

Pull requests are welcome. This project is meant to stay **$0-friendly** by composing free tiers (Kaggle GPU, Edge TTS, local studio, optional Cloudflare quick tunnels)—not by hiding paid dependencies.

## Before you open a PR

1. Install dev deps: `pip install -e ".[dev]"`
2. Run tests: `pytest`
3. Run lint: `ruff check app tests kaggle_runner`
4. Keep secrets out of git (`.env`, `data/secrets/`, job outputs).

## Good first issues

- New ecommerce campaign templates (food, fashion, electronics, services).
- Festival calendars for more cities/languages.
- Trending Reels audio catalog entries (royalty-free or user-hosted HTTPS URLs).
- Docs, translations, and accessibility on the studio UI.

## Code of conduct

Be constructive. Review focus: correctness, cost awareness, and merchant-safe defaults (no burned-in spam text on footage).
