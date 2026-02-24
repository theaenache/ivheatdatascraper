"""
Imperial Valley Heat Death News Scraper
Uses newspaper4k for article extraction and supports English/Spanish content

IMPORTANT: Before running, ensure you have:
1. Checked robots.txt for each source
2. Configured rate limiting appropriately
3. Reviewed Terms of Service
"""

import sqlite3
import re
import hashlib
import time
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import logging

try:
    from newspaper import Article, Config
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: Required packages not installed.")
    print("Install with: pip install newspaper4k beautifulsoup4 requests lxml --break-system-packages")
    exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

# News sources with metadata
NEWS_SOURCES = [
    {
        'name': 'Imperial Valley Press',
        'url': 'https://www.ivpressonline.com',
        'sections': ['/news/local/', '/news/'],
        'language': 'en',
        'bias': 'LOCAL-UNRATED'
    },
    {
        'name': 'Calexico Chronicle',
        'url': 'https://calexicochronicle.com',
        'sections': ['/'],
        'language': 'en',
        'bias': 'LOCAL-UNRATED'
    },
    {
        'name': 'Holtville Tribune',
        'url': 'https://holtvilletribune.com',
        'sections': ['/category/regional-news/'],
        'language': 'en',
        'bias': 'LOCAL-UNRATED'
    },
    {
        'name': 'The Desert Review',
        'url': 'https://www.thedesertreview.com',
        'sections': ['/news/local/'],
        'language': 'en',
        'bias': 'LOCAL-UNRATED'
    },
    {
        'name': 'Adelante Valle',
        'url': 'https://www.ivpressonline.com',
        'sections': ['/adelante-valle/'],
        'language': 'es',
        'bias': 'LOCAL-UNRATED'
    }
]

# English Keywords (with weights)
KEYWORDS_EN = {
    'primary_death': {  # Weight: 10
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
    'heat_illness': {  # Weight: 5
        'keywords': [
            r'heat\s+stroke', r'heat\s+exhaustion', r'hyperthermia',
            r'heat\s+illness', r'heat\s+related\s+illness', r'heat\s+emergency',
            r'heat-associated', r'severe\s+dehydration'
        ],
        'weight': 5
    },
    'contextual_death': {  # Weight: 7
        'keywords': [
            r'found\s+dead.*heat', r'body\s+found.*heat',
            r'unresponsive.*heat', r'pronounced\s+dead.*heat',
            r'died\s+after.*heat\s+wave', r'succumbed.*heat',
            r'extreme\s+heat.*died'
        ],
        'weight': 7
    },
    'environmental': {  # Weight: 2
        'keywords': [
            r'excessive\s+heat\s+warning', r'heat\s+wave', r'extreme\s+heat',
            r'triple-digit\s+temperature', r'record\s+heat', r'blistering\s+heat',
            r'record\s+breaking\s+heat', r'dangerous\s+heat', r'heat\s+advisory',
            r'scorching\s+(?:heat|temperature)', r'heat\s+claims\s+lives',
            r'deadly\s+heat', r'heat\s+turns\s+deadly'
        ],
        'weight': 2
    },
    'location_specific': {  # Weight: 8
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
    'medical_coroner': {  # Weight: 3
        'keywords': [
            r'coroner.*heat', r'medical\s+examiner.*heat', r'autopsy.*heat',
            r'cause\s+of\s+death.*heat', r'heat\s+related\s+cause',
            r'environmental\s+heat.*death', r'heat\s+as\s+contributing\s+factor'
        ],
        'weight': 3
    },
    'exclusions': {  # Auto-reject
        'keywords': [
            r'heated\s+argument', r'heated\s+debate', r'heat\s+of\s+the\s+moment',
            r'preheat', r'heat\s+pump', r'heating\s+system'
        ],
        'weight': -100
    }
}

# Spanish Keywords (with weights)
KEYWORDS_ES = {
    'primary_death': {
        'keywords': [
            r'muerte\s+por\s+calor', r'falleció\s+por\s+calor',
            r'murió\s+por\s+calor', r'sucumbió\s+por\s+calor',
            r'falleció\s+por\s+el\s+calor', r'hipertermia\s+fatal'
        ],
        'weight': 10
    },
    'heat_illness': {
        'keywords': [
            r'golpe\s+de\s+calor', r'insolación', r'hipertermia',
            r'deshidratación\s+severa', r'enfermedad\s+por\s+calor'
        ],
        'weight': 5
    },
    'environmental': {
        'keywords': [
            r'ola\s+de\s+calor', r'calor\s+extremo', r'temperatura\s+récord',
            r'aviso\s+de\s+calor', r'calor\s+peligroso', r'calor\s+mortal'
        ],
        'weight': 2
    }
}

# Rate limiting
REQUEST_DELAY = 12  # seconds between requests (conservative)
MAX_ARTICLES_PER_SOURCE = 50  # per session
MAX_ARTICLES_PER_DAY = 200  # total limit

# ============================================================================
# DATABASE SETUP
# ============================================================================

def init_database(db_path: str = 'imperial_valley_heat_deaths.db') -> sqlite3.Connection:
    """Initialize SQLite database with comprehensive schema."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Main articles table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            source_bias TEXT,
            language TEXT,
            url TEXT UNIQUE NOT NULL,
            url_hash TEXT UNIQUE,
            title TEXT,
            authors TEXT,
            published_date DATE,
            scraped_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            text_content TEXT,
            keywords_matched TEXT,
            heat_score REAL,
            category TEXT,
            UNIQUE(url_hash)
        )
    ''')
    
    # Keyword matches table (for detailed analysis)
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
    
    # Scrape sessions log
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS scrape_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            start_time TIMESTAMP,
            end_time TIMESTAMP,
            articles_found INTEGER,
            articles_new INTEGER,
            articles_scraped INTEGER,
            errors INTEGER,
            status TEXT
        )
    ''')
    
    # Error log
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS error_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            source TEXT,
            url TEXT,
            error_type TEXT,
            error_message TEXT
        )
    ''')
    
    conn.commit()
    logger.info(f"Database initialized: {db_path}")
    return conn

# ============================================================================
# KEYWORD MATCHING ENGINE
# ============================================================================

def calculate_heat_score(text: str, language: str = 'en') -> Tuple[float, List[Dict], Dict]:
    """
    Calculate heat-related death relevance score.
    
    Args:
        text: Article text (title + content)
        language: 'en' or 'es'
    
    Returns:
        (score, matched_keywords_list, category_breakdown)
    """
    text_lower = text.lower()
    score = 0
    all_matches = []
    category_scores = {}
    
    # Select keyword set based on language
    keywords_dict = KEYWORDS_EN if language == 'en' else KEYWORDS_ES
    
    # Check for exclusions first (English only for now)
    if language == 'en':
        for pattern in keywords_dict['exclusions']['keywords']:
            if re.search(pattern, text_lower, re.IGNORECASE):
                logger.debug(f"Excluded due to pattern: {pattern}")
                return 0.0, [], {}
    
    # Score each category
    for category, config in keywords_dict.items():
        if category == 'exclusions':
            continue
            
        category_matches = []
        category_score = 0
        
        for pattern in config['keywords']:
            matches = re.findall(pattern, text_lower, re.IGNORECASE)
            if matches:
                match_count = len(matches)
                points = match_count * config['weight']
                score += points
                category_score += points
                
                for match in matches:
                    all_matches.append({
                        'keyword': match,
                        'category': category,
                        'weight': config['weight'],
                        'points': config['weight']
                    })
                    category_matches.append(match)
        
        if category_matches:
            category_scores[category] = {
                'matches': len(category_matches),
                'unique_matches': len(set(category_matches)),
                'score': category_score
            }
    
    return score, all_matches, category_scores

def classify_relevance(score: float) -> str:
    """Classify article relevance based on score."""
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
# WEB SCRAPING FUNCTIONS
# ============================================================================

def get_url_hash(url: str) -> str:
    """Generate consistent hash for URL deduplication."""
    return hashlib.md5(url.encode()).hexdigest()

def check_if_scraped(url: str, conn: sqlite3.Connection) -> bool:
    """Check if URL already exists in database."""
    cursor = conn.cursor()
    url_hash = get_url_hash(url)
    cursor.execute('SELECT id FROM articles WHERE url_hash = ?', (url_hash,))
    return cursor.fetchone() is not None

def extract_article_links(source: Dict, max_links: int = 50) -> List[str]:
    """
    Extract article links from news source homepage/sections.
    
    Args:
        source: Source configuration dict
        max_links: Maximum links to return
    
    Returns:
        List of article URLs
    """
    all_links = []
    
    for section in source['sections']:
        try:
            url = source['url'] + section
            logger.info(f"Fetching links from: {url}")
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Academic Research - Heat Death Study) AppleWebKit/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find all links
            links = soup.find_all('a', href=True)
            
            for link in links:
                href = link['href']
                
                # Make absolute URL
                if href.startswith('/'):
                    full_url = source['url'] + href
                elif href.startswith('http'):
                    full_url = href
                else:
                    continue
                
                # Filter for article-like URLs
                if any(indicator in href.lower() for indicator in [
                    'article', 'news', '/202', 'story', 'post'
                ]) and full_url not in all_links:
                    all_links.append(full_url)
            
            logger.info(f"Found {len(links)} total links, {len(all_links)} potential articles")
            time.sleep(REQUEST_DELAY)  # Rate limiting
            
        except Exception as e:
            logger.error(f"Error fetching links from {url}: {e}")
    
    return all_links[:max_links]

def scrape_article_newspaper4k(url: str, language: str = 'en') -> Optional[Dict]:
    """
    Scrape article using newspaper4k.
    
    Args:
        url: Article URL
        language: 'en' or 'es'
    
    Returns:
        Article data dict or None if failed
    """
    try:
        # Configure newspaper
        config = Config()
        config.browser_user_agent = 'Mozilla/5.0 (Academic Research - Heat Death Study)'
        config.request_timeout = 15
        config.language = language
        
        # Create and download article
        article = Article(url, config=config, language=language)
        article.download()
        article.parse()
        
        # Extract data
        article_data = {
            'url': url,
            'url_hash': get_url_hash(url),
            'title': article.title,
            'authors': ', '.join(article.authors) if article.authors else None,
            'text': article.text,
            'published_date': article.publish_date.strftime('%Y-%m-%d') if article.publish_date else None,
            'language': language
        }
        
        logger.info(f"Successfully scraped: {article.title[:60]}...")
        return article_data
        
    except Exception as e:
        logger.error(f"Error scraping {url}: {e}")
        return None

def save_article(article_data: Dict, source_name: str, source_bias: str, 
                 score: float, matches: List[Dict], category: str,
                 conn: sqlite3.Connection) -> int:
    """Save article and keyword matches to database."""
    cursor = conn.cursor()
    
    try:
        # Insert article
        cursor.execute('''
            INSERT OR IGNORE INTO articles 
            (source, source_bias, language, url, url_hash, title, authors,
             published_date, text_content, keywords_matched, heat_score, category)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            source_name,
            source_bias,
            article_data['language'],
            article_data['url'],
            article_data['url_hash'],
            article_data['title'],
            article_data.get('authors'),
            article_data.get('published_date'),
            article_data['text'],
            str(matches),
            score,
            category
        ))
        
        article_id = cursor.lastrowid
        
        # Insert keyword matches
        for match in matches:
            cursor.execute('''
                INSERT INTO keyword_matches
                (article_id, keyword, keyword_type, match_count, weight)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                article_id,
                match['keyword'],
                match['category'],
                1,  # Individual match
                match['weight']
            ))
        
        conn.commit()
        logger.info(f"✓ Saved article ID {article_id}: {article_data['title'][:60]}")
        return article_id
        
    except Exception as e:
        logger.error(f"Error saving article: {e}")
        conn.rollback()
        return -1

def log_error(source: str, url: str, error_type: str, error_msg: str,
              conn: sqlite3.Connection):
    """Log scraping error to database."""
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO error_log (source, url, error_type, error_message)
        VALUES (?, ?, ?, ?)
    ''', (source, url, error_type, str(error_msg)))
    conn.commit()

# ============================================================================
# MAIN SCRAPING WORKFLOW
# ============================================================================

def scrape_source(source: Dict, conn: sqlite3.Connection, 
                  max_articles: int = MAX_ARTICLES_PER_SOURCE) -> Dict:
    """
    Scrape articles from a single news source.
    
    Args:
        source: Source configuration dict
        conn: Database connection
        max_articles: Maximum articles to scrape
    
    Returns:
        Statistics dict
    """
    stats = {
        'source': source['name'],
        'start_time': datetime.now(),
        'articles_found': 0,
        'articles_new': 0,
        'articles_scraped': 0,
        'errors': 0
    }
    
    logger.info(f"\n{'='*80}")
    logger.info(f"SCRAPING: {source['name']} ({source['language'].upper()})")
    logger.info(f"{'='*80}")
    
    try:
        # Get article links
        article_urls = extract_article_links(source, max_links=max_articles)
        stats['articles_found'] = len(article_urls)
        
        logger.info(f"Found {len(article_urls)} articles to process")
        
        # Scrape each article
        for i, url in enumerate(article_urls, 1):
            logger.info(f"\n[{i}/{len(article_urls)}] Processing: {url}")
            
            # Check if already scraped
            if check_if_scraped(url, conn):
                logger.info("  → Already in database, skipping")
                continue
            
            stats['articles_new'] += 1
            
            # Rate limiting
            time.sleep(REQUEST_DELAY)
            
            # Scrape article
            article_data = scrape_article_newspaper4k(url, source['language'])
            
            if not article_data:
                stats['errors'] += 1
                log_error(source['name'], url, 'SCRAPE_FAILED', 
                         'Failed to extract article', conn)
                continue
            
            # Calculate heat score
            full_text = article_data['title'] + '\n\n' + article_data['text']
            score, matches, categories = calculate_heat_score(
                full_text, source['language']
            )
            
            relevance = classify_relevance(score)
            
            logger.info(f"  Heat Score: {score:.1f} ({relevance})")
            
            # Only save if relevant
            if score > 0:
                article_id = save_article(
                    article_data, source['name'], source['bias'],
                    score, matches, relevance, conn
                )
                if article_id > 0:
                    stats['articles_scraped'] += 1
            else:
                logger.info("  → Score 0, not saving")
        
        stats['end_time'] = datetime.now()
        stats['status'] = 'COMPLETED'
        
    except Exception as e:
        logger.error(f"Error scraping source {source['name']}: {e}")
        stats['status'] = 'FAILED'
        stats['errors'] += 1
    
    # Log session
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO scrape_sessions
        (source, start_time, end_time, articles_found, articles_new,
         articles_scraped, errors, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        stats['source'],
        stats['start_time'],
        stats.get('end_time'),
        stats['articles_found'],
        stats['articles_new'],
        stats['articles_scraped'],
        stats['errors'],
        stats['status']
    ))
    conn.commit()
    
    return stats

def generate_summary_report(conn: sqlite3.Connection) -> str:
    """Generate summary report of scraping results."""
    cursor = conn.cursor()
    
    report = ["\n" + "="*80]
    report.append("SCRAPING SUMMARY REPORT")
    report.append("="*80)
    
    # Total articles
    cursor.execute('SELECT COUNT(*) FROM articles')
    total = cursor.fetchone()[0]
    report.append(f"\nTotal Articles in Database: {total}")
    
    # By relevance
    report.append("\nBy Relevance Category:")
    cursor.execute('''
        SELECT category, COUNT(*), AVG(heat_score)
        FROM articles
        GROUP BY category
        ORDER BY AVG(heat_score) DESC
    ''')
    for category, count, avg_score in cursor.fetchall():
        report.append(f"  {category:25} {count:4} articles (avg score: {avg_score:.1f})")
    
    # By source
    report.append("\nBy Source:")
    cursor.execute('''
        SELECT source, COUNT(*), AVG(heat_score)
        FROM articles
        GROUP BY source
        ORDER BY COUNT(*) DESC
    ''')
    for source, count, avg_score in cursor.fetchall():
        report.append(f"  {source:30} {count:4} articles (avg score: {avg_score:.1f})")
    
    # By language
    report.append("\nBy Language:")
    cursor.execute('''
        SELECT language, COUNT(*)
        FROM articles
        GROUP BY language
    ''')
    for lang, count in cursor.fetchall():
        lang_name = "English" if lang == "en" else "Spanish"
        report.append(f"  {lang_name:30} {count:4} articles")
    
    # Top articles
    report.append("\nTop 10 Most Relevant Articles:")
    cursor.execute('''
        SELECT title, source, heat_score, category
        FROM articles
        ORDER BY heat_score DESC
        LIMIT 10
    ''')
    for i, (title, source, score, category) in enumerate(cursor.fetchall(), 1):
        report.append(f"\n  {i}. [{score:.1f}] {title[:70]}")
        report.append(f"     Source: {source} | Category: {category}")
    
    report.append("\n" + "="*80)
    
    return '\n'.join(report)

# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main scraping workflow."""
    logger.info("="*80)
    logger.info("IMPERIAL VALLEY HEAT DEATH SCRAPER")
    logger.info("="*80)
    logger.info(f"Start time: {datetime.now()}")
    
    # Initialize database
    conn = init_database()
    
    # Scrape each source
    all_stats = []
    for source in NEWS_SOURCES:
        stats = scrape_source(source, conn)
        all_stats.append(stats)
    
    # Generate and display report
    report = generate_summary_report(conn)
    logger.info(report)
    
    # Save report
    with open('scraping_report.txt', 'w') as f:
        f.write(report)
    
    conn.close()
    logger.info(f"\nScraping completed at: {datetime.now()}")
    logger.info(f"Database: imperial_valley_heat_deaths.db")
    logger.info(f"Log file: scraper.log")
    logger.info(f"Report: scraping_report.txt")

if __name__ == '__main__':
    main()
