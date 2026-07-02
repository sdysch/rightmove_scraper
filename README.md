# Rightmove Tracker

[![Last Scraper Run](https://img.shields.io/github/actions/workflow/status/sdysch/rightmove_scraper/scrape.yml?branch=main&label=Last%20run)](https://github.com/sdysch/rightmove_scraper/actions/workflows/scrape.yml)

Monitor Rightmove for new properties and price reductions. Get Telegram notifications when something changes.

## Table of Contents

- [How it works](#how-it-works)
- [Setup](#setup)
  - [1. Fork this repo](#1-fork-this-repo)
  - [2. Create a Telegram bot](#2-create-a-telegram-bot)
  - [3. Get your Rightmove search URL](#3-get-your-rightmove-search-url)
  - [4. Set up Supabase](#4-set-up-supabase)
  - [5. Set GitHub Secrets](#5-set-github-secrets)
  - [6. Enable the workflow](#6-enable-the-workflow)
- [What's public vs private](#whats-public-vs-private)
- [Optional: limit to recent listings](#optional-limit-to-recent-listings)
- [Local development](#local-development)
- [Project structure](#project-structure)

## How it works

1. Runs every hour via GitHub Actions cron
2. Scrapes your Rightmove search URL for all matching properties
3. Compares against previous state (stored in Supabase — private)
4. Sends a Telegram notification for:
   - **New properties** appearing on the market
   - **Price reductions** on existing listings

## Setup

### 1. Fork this repo

Click the Fork button at the top of this page.

### 2. Create a Telegram bot

1. Open Telegram and search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Save the **token** it gives you
4. Start a chat with your new bot (send any message)
5. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
6. Find your **chat ID** in the response (`"id":` field)

### 3. Get your Rightmove search URL

1. Go to [rightmove.co.uk](https://www.rightmove.co.uk) and search for properties
2. Apply your filters (location, radius, bedrooms, price range, property type)
3. Copy the full URL from your browser

This URL contains your search criteria (postcode, prices, etc.) and must be kept private.

### 4. Set up Supabase

1. Create a free account at [supabase.com](https://supabase.com)
2. Create a new project
3. Go to the **SQL Editor** and run the migration in `supabase/migrations/001_create_property_state.sql`
4. Go to **Project Settings → API** and copy your **Project URL** and **`service_role` key**

### 5. Set GitHub Secrets

In your forked repo, go to **Settings → Secrets and variables → Actions** and add:

| Secret | Value |
|---|---|
| `SEARCH_URL` | Your full Rightmove search URL |
| `TELEGRAM_TOKEN` | Your Telegram bot token |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID |
| `SUPABASE_URL` | Your Supabase project URL (e.g. `https://abc123.supabase.co`) |
| `SUPABASE_SERVICE_KEY` | Your Supabase `service_role` key |

### 6. Enable the workflow

Go to **Actions** in your repo and enable the workflow. It runs every hour on the hour.
You can also trigger it manually from the Actions tab with the **Run workflow** button.

## What's public vs private

**Public (in the repo):**
- The scraper code
- The workflow configuration

**Private (never in the repo):**
- Your Rightmove search URL (GitHub Secret)
- Your Telegram credentials (GitHub Secrets)
- Your Supabase credentials (GitHub Secrets)
- The property state database (Supabase, accessible only via service_role key)

## Optional: limit to recent listings

Add `&added=24` to the end of your `SEARCH_URL` to only fetch listings added or updated in the last 24 hours. This reduces requests but means you'll miss price drops on older listings that haven't been re-bumped. Remove the `_includeSSTC=on` parameter if you don't want to include Sold Subject to Contract.

## Local development

```bash
# 1. Install dependencies
uv sync

# 2. Copy the example env and fill in your values
cp .env.example .env
# Then edit .env with your Rightmove URL, Telegram creds, and Supabase creds

# 3. Run the tracker
uv run python rightmove_tracker.py
```

On the first run the script captures a baseline (no notifications sent).
Subsequent runs compare against Supabase and send Telegram notifications for new properties and price drops.

## Project structure

```
.
├── .env.example          # Template for local config (copy to .env)
├── .github/workflows/    # GitHub Actions hourly cron
├── pyproject.toml        # Python deps managed by uv
├── rightmove_tracker.py  # Main scraper + notifier
├── supabase/migrations/  # Database schema
└── tests/                # Pytest suite (32 tests)
```
