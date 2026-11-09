# Transfer-trap paper trading

`watch.py` watches the GE around the clock for suspected gold transfers (see
`docs/price-history-findings.md`) and keeps *imaginary* sell offers on the items most
likely to be used next, to test whether they'd be filled. No real offers are placed.

Results: **https://n-j-g.github.io/ge-tracker/paper/** (refreshes every 30 minutes).

## What it does each minute

- Reads the Wiki price API's latest trades (`/latest`) and 5-minute averages (`/5m`);
  each hour, the 1-hour averages (`/1h`) for every item's typical price (median of the
  past week). That is about 3 small requests a minute.
- Flags a transfer when a cheap item trades at 20× its typical price or more (and at
  least 50k each) with 10m+ gp above normal value.
- Runs two paper strategies, 8 offers each:
  - **Newest:** after each transfer, list that item for 7 days at half the price seen,
    holding twice the units.
  - **Recency score:** keep offers on the 8 items with the highest recent-transfer score
    (recent transfers count most, weighted by size), re-ranked as transfers come in.
- An offer counts as "up" 10 minutes after the transfer is detected (time to log in), and
  fills when a later 5-minute bucket on that item trades at or above our ask.
- Keeps raw minute-level trades for the ~760 transfer items (120 days) so the "test
  trades" question can be studied later.

## Setting up a server (about 15 minutes, all in a web browser)

You need three things: a place for the results, a key that lets the server write
there, and a small server.

**1. Make the results repository.** On GitHub, click **+** (top right) → **New
repository**. Name it `ge-paper-data`, choose **Public**, and leave every "Add …" box
unticked. Click **Create repository**.

**2. Make a key for the server.** GitHub → your picture (top right) → **Settings** →
**Developer settings** (bottom of the left menu) → **Personal access tokens** →
**Fine-grained tokens** → **Generate new token**.
- Name: `ge-paper server`; Expiration: 1 year (or what you like).
- Repository access: **Only select repositories** → `ge-paper-data`.
- Permissions → Repository permissions → **Contents: Read and write**.
- Click **Generate token** and copy it (it starts with `github_pat_`). This key can only
  change `ge-paper-data`, not your code.

**3. Make the server.** Any Ubuntu server works; DigitalOcean is the simplest:
- Sign up at digitalocean.com, then **Create** → **Droplets**.
- Region: any. Image: **Ubuntu 24.04 (LTS)**. Size: **Basic**, **Regular**, the cheapest
  plan (about $4–6 a month is plenty).
- Authentication: **Password** (pick any strong one; you shouldn't need it).
- Open **Advanced options** → tick **Add initialization scripts**. Open
  [`setup_server.sh`](setup_server.sh) (click **Raw**), copy all of it, paste it into the
  box, and replace `PASTE_TOKEN_HERE` with the token from step 2 (keep the quotes).
- Click **Create Droplet**.

**4. Check it.** After about 10 minutes (it first downloads a week of prices), the
results page should say "Updated … min ago".

Code changes pushed to GitHub reach the server within an hour on their own.

## If something goes wrong

- **The page says "No results yet" after 20 minutes:** usually the token (wrong
  repository, or Contents not set to Read and write). Make a new token, then in
  DigitalOcean destroy the droplet and create it again with the new token (it's cheaper
  than fixing it by hand).
- **The page says "No update for …":** the server is off or stuck. In DigitalOcean,
  open the droplet → **Power** → **Power cycle**.
- **Stopping:** destroy the droplet in DigitalOcean (billing stops) and delete the
  token on GitHub.

## Running it on a Mac instead (free, while it's awake)

```
cd ~/Desktop/ge-tracker
caffeinate -i python3 -m live.watch --data ~/paper-data
```
Results go to `~/paper-data/publish/` (not online, unless `PAPER_PUSH_URL` is set).
