
# IBS Marketplace

A campus-only peer-to-peer marketplace for ICFAI Business School students.

## Core features

- Google OIDC sign-in restricted to `@ibsindia.org`
- Buy / Sell / Rent / Trade
- Categories for books, stationery, electronics, appliances and hostel essentials
- Multi-parameter filters
- Hostel block tagging: A, B, C, D, E, F, G, H, T
- Safe meetup zones including Library Reading Room
- Visual image-search using perceptual hashes
- AI-assisted fair-price estimation using condition, age and historical campus transactions
- Private campus chat with automatic polling
- AI negotiation assistant using a seller-only private price floor
- Watchlist
- Completed transaction records
- Peer ratings

## Architecture

Streamlit is the UI and application layer. Supabase provides the persistent Postgres database. Google OIDC handles campus authentication. OpenAI is optional for the two AI assistants.

## Setup

1. Create a Supabase project.
2. Run `schema.sql` once in the Supabase SQL Editor.
3. Create a Google OAuth Web Application in Google Auth Platform.
4. Add the deployed Streamlit URL + `/oauth2callback` as an authorized redirect URI.
5. Configure the Google OIDC client for the IBS Google Workspace domain.
6. Put secrets in Streamlit Cloud Settings → Secrets. Never commit `secrets.toml`.
7. Deploy `app.py` from GitHub.

Streamlit's native `st.login()` uses OpenID Connect, and Google exposes the hosted-domain (`hd`) claim that the app verifies before granting access.
