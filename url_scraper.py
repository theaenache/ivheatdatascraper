"""
URL LIST SCRAPER
================

Downloads and scores articles from a list of URLs.
No searching - just direct downloads.

Perfect for use with Wayback Machine extracted URLs!
"""

import sqlite3
import re
import hashlib
import time
import random
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import logging

try:
    from newspaper import Article, Config
except ImportError:
    print("ERROR: newspaper4k not installed.")
    print("Install with: pip install newspaper4k beautifulsoup4 requests lxml")
    exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('url_scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration
REQUEST_DELAY_MIN = 3
REQUEST_DELAY_MAX = 6
MIN_SCORE_THRESHOLD = 10

# Keywords (same as your working scraper)
KEYWORDS_EN = {
    'primary_death': {
        'keywords': [
            r'heat\s+death', r'heat-related\s+death', r'heat-caused\s+death',
            r'heat\s+fatality', r'died\s+from\s+heat', r'died\s+of\s+heat',
            r'heat\s+exposure\s+death', r'hyperthermia\s+death',
            r'heat\s+stroke\s+death', r'died\s+from\s+hyperthermia',
            r'succumbed\s+to\s+heat', r'heat\s+related\s+fatality',
            r'heat\s+victim', r'heat\s+casualty'
        ],
        'weight': 10
    },
    'heat_illness': {
        'keywords': [
            r'heat\s+stroke', r'heat\s+exhaustion', r'hyperthermia',
            r'heat\s+illness', r'heat\s+related\s+illness', r'heat\s+emergency',
            r'heat-associated', r'severe\s+dehydration'
        ],
        'weight': 5
    },
    'contextual_death': {
        'keywords': [
            r'found\s+dead.*heat', r'body\s+found.*heat',
            r'unresponsive.*heat', r'pronounced\s+dead.*heat',
            r'died\s+after.*heat\s+wave', r'succumbed.*heat',
            r'extreme\s+heat.*died'
        ],
        'weight': 7
    },
    'environmental': {
        'keywords': [
            r'excessive\s+heat\s+warning', r'heat\s+wave', r'extreme\s+heat',
            r'triple-digit\s+temperature', r'record\s+heat', r'blistering\s+heat',
            r'record\s+breaking\s+heat', r'dangerous\s+heat', r'heat\s+advisory',
            r'scorching\s+(?:heat|temperature)', r'heat\s+claims\s+lives',
            r'deadly\s+heat', r'heat\s+turns\s+deadly'
        ],
        'weight': 2
    },
    'location_specific': {
        'keywords': [
            r'died\s+in\s+vehicle.*heat', r'found\s+in\s+car.*heat',
            r'outdoor\s+death.*heat', r'homeless.*heat\s+death',
            r'farm\s+worker.*heat\s+death', r'agricultural\s+worker.*heat',
            r'(?:air\s+conditioning|A/C)\s+failure.*death',
            r'no\s+(?:A/C|air\s+conditioning).*death',
            r'mobile\s+home.*heat\s+death'
        ],
        'weight': 8
    },
    'medical_coroner': {
        'keywords': [
            r'coroner.*heat', r'medical\s+examiner.*heat', r'autopsy.*heat',
            r'cause\s+of\s+death.*heat', r'heat\s+related\s+cause',
            r'environmental\s+heat.*death', r'heat\s+as\s+contributing\s+factor'
        ],
        'weight': 3
    },
    'exclusions': {
        'keywords': [
            r'heated\s+argument', r'heated\s+debate', r'heat\s+of\s+the\s+moment',
            r'preheat', r'heat\s+pump', r'heating\s+system', r'heated\s+game',
            r'heated\s+competition'
        ],
        'weight': -100
    }
}

# ============================================================================
# DATABASE
# ============================================================================

def init_database(db_path: str = 'imperial_valley_heat_deaths.db') -> sqlite3.Connection:
    """Initialize database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            url TEXT UNIQUE NOT NULL,
            url_hash TEXT UNIQUE,
            title TEXT,
            published_date DATE,
            scraped_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            text_content TEXT,
            heat_score REAL,
            category TEXT,
            UNIQUE(url_hash)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS keyword_matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER,
            keyword TEXT,
            keyword_type TEXT,
            match_count INTEGER,
            weight INTEGER,
            FOREIGN KEY (article_id) REFERENCES articles(id)
        )
    ''')
    
    conn.commit()
    logger.info(f"Database initialized: {db_path}")
    return conn

# ============================================================================
# SCORING
# ============================================================================

def calculate_heat_score(text: str) -> Tuple[float, List[Dict], Dict]:
    """Calculate heat score."""
    text_lower = text.lower()
    score = 0
    all_matches = []
    category_scores = {}
    
    # Check exclusions
    for pattern in KEYWORDS_EN['exclusions']['keywords']:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return 0.0, [], {}
    
    # Score categories
    for category, config in KEYWORDS_EN.items():
        if category == 'exclusions':
            continue
            
        for pattern in config['keywords']:
            matches = re.findall(pattern, text_lower, re.IGNORECASE)
            if matches:
                match_count = len(matches)
                points = match_count * config['weight']
                score += points
                
                for match in matches:
                    all_matches.append({
                        'keyword': match,
                        'category': category,
                        'weight': config['weight'],
                        'points': config['weight']
                    })
        
        category_matches = [m for m in all_matches if m['category'] == category]
        if category_matches:
            category_scores[category] = {
                'matches': len(category_matches),
                'score': sum(m['points'] for m in category_matches)
            }
    
    return score, all_matches, category_scores

def classify_relevance(score: float) -> str:
    """Classify relevance."""
    if score >= 50:
        return "EXTREMELY_RELEVANT"
    elif score >= 20:
        return "HIGHLY_RELEVANT"
    elif score >= 10:
        return "MODERATELY_RELEVANT"
    elif score > 0:
        return "MINIMALLY_RELEVANT"
    else:
        return "NOT_RELEVANT"

# ============================================================================
# SCRAPING
# ============================================================================

def get_url_hash(url: str) -> str:
    """Generate URL hash."""
    return hashlib.md5(url.encode()).hexdigest()

def check_if_scraped(url: str, conn: sqlite3.Connection) -> bool:
    """Check if already scraped."""
    cursor = conn.cursor()
    url_hash = get_url_hash(url)
    cursor.execute('SELECT id FROM articles WHERE url_hash = ?', (url_hash,))
    return cursor.fetchone() is not None

def scrape_article(url: str) -> Optional[Dict]:
    """Scrape article."""
    try:
        config = Config()
        config.browser_user_agent = 'Mozilla/5.0 (Academic Research)'
        config.request_timeout = 15
        
        article = Article(url, config=config)
        article.download()
        article.parse()
        
        return {
            'url': url,
            'url_hash': get_url_hash(url),
            'title': article.title,
            'text': article.text,
            'published_date': article.publish_date.strftime('%Y-%m-%d') if article.publish_date else None
        }
        
    except Exception as e:
        logger.error(f"Error scraping {url}: {e}")
        return None

def save_article(article_data: Dict, score: float, matches: List[Dict], 
                 category: str, conn: sqlite3.Connection) -> int:
    """Save article."""
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT OR IGNORE INTO articles 
            (source, url, url_hash, title, published_date, text_content,
             heat_score, category)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            'Imperial Valley Press',
            article_data['url'],
            article_data['url_hash'],
            article_data['title'],
            article_data.get('published_date'),
            article_data['text'],
            score,
            category
        ))
        
        article_id = cursor.lastrowid
        
        if article_id > 0:
            for match in matches:
                cursor.execute('''
                    INSERT INTO keyword_matches
                    (article_id, keyword, keyword_type, match_count, weight)
                    VALUES (?, ?, ?, ?, ?)
                ''', (article_id, match['keyword'], match['category'], 1, match['weight']))
            
            conn.commit()
            return article_id
        
    except Exception as e:
        logger.error(f"Save failed: {e}")
        conn.rollback()
        return -1
    
    return -1

# ============================================================================
# MAIN
# ============================================================================

def main():
    """Main workflow."""
    print("="*80)
    print("URL LIST SCRAPER")
    print("="*80)
    print("\nDownloads and scores articles from a list of URLs")
    print("No searching - just direct downloads!")
    
    # Get URL file
    print("\n" + "-"*80)
    url_file = input("\nEnter URL file path (default: article_urls_summer_2024.txt): ").strip()
    if not url_file:
        url_file = 'article_urls_summer_2024.txt'
    
    # Load URLs
    try:
        with open(url_file, 'r') as f:
            urls = [line.strip() for line in f if line.strip()]
        
        print(f"\n✓ Loaded {len(urls)} URLs from {url_file}")
        
    except FileNotFoundError:
        print(f"\n❌ File not found: {url_file}")
        print("\nMake sure you've run wayback_extractor.py first!")
        return
    
    # Initialize database
    conn = init_database()
    
    # Scraping
    print(f"\n{'='*80}")
    print("SCRAPING & SCORING")
    print(f"{'='*80}")
    print(f"\nProcessing {len(urls)} articles...")
    print(f"Delay: {REQUEST_DELAY_MIN}-{REQUEST_DELAY_MAX}s between requests\n")
    
    stats = {
        'total': len(urls),
        'processed': 0,
        'saved': 0,
        'score_too_low': 0,
        'errors': 0,
        'already_scraped': 0
    }
    
    for i, url in enumerate(urls, 1):
        print(f"\n[{i}/{len(urls)}] {url[:75]}...")
        
        if check_if_scraped(url, conn):
            print("  → Already in database")
            stats['already_scraped'] += 1
            continue
        
        # Delay
        delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
        time.sleep(delay)
        
        # Scrape
        article_data = scrape_article(url)
        if not article_data:
            stats['errors'] += 1
            continue
        
        stats['processed'] += 1
        logger.info(f"  ✓ Scraped: {article_data['title'][:60]}...")
        
        # Score
        full_text = article_data['title'] + '\n\n' + article_data['text']
        score, matches, categories = calculate_heat_score(full_text)
        relevance = classify_relevance(score)
        
        print(f"  Score: {score:.1f} ({relevance})")
        
        if score >= MIN_SCORE_THRESHOLD:
            for cat, data in categories.items():
                print(f"    - {cat}: {data['matches']} matches ({data['score']} pts)")
            
            article_id = save_article(article_data, score, matches, relevance, conn)
            if article_id > 0:
                stats['saved'] += 1
                logger.info(f"  💾 SAVED (ID: {article_id})")
        else:
            print(f"  → Score below threshold ({MIN_SCORE_THRESHOLD})")
            stats['score_too_low'] += 1
    
    # Summary
    print(f"\n{'='*80}")
    print("FINAL SUMMARY")
    print(f"{'='*80}")
    print(f"URLs loaded: {stats['total']}")
    print(f"Processed: {stats['processed']}")
    print(f"Saved (score >= {MIN_SCORE_THRESHOLD}): {stats['saved']}")
    print(f"Score too low: {stats['score_too_low']}")
    print(f"Already in database: {stats['already_scraped']}")
    print(f"Errors: {stats['errors']}")
    
    hit_rate = (stats['saved'] / stats['processed'] * 100) if stats['processed'] > 0 else 0
    print(f"\n✨ Hit rate: {hit_rate:.1f}%")
    
    conn.close()
    print(f"\n✅ Complete! Database: imperial_valley_heat_deaths.db")

if __name__ == '__main__':
    main()
