# Discogs Collection Liquidity Analyzer

A simple tool for Discogs collectors to understand **which records are likely to sell fastest**.

Instead of guessing based on price alone, this script looks at real Discogs marketplace activity and ranks records by **liquidity** — how easy they are to sell right now.

---

## 🚀 Quick Start

If you already have Python installed:

```bash
git clone https://github.com/yourusername/discogs-liquidity-analyzer.git
cd discogs-liquidity-analyzer
python3 -m venv venv
source venv/bin/activate   # Windows: .\venv\Scripts\Activate.ps1
pip install pandas requests python-dotenv
```

Create a .env file

DISCOGS_TOKEN=your_discogs_token_here

Run the script (if no category/folder is passed it defaults to one called "selling"
```bash
python3 app.py --user yourusername
```
You'll Get:

collection-output-MMDDYYYY.csv

What This Tool Is For

This script helps with:

		“What records should I list first?”
		“Which items are likely to sell quickly vs sit?”

## What the Script Does;

When you run it, the script:

	1.	Loads a Discogs collection Directly from Discogs (recommended), or from a Discogs CSV export
	2.	Filters by folder (selling, keepers, or all)
	3.	Looks up live Discogs data:
	•	How many people want the record
	•	How many people own it
	•	How many copies are currently for sale
	•	The lowest current listing price
	4.	Calculates a liquidity score
	5.	Ranks records by sell priority
	6.	Writes output to a CSV file.

It works for:

		Your own collection
		Another user’s public collection
		Either live API data or a CSV export

## What “Liquidity” Means

Liquidity = how quickly and easily a record is likely to sell.
A record that sells tomorrow for $30 is more liquid than a $200 record that sits unsold for months.
This tool focuses on sellability, not maximum value.

## How the Liquidity Score Works

The score is based only on data Discogs makes available via its API:

		Want count (demand)
		Have count (supply already owned)
		Number of active listings
		Whether Discogs allows the item to be sold

In simple terms:

	•	High want + low have → higher score
	•	Active listings → healthier market
	•	No listings → harder to price and sell
	•	Blocked items → effectively unsellable

The score is relative, not absolute.
It’s meant to rank items within the same run, not compare across collections.


## Limitations

❌ No Median or High Prices

Discogs does not expose median or high sale prices via the API.

Because of this:

	•	Only the lowest current listing price is included
	•	Median / high prices are not calculated or estimated
	•	Final pricing decisions are still manual

❌ Private Collections Are Not Accessible:

	•	Being “friends” on Discogs does not grant access
	•	Only public collections and public folders can be fetched
	•	Folder privacy settings matter

## Setup Instructions

## Create a Virtual Environment

#### macOS / Linux
```bash
python3 -m venv venv
source venv/bin/activate
```
### Windows (powershell)
```bash
python -m venv venv
.\venv\Scripts\Activate.ps1
```

## Install Dependancies
```bash
pip install pandas requests python-dotenv
```

## Discogs API Setup
	1.	Go to https://www.discogs.com/settings/developers
	2.	Create a Personal Access Token
	3.	Create a .env file in the project root:
	
	DISCOGS_TOKEN=your_discogs_token_here

### Command line usage (running with no arguements prints usage)
	python3 app.py

## API Mode (Recommended)


#### Fetch your Selling folder (default):
	
	python3 app.py --user username
#### Fetch a specific folder

	python3 app.py --user username --category keepers
#### Fetch all public folders

	python3 app.py --user username --category all

## CVS mode (optional) provide your exported discogs collection


	python3 app.py --source csv \
  	--input my_collection.csv \
 	 --category selling

## Caching & Performance

To stay within Discogs rate limits, the script uses a local cache.

Defaults:  
	-	Marketplace data refreshes every 24 hours  
	-	Want/Have counts refresh every 14 days

### Override Timing

	python3 app.py --user username --marketplace-ttl 3600

### Force everything to refresh

	python3 app.py --user username --marketplace-ttl 0 --release-ttl 0

	

	
