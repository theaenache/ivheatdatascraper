# Imperial Valley Heat Death Scraper - User Guide

## Overview

This scraper collects heat-related death reports from Imperial Valley news sources using:
- **newspaper4k** for intelligent article extraction
- **BeautifulSoup4** for HTML parsing
- **Bilingual support** (English & Spanish)
- **Comprehensive keyword matching** with weighted scoring
- **SQLite database** for organized storage

---

## Installation

### 1. Install Required Packages

```bash
pip install newspaper4k beautifulsoup4 requests lxml --break-system-packages
```

**Package Purposes:**
- `newspaper4k` - Smart article extraction (maintained fork of newspaper3k)
- `beautifulsoup4` - HTML parsing
- `requests` - HTTP requests
- `lxml` - Fast XML/HTML parsing

### 2. Download the Scraper

Save `imperial_valley_scraper.py` to your working directory.

---

## Quick Start

### Basic Usage

```bash
python imperial_valley_scraper.py
```

This will:
1. Create database: `imperial_valley_heat_deaths.db`
2. Scrape all configured news sources
3. Save relevant articles (heat score > 0)
4. Generate report: `scraping_report.txt`
5. Create log: `scraper.log`

---

## Configuration

### Adjust Rate Limiting

In the scraper file, modify:

```python
REQUEST_DELAY = 12  # seconds between requests
MAX_ARTICLES_PER_SOURCE = 50  # articles per source per session
```

**Recommended settings:**
- Academic research: 10-15 seconds
- Personal use: 15-20 seconds
- Be conservative to avoid being blocked!

### Add/Remove News Sources

Edit the `NEWS_SOURCES` list:

```python
NEWS_SOURCES = [
    {
        'name': 'Your News Source',
        'url': 'https://example.com',
        'sections': ['/news/', '/local/'],
        'language': 'en',  # or 'es'
        'bias': 'LOCAL-UNRATED'
    }
]
```

### Customize Keywords

Modify keyword dictionaries in the script:

```python
KEYWORDS_EN = {
    'primary_death': {
        'keywords': [r'heat\s+death', ...],
        'weight': 10
    }
}
```

---

## Database Schema

### Tables

**1. articles** - Main article storage
```sql
- id, source, source_bias, language
- url, title, authors, published_date
- text_content, heat_score, category
```

**2. keyword_matches** - Detailed keyword tracking
```sql
- article_id, keyword, keyword_type
- match_count, weight
```

**3. scrape_sessions** - Session logs
```sql
- source, start_time, end_time
- articles_found, articles_scraped, errors
```

**4. error_log** - Error tracking
```sql
- timestamp, source, url
- error_type, error_message
```

### Querying the Database

```python
import sqlite3

conn = sqlite3.connect('imperial_valley_heat_deaths.db')
cursor = conn.cursor()

# Get all highly relevant articles
cursor.execute('''
    SELECT title, source, heat_score 
    FROM articles 
    WHERE category = 'HIGHLY_RELEVANT'
    ORDER BY heat_score DESC
''')

for title, source, score in cursor.fetchall():
    print(f"[{score:.1f}] {title} - {source}")
```

---

## Understanding Heat Scores

### Scoring System

| Keyword Type | Weight | Examples |
|--------------|--------|----------|
| **Primary Death** | 10 | "heat-related death", "died from heat" |
| **Location Specific** | 8 | "homeless...heat death", "found in car...heat" |
| **Contextual Death** | 7 | "found dead...heat", "extreme heat...died" |
| **Heat Illness** | 5 | "heat stroke", "heat exhaustion" |
| **Medical/Coroner** | 3 | "coroner...heat", "autopsy...heat" |
| **Environmental** | 2 | "heat wave", "excessive heat warning" |

### Relevance Categories

| Score Range | Category | Meaning |
|-------------|----------|---------|
| **50+** | EXTREMELY_RELEVANT | Clear heat death case |
| **20-49** | HIGHLY_RELEVANT | Likely heat-related incident |
| **10-19** | MODERATELY_RELEVANT | Heat context present |
| **1-9** | MINIMALLY_RELEVANT | Tangential heat mention |
| **0** | NOT_RELEVANT | No heat-related content |

### Example Scoring

Article: "Three heat-related deaths reported during heat wave"

```
Matches found:
- "heat-related death" × 1 = 10 points (primary)
- "heat wave" × 1 = 2 points (environmental)

Total Score: 12 → MODERATELY_RELEVANT
```

---

## Output Files

### 1. Database: `imperial_valley_heat_deaths.db`
- SQLite database with all articles
- Query with any SQLite tool or Python
- Portable, can share with collaborators

### 2. Report: `scraping_report.txt`
- Summary statistics
- Articles by source, relevance, language
- Top 10 most relevant articles

### 3. Log: `scraper.log`
- Timestamped scraping activity
- Errors and warnings
- Useful for debugging

---

## Best Practices

### Before First Run

1. **Check robots.txt** for each source:
   ```
   https://www.ivpressonline.com/robots.txt
   https://calexicochronicle.com/robots.txt
   ```

2. **Review Terms of Service**

3. **Start with one source** for testing:
   ```python
   NEWS_SOURCES = [NEWS_SOURCES[0]]  # Just IV Press
   ```

4. **Limit articles** during testing:
   ```python
   MAX_ARTICLES_PER_SOURCE = 10
   ```

### Running Regularly

```bash
# Run once per day via cron (Linux/Mac)
0 2 * * * /usr/bin/python3 /path/to/imperial_valley_scraper.py

# Or Task Scheduler (Windows)
# Run at 2 AM daily
```

### Monitoring

Check the log file regularly:
```bash
tail -f scraper.log  # Watch in real-time
grep ERROR scraper.log  # Find errors
```

---

## Troubleshooting

### "newspaper4k not found"
```bash
pip install newspaper4k --break-system-packages
```

### "Connection refused" or "Blocked"
- **Increase REQUEST_DELAY** to 20+ seconds
- **Reduce MAX_ARTICLES_PER_SOURCE**
- Wait 24 hours before trying again
- Check if site blocked your IP

### "No articles found"
- Check if website structure changed
- Verify sections URLs are correct
- Check scraper.log for details

### "Score always 0"
- Articles might not contain heat keywords
- Try broader keyword patterns
- Check if language setting is correct

---

## Advanced Usage

### Filter by Date Range

```python
# After scraping, query specific dates
cursor.execute('''
    SELECT * FROM articles
    WHERE published_date BETWEEN '2024-06-01' AND '2024-09-30'
    AND heat_score >= 20
''')
```

### Export to CSV

```python
import csv

cursor.execute('SELECT * FROM articles WHERE heat_score > 0')
rows = cursor.fetchall()

with open('heat_deaths.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(['ID', 'Source', 'Title', 'Score', 'Date', 'URL'])
    for row in rows:
        writer.writerow([row[0], row[1], row[6], row[12], row[8], row[4]])
```

### Combine with Maricopa County Data

```python
# Use IV scraper data to validate against Maricopa ground truth
# Compare dates, demographics, environmental conditions
```

---

## Legal & Ethical Considerations

✅ **DO:**
- Respect robots.txt
- Use conservative rate limiting
- Identify yourself in User-Agent
- Attribute sources properly
- Use data for research only

❌ **DON'T:**
- Overwhelm servers with requests
- Ignore robots.txt
- Republish scraped content
- Use for commercial purposes without permission
- Share full article texts publicly

---

## Support & Feedback

- Check `scraper.log` for errors
- Review `DEMO_RESULTS.md` for validation
- See `heat_research_setup.md` for full research context

---

**Last Updated:** February 2026
