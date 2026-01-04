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
