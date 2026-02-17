#!/usr/bin/env python3
"""
Dealdrip - Price Tracking Tool
A full-stack web application for tracking e-commerce product prices
and sending email notifications when prices drop below target values.
"""

import sqlite3
import smtplib
import re
import os
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify, send_from_directory
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import requests
from bs4 import BeautifulSoup
import atexit
import time
from threading import Thread

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask app initialization
app = Flask(__name__)
CORS(app)
app.secret_key = 'dealdrip-secret-key-2024'

# Database configuration
import os
# Use PostgreSQL URL from environment (Render) or SQLite locally
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    # Production: PostgreSQL
    DATABASE = DATABASE_URL
else:
    # Development: SQLite
    DATABASE = 'dealdrip.db'

# ====== DIRECT EMAIL CONFIGURATION ======
# Option 1: Set your email settings directly here (easier)
DIRECT_EMAIL_CONFIG = {
    'enabled': True,  # Set to True to use direct config, False to use environment variables
    'smtp_server': 'smtp.gmail.com',  # For Gmail
    'smtp_port': 587,
    'email_user': 'dealdrip18@gmail.com',  # Replace with your email
    'email_password': 'phwx gphy soxk jfhd'  # Replace with your App Password
}

# Option 2: Environment variables (original method)
if DIRECT_EMAIL_CONFIG['enabled']:
    SMTP_SERVER = DIRECT_EMAIL_CONFIG['smtp_server']
    SMTP_PORT = DIRECT_EMAIL_CONFIG['smtp_port']
    EMAIL_USER = DIRECT_EMAIL_CONFIG['email_user']
    EMAIL_PASSWORD = DIRECT_EMAIL_CONFIG['email_password']
else:
    SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
    SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
    EMAIL_USER = os.environ.get('EMAIL_USER', 'your-email@gmail.com')
    EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD', 'your-app-password')

class DatabaseManager:
    """Handles all database operations for the Dealdrip application"""
    
    def __init__(self, db_path):
        self.db_path = db_path
        self.is_postgres = db_path.startswith('postgresql://') or db_path.startswith('postgres://')
        self.init_database()
    
    def get_connection(self):
        """Get database connection (SQLite or PostgreSQL)"""
        if self.is_postgres:
            try:
                # Try psycopg3 first (better Python 3.13+ support)
                import psycopg
                return psycopg.connect(self.db_path)
            except ImportError:
                # Fallback to psycopg2
                import psycopg2
                return psycopg2.connect(self.db_path)
        else:
            return sqlite3.connect(self.db_path)
    
    def init_database(self):
        """Initialize the database and create tables if they don't exist"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            if self.is_postgres:
                # PostgreSQL syntax
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS price_alerts (
                        id SERIAL PRIMARY KEY,
                        product_url TEXT NOT NULL,
                        target_price REAL NOT NULL,
                        user_email TEXT NOT NULL,
                        user_phone TEXT,
                        notification_type TEXT DEFAULT 'email',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_checked TIMESTAMP,
                        current_price REAL,
                        is_active BOOLEAN DEFAULT TRUE
                    )
                ''')
            else:
                # SQLite syntax
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS price_alerts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        product_url TEXT NOT NULL,
                        target_price REAL NOT NULL,
                        user_email TEXT NOT NULL,
                        user_phone TEXT,
                        notification_type TEXT DEFAULT 'email',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_checked TIMESTAMP,
                        current_price REAL,
                        is_active BOOLEAN DEFAULT 1
                    )
                ''')
            
            conn.commit()
            conn.close()
            logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Database initialization error: {e}")
    
    def add_price_alert(self, product_url, target_price, user_email, user_phone=None, notification_type='email'):
        """Add a new price alert to the database"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO price_alerts (product_url, target_price, user_email, user_phone, notification_type)
                VALUES (%s, %s, %s, %s, %s) RETURNING id
            ''' if self.is_postgres else '''
                INSERT INTO price_alerts (product_url, target_price, user_email, user_phone, notification_type)
                VALUES (?, ?, ?, ?, ?)
            ''', (product_url, target_price, user_email, user_phone, notification_type))
            
            if self.is_postgres:
                alert_id = cursor.fetchone()[0]
            else:
                alert_id = cursor.lastrowid
                
            conn.commit()
            conn.close()
            return alert_id
        except Exception as e:
            logger.error(f"Error adding price alert: {e}")
            return None
    
    def get_all_active_alerts(self):
        """Retrieve all active price alerts from the database"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            active_value = 'TRUE' if self.is_postgres else '1'
            cursor.execute(f'''
                SELECT id, product_url, target_price, user_email, current_price, user_phone, notification_type
                FROM price_alerts 
                WHERE is_active = {active_value}
            ''')
            
            results = cursor.fetchall()
            conn.close()
            return results
        except Exception as e:
            logger.error(f"Error fetching alerts: {e}")
            return []
    
    def update_price_info(self, alert_id, current_price):
        """Update the current price and last checked timestamp for an alert"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            if self.is_postgres:
                cursor.execute('''
                    UPDATE price_alerts 
                    SET current_price = %s, last_checked = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (current_price, alert_id))
            else:
                cursor.execute('''
                    UPDATE price_alerts 
                    SET current_price = ?, last_checked = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (current_price, alert_id))
            
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Error updating price info: {e}")

class PriceScraper:
    """Context-aware price scraper that focuses on the main product price"""
    
    def __init__(self):
        # Production-ready headers that mimic real browser behavior
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0'
        }
        # Create a session for better connection reuse
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        
        # Alternative user agents for rotation (more diverse and recent)
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:122.0) Gecko/20100101 Firefox/122.0'
        ]
        
        # Additional headers pool for rotation
        self.header_sets = [
            {
                'Accept-Language': 'en-US,en;q=0.9,hi;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br, zstd',
                'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"'
            },
            {
                'Accept-Language': 'en-IN,en;q=0.9,hi;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="121", "Google Chrome";v="121"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"macOS"'
            }
        ]
    
    def extract_price(self, url):
        """
        Context-aware price extraction focusing on the main product price with retry mechanism
        """
        # Retry configuration
        max_retries = 3
        timeout_values = [20, 25, 30]  # Increasing timeouts for retries
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Attempt {attempt + 1}/{max_retries} to extract price from {url}")
                
                # Add small random delay to avoid being detected as bot
                import random
                import time
                delay = random.uniform(1, 3) if attempt > 0 else 0
                if delay > 0:
                    time.sleep(delay)
                
                # Rotate user agent and headers for different attempts
                if attempt > 0:
                    random_ua = random.choice(self.user_agents)
                    random_headers = random.choice(self.header_sets)
                    
                    # Update session with new headers
                    self.session.headers.update({'User-Agent': random_ua})
                    self.session.headers.update(random_headers)
                    
                    # Add referrer to look more legitimate
                    domain = self._get_domain(url)
                    self.session.headers.update({'Referer': f'https://{domain}/'})
                
                # Use session with appropriate timeout
                timeout = timeout_values[attempt] if attempt < len(timeout_values) else 30
                response = self.session.get(url, timeout=timeout)
                
                # Check if we got a successful response
                if response.status_code == 200:
                    logger.info(f"Successfully fetched page (status: {response.status_code})")
                    break
                elif response.status_code == 403:
                    logger.warning(f"Access forbidden (403). Trying with different headers...")
                    # Try with more basic headers for this attempt
                    basic_headers = {
                        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                    }
                    response = self.session.get(url, headers=basic_headers, timeout=timeout)
                    if response.status_code == 200:
                        break
                elif response.status_code in [429, 502, 503, 504]:
                    # Rate limited or server errors - wait and retry
                    import time
                    wait_time = (attempt + 1) * 2  # Exponential backoff
                    logger.warning(f"Server error {response.status_code}. Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                    continue
                else:
                    response.raise_for_status()
                    
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout on attempt {attempt + 1}. Retrying with longer timeout...")
                if attempt == max_retries - 1:
                    raise
                continue
            except requests.exceptions.RequestException as e:
                logger.warning(f"Request failed on attempt {attempt + 1}: {e}")
                if attempt == max_retries - 1:
                    raise
                import time
                time.sleep(2)  # Wait before retry
                continue
        
        if response.status_code != 200:
            logger.error(f"Failed to fetch page after {max_retries} attempts. Status: {response.status_code}")
            return None
        
        try:
            # Parse the HTML content
            soup = BeautifulSoup(response.content, 'html.parser')
            domain = self._get_domain(url)
            
            logger.info(f"Extracting price from domain: {domain}")
            page_title = soup.title.string if soup.title else 'No title'
            logger.debug(f"Page title: {page_title}")
            logger.debug(f"Content length: {len(response.text)} characters")
            
            # Check if we got a maintenance/error page instead of the actual product page
            if self._is_blocked_or_error_page(response.text, page_title):
                logger.warning(f"Detected maintenance/error page instead of product page. Title: {page_title}")
                return None
            
            # Debug: Log first 500 chars to see what we're getting
            content_sample = response.text[:500].replace('\n', ' ').replace('\r', '')
            logger.debug(f"Content sample: {content_sample}")
            
            # Try different strategies in order of reliability
            strategies = [
                ('Structured Data', lambda: self._extract_from_structured_data(soup, response.text)),
                ('Site Specific', lambda: self._extract_site_specific_price(soup, domain, url)),
                ('Main Content', lambda: self._extract_from_main_content(soup)),
                ('Context Aware', lambda: self._extract_context_aware_generic(soup)),
                ('Aggressive Regex', lambda: self._extract_aggressive_regex(response.text)),
                ('API Fallback', lambda: self._try_api_fallback(url, domain))
            ]
            
            for strategy_name, strategy_func in strategies:
                try:
                    price = strategy_func()
                    if price and 10 <= price <= 100000:  # Reasonable price range
                        logger.info(f"Found price ₹{price:.2f} using {strategy_name} strategy")
                        return price
                except Exception as e:
                    logger.debug(f"{strategy_name} strategy failed: {e}")
                    continue
            
            logger.warning(f"No reliable price found for URL: {url}")
            return None
            
        except Exception as e:
            logger.error(f"Error scraping price from {url}: {e}")
            return None
    
    def _get_domain(self, url):
        """Extract domain from URL"""
        try:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc.lower()
            # Remove www. and mobile prefixes
            domain = re.sub(r'^(www\.|m\.|mobile\.)', '', domain)
            return domain
        except:
            return 'unknown'
    
    def _extract_site_specific_price(self, soup, domain, url):
        """Extract price using site-specific selectors"""
        
        site_selectors = {
            'amazon.com': [
                '.a-price .a-offscreen',
                '.a-price-whole',
                '#priceblock_dealprice',
                '#priceblock_ourprice', 
                '.a-price.a-text-price.a-size-medium.apexPriceToPay .a-offscreen',
                '.a-price-range .a-price .a-offscreen',
                'span.a-price-symbol + span.a-price-whole',
                '.a-section .a-price .a-offscreen'
            ],
            'amazon.in': [
                '.a-price .a-offscreen',
                '.a-price-whole',
                '#priceblock_dealprice',
                '#priceblock_ourprice',
                'span[class*="a-price-symbol"] + span[class*="a-price-whole"]',
                '.a-section .a-price .a-offscreen'
            ],
            'flipkart.com': [
                '._30jeq3._16Jk6d',
                '._30jeq3',
                '._16Jk6d',
                '.CEmiEU .Nx9bqj',
                '._1_WHN1',
                '.CEmiEU ._16Jk6d'
            ],
            'myntra.com': [
                # 2024 Myntra selectors - comprehensive list
                'span.pdp-price strong',
                '.pdp-price strong', 
                '.price-container .current-price',
                '.product-price .current-price',
                'span[class*="price-discounted"]',
                'span[class*="price-current"]',
                'div[class*="price-current"]',
                '[data-testid="price"]',
                '[class*="ProductPrice"]',
                '.price-info .current-price',
                '.selling-price',
                '.final-price',
                # Generic price patterns that might work (removed deprecated :contains)
                '.price',
                '[class*="price"]',
                '[id*="price"]',
                'span[title*="₹"]',
                'span[aria-label*="price"]',
                'div[data-price]'
            ],
            'ajio.com': [
                '.prod-sp',
                '.price-wrapper .prod-sp',
                'span[class*="prod-sp"]'
            ],
            'snapdeal.com': [
                '.payBlkBig',
                '.price .payBlkBig',
                'span[class*="payBlkBig"]'
            ],
            'ebay.com': [
                '.u-flL.condText',
                '#prcIsum',
                '.u-flL .condText .shrinkFont',
                'span[class*="conditionalText"]',
                '.price .currency-value'
            ],
            'walmart.com': [
                '[data-testid="price-current"]',
                '.price-characteristic',
                'span[itemprop="price"]',
                '.price .visuallyhidden'
            ],
            'target.com': [
                '[data-test="product-price"]',
                '.price',
                'span[class*="Price"]'
            ],
            'bestbuy.com': [
                '.sr-only:contains("current price")',
                '.pricing-price__range',
                'span[class*="sr-only"]'
            ],
            'nykaa.com': [
                '.css-1d0jdb',
                '.product-price .css-1d0jdb',
                'span[class*="css-1d0jdb"]'
            ],
            # Add more sites as needed
        }
        
        # Get selectors for this domain
        selectors = []
        for domain_key in site_selectors:
            if domain_key in domain:
                selectors = site_selectors[domain_key]
                logger.info(f"Using {len(selectors)} specific selectors for {domain_key}")
                logger.debug(f"Selectors: {selectors[:5]}")  # Log first 5 selectors
                break
        
        # Try site-specific selectors
        for selector in selectors:
            try:
                elements = soup.select(selector)
                logger.debug(f"Selector '{selector}' found {len(elements)} elements")
                
                for element in elements:
                    if element:
                        price_text = element.get_text(strip=True)
                        logger.debug(f"Element text for '{selector}': '{price_text[:50]}...'")
                        price = self._parse_price(price_text)
                        if price and price > 0:
                            logger.info(f"Found price with site-specific selector '{selector}': ₹{price}")
                            return price
            except Exception as e:
                logger.debug(f"Selector '{selector}' failed: {e}")
                continue
        
        return None
    
    def _extract_generic_price(self, soup, html_content):
        """Extract price using generic methods as fallback"""
        
        # Comprehensive list of generic selectors
        generic_selectors = [
            # Price-specific classes
            '.price',
            '.cost',
            '.amount',
            '.value',
            '.currency',
            '.money',
            
            # Common price class patterns
            '[class*="price"]',
            '[class*="cost"]',
            '[class*="amount"]',
            '[class*="currency"]',
            '[class*="money"]',
            '[class*="rupee"]',
            '[class*="dollar"]',
            '[class*="inr"]',
            
            # ID-based patterns
            '[id*="price"]',
            '[id*="cost"]',
            '[id*="amount"]',
            
            # Specific variations
            '.price-current',
            '.price-now',
            '.price-final',
            '.price-selling',
            '.sale-price',
            '.regular-price',
            '.product-price',
            '.item-price',
            '.current-price',
            '.selling-price',
            '.offer-price',
            '.discounted-price',
            '.final-price',
            
            # Schema.org microdata
            '[itemprop="price"]',
            '[itemprop="lowPrice"]',
            '[itemprop="highPrice"]',
            
            # Data attributes
            '[data-price]',
            '[data-cost]',
            '[data-amount]',
            
            # Text-based searches
            'span:contains("₹")',
            'span:contains("$")',
            'div:contains("₹")',
            'div:contains("$")',
        ]
        
        logger.info(f"Trying {len(generic_selectors)} generic selectors")
        
        # Try each generic selector
        for selector in generic_selectors:
            try:
                elements = soup.select(selector)
                for element in elements:
                    if element:
                        price_text = element.get_text(strip=True)
                        price = self._parse_price(price_text)
                        if price and price > 1:  # Minimum price threshold
                            logger.info(f"Found price with generic selector '{selector}': ${price}")
                            return price
            except Exception as e:
                continue
        
        # Last resort: regex on entire HTML content
        logger.info("Trying regex patterns on HTML content")
        return self._extract_with_regex(html_content)
    
    def _extract_with_regex(self, html_content):
        """Extract price using regex patterns with smart selection"""
        
        # Enhanced regex patterns for different currencies and formats
        regex_patterns = [
            # Indian Rupee patterns
            r'₹\s*([\d,]+(?:\.\d{2})?)',
            r'Rs\.?\s*([\d,]+(?:\.\d{2})?)',
            r'INR\s*([\d,]+(?:\.\d{2})?)',
            
            # Dollar patterns
            r'\$\s*([\d,]+(?:\.\d{2})?)',
            r'USD\s*([\d,]+(?:\.\d{2})?)',
            
            # JSON-like patterns (more reliable)
            r'"price"\s*:\s*"?([\d,]+(?:\.\d{2})?)"?',
            r'"sellingPrice"\s*:\s*"?([\d,]+(?:\.\d{2})?)"?',
            r'"currentPrice"\s*:\s*"?([\d,]+(?:\.\d{2})?)"?',
            r'"salePrice"\s*:\s*"?([\d,]+(?:\.\d{2})?)"?',
        ]
        
        all_prices = []
        
        # Collect all prices with their sources
        for pattern in regex_patterns:
            matches = re.findall(pattern, html_content, re.IGNORECASE)
            for match in matches:
                price = self._parse_price(match)
                if price and price > 1:  # Reasonable minimum price
                    all_prices.append({'price': price, 'pattern': pattern})
        
        if not all_prices:
            return None
        
        # Smart price selection logic
        selected_price = self._select_best_price(all_prices)
        
        if selected_price:
            logger.info(f"Selected price ${selected_price:.2f} from {len(all_prices)} found prices")
            return selected_price
        
        return None
    
    def _select_best_price(self, all_prices):
        """Select the most relevant price from multiple candidates"""
        if not all_prices:
            return None
        
        if len(all_prices) == 1:
            return all_prices[0]['price']
        
        # Remove duplicates
        unique_prices = {}
        for item in all_prices:
            price = item['price']
            if price not in unique_prices:
                unique_prices[price] = item
        
        price_list = list(unique_prices.keys())
        price_list.sort()
        
        logger.info(f"Found unique prices: {price_list}")
        
        # Strategy 1: If there are 2-3 prices, pick the middle one (likely current/selling price)
        if 2 <= len(price_list) <= 3:
            if len(price_list) == 2:
                # Choose the lower price (sale price over original)
                return min(price_list)
            else:  # 3 prices
                # Choose the middle price (current price between original and discounted)
                return sorted(price_list)[1]
        
        # Strategy 2: If many prices, avoid extreme outliers
        elif len(price_list) > 3:
            # Remove obvious outliers (very high or very low)
            median_price = sorted(price_list)[len(price_list)//2]
            
            # Filter prices within reasonable range of median
            reasonable_prices = [
                p for p in price_list 
                if 0.1 * median_price <= p <= 10 * median_price
            ]
            
            if reasonable_prices:
                # Prefer JSON-sourced prices (more reliable)
                json_prices = [
                    unique_prices[p]['price'] for p in reasonable_prices
                    if 'price' in unique_prices[p]['pattern'] or 'Price' in unique_prices[p]['pattern']
                ]
                
                if json_prices:
                    return min(json_prices)  # Lowest reliable price
                else:
                    return min(reasonable_prices)  # Lowest reasonable price
        
        # Fallback: return the most common price or the lowest
        return min(price_list)
    
    def _extract_from_structured_data(self, soup, html_content):
        """Extract from JSON-LD structured data (most reliable)"""
        import json
        
        # Look for JSON-LD structured data
        scripts = soup.find_all('script', {'type': 'application/ld+json'})
        for script in scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # Handle different structured data formats
                if isinstance(data, list):
                    data = data[0] if data else {}
                
                # Look for price in different structured data formats
                price_paths = [
                    ['offers', 'price'],
                    ['offers', 'lowPrice'],
                    ['offers', 'highPrice'],
                    ['price'],
                    ['priceRange'],
                ]
                
                for path in price_paths:
                    try:
                        current = data
                        for key in path:
                            current = current[key]
                        
                        if isinstance(current, (int, float, str)):
                            price = self._parse_price(str(current))
                            if price:
                                logger.info(f"Found price in structured data: ₹{price:.2f}")
                                return price
                    except (KeyError, TypeError):
                        continue
                        
            except Exception as e:
                logger.debug(f"Structured data parsing failed: {e}")
                continue
        
        return None
    
    def _extract_from_main_content(self, soup):
        """Extract from the main product content area"""
        
        # Look for main product containers
        main_selectors = [
            'main', '[role="main"]', '.main', '#main',
            '.product', '.product-details', '.product-info',
            '.item', '.item-details', '.item-info',
            '.pdp-container', '.product-container'
        ]
        
        for selector in main_selectors:
            try:
                main_area = soup.select_one(selector)
                if main_area:
                    # Look for prices within this main area only
                    price = self._find_price_in_element(main_area)
                    if price:
                        logger.info(f"Found price in main content: ₹{price:.2f}")
                        return price
            except Exception as e:
                logger.debug(f"Main content extraction failed for {selector}: {e}")
                continue
        
        return None
    
    def _extract_context_aware_generic(self, soup):
        """Generic extraction with context awareness"""
        
        # Look for price-related elements with context scoring
        price_contexts = [
            {'selector': '[data-testid*="price"]', 'weight': 10},
            {'selector': '[class*="selling-price"]', 'weight': 9},
            {'selector': '[class*="current-price"]', 'weight': 9},
            {'selector': '[class*="product-price"]', 'weight': 8},
            {'selector': '[itemprop="price"]', 'weight': 8},
            {'selector': '.price', 'weight': 6},
            {'selector': '[class*="price"]', 'weight': 5},
        ]
        
        candidates = []
        
        for context in price_contexts:
            try:
                elements = soup.select(context['selector'])
                for element in elements[:5]:  # Limit to first 5 matches
                    text = element.get_text(strip=True)
                    price = self._parse_price(text)
                    if price and 10 <= price <= 100000:
                        score = context['weight']
                        
                        # Boost score for elements in likely product areas
                        ancestors = [p.name for p in element.parents if p.name]
                        if any(name in ['main', 'article', 'section'] for name in ancestors):
                            score += 2
                        
                        candidates.append({'price': price, 'score': score, 'text': text})
            except Exception as e:
                logger.debug(f"Context extraction failed for {context['selector']}: {e}")
                continue
        
        if candidates:
            # Sort by score and return the best candidate
            best = max(candidates, key=lambda x: x['score'])
            logger.info(f"Best price candidate: ₹{best['price']:.2f} (score: {best['score']})")
            return best['price']
        
        return None
    
    def _find_price_in_element(self, element):
        """Find price within a specific element"""
        text = element.get_text(separator=' ', strip=True)
        
        # Look for currency patterns
        patterns = [
            r'₹\s*([0-9,]+(?:\.[0-9]{2})?)',
            r'Rs\.?\s*([0-9,]+(?:\.[0-9]{2})?)',
            r'\$\s*([0-9,]+(?:\.[0-9]{2})?)'
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                price = self._parse_price(match)
                if price and 10 <= price <= 100000:
                    return price
        
        return None
    
    def _extract_aggressive_regex(self, html_content):
        """Aggressive regex-based price extraction that searches entire page content"""
        logger.info("Trying aggressive regex extraction on full page content")
        
        # Log content sample for debugging
        content_length = len(html_content)
        logger.debug(f"Total content length: {content_length} characters")
        
        # Sample different parts of content to understand structure
        if content_length > 1000:
            beginning = html_content[:300].replace('\n', ' ')[:100]
            middle = html_content[content_length//2:content_length//2+300].replace('\n', ' ')[:100]
            end = html_content[-300:].replace('\n', ' ')[:100]
            logger.debug(f"Content beginning: {beginning}...")
            logger.debug(f"Content middle: {middle}...")
            logger.debug(f"Content end: {end}...")
        else:
            logger.debug(f"Short content: {html_content[:200]}...")
        
        # Comprehensive regex patterns for Indian e-commerce sites
        patterns = [
            # Standard rupee patterns with flexible spacing and formatting
            r'₹\s*([1-9][0-9,]*(?:\.[0-9]{2})?)',
            r'Rs\.?\s*([1-9][0-9,]*(?:\.[0-9]{2})?)',
            r'INR\s*([1-9][0-9,]*(?:\.[0-9]{2})?)',
            r'₹([1-9][0-9,]{2,8})',
            
            # JSON/JavaScript patterns (most reliable for modern sites) - fixed to avoid trailing punctuation
            r'"price"\s*:\s*"?([1-9][0-9,]*(?:\.[0-9]{2})?)"?[,}\s]',
            r'"sellingPrice"\s*:\s*"?([1-9][0-9,]*(?:\.[0-9]{2})?)"?[,}\s]',
            r'"currentPrice"\s*:\s*"?([1-9][0-9,]*(?:\.[0-9]{2})?)"?[,}\s]',
            r'"salePrice"\s*:\s*"?([1-9][0-9,]*(?:\.[0-9]{2})?)"?[,}\s]',
            r'"finalPrice"\s*:\s*"?([1-9][0-9,]*(?:\.[0-9]{2})?)"?[,}\s]',
            r'"discountedPrice"\s*:\s*"?([1-9][0-9,]*(?:\.[0-9]{2})?)"?[,}\s]',
            r'"listPrice"\s*:\s*"?([1-9][0-9,]*(?:\.[0-9]{2})?)"?[,}\s]',
            r'"mrp"\s*:\s*"?([1-9][0-9,]*(?:\.[0-9]{2})?)"?[,}\s]',
            
            # JavaScript variable assignments
            r'price\s*[=:]\s*([1-9][0-9,]*(?:\.[0-9]{2})?)',
            r'currentPrice\s*[=:]\s*([1-9][0-9,]*(?:\.[0-9]{2})?)',
            r'sellingPrice\s*[=:]\s*([1-9][0-9,]*(?:\.[0-9]{2})?)',
            r'productPrice\s*[=:]\s*([1-9][0-9,]*(?:\.[0-9]{2})?)',
            
            # HTML data attributes
            r'data-price[=\s]*["\']([1-9][0-9,]*(?:\.[0-9]{2})?)["\']',
            r'data-selling-price[=\s]*["\']([1-9][0-9,]*(?:\.[0-9]{2})?)["\']',
            r'data-current-price[=\s]*["\']([1-9][0-9,]*(?:\.[0-9]{2})?)["\']',
            
            # Context-based patterns
            r'([1-9][0-9,]*(?:\.[0-9]{2})?)\s*(?:only|OFF|offer|discount|/-)',
            r'(?:was|originally|MRP|marked|price)\s*:?\s*₹?\s*([1-9][0-9,]*(?:\.[0-9]{2})?)',
            r'(?:save|you save)\s*₹?\s*([1-9][0-9,]*(?:\.[0-9]{2})?)',
            
            # Very flexible patterns (use with caution)
            r'([1-9][0-9]{2,5})(?=\s*(?:/\-|only|OFF))',  # Numbers followed by price indicators
            r'([1-9],[0-9]{2,3}(?:,[0-9]{3})*)',  # Indian number format: 1,234 or 12,34,567
            
            # Emergency patterns - very broad (lowest priority)
            r'([5-9][0-9]{2}|[1-9][0-9]{3,5})',  # Any number between 500-999999
        ]
        
        all_prices = []
        
        # Extract all potential prices
        for i, pattern in enumerate(patterns):
            matches = re.findall(pattern, html_content, re.IGNORECASE | re.MULTILINE)
            if matches:
                logger.debug(f"Pattern {i+1} found {len(matches)} matches: {matches[:3]}...")  # Show first 3 matches
            else:
                logger.debug(f"Pattern {i+1} found no matches")
            
            for match in matches:
                price = self._parse_price(match)
                if price and 10 <= price <= 100000:  # More lenient range for better extraction
                    all_prices.append({
                        'price': price, 
                        'pattern_index': i,
                        'pattern': pattern,
                        'raw_match': match
                    })
        
        if not all_prices:
            logger.info("No prices found with aggressive regex")
            return None
        
        # Sort by pattern priority (lower index = higher priority)
        all_prices.sort(key=lambda x: (x['pattern_index'], x['price']))
        
        # Log what we found
        price_values = [p['price'] for p in all_prices[:10]]  # First 10
        logger.info(f"Aggressive regex found {len(all_prices)} price candidates: {price_values}")
        
        # Return the most likely price (first in sorted list)
        selected_price = all_prices[0]['price']
        logger.info(f"Selected price ₹{selected_price:.2f} from pattern: {all_prices[0]['pattern'][:50]}...")
        
        return selected_price
    
    def _is_blocked_or_error_page(self, html_content, page_title):
        """Detect if we received a maintenance, error, or blocking page instead of actual content"""
        
        # Convert to lowercase for case-insensitive matching
        content_lower = html_content.lower()
        title_lower = page_title.lower() if page_title else ''
        
        # Common indicators of maintenance/error/blocking pages
        error_indicators = [
            'site maintenance', 'maintenance mode', 'under maintenance',
            'temporarily unavailable', 'service unavailable',
            'access denied', 'forbidden', 'blocked',
            'error 403', 'error 404', 'error 500',
            'something went wrong', 'oops', 'sorry',
            'please try again', 'administrator',
            'captcha', 'verify you are human',
            'bot detected', 'automated traffic'
        ]
        
        # Check title first (most reliable)
        for indicator in error_indicators:
            if indicator in title_lower:
                logger.debug(f"Error indicator '{indicator}' found in title")
                return True
        
        # Check if content is suspiciously short for a product page
        if len(html_content) < 1000:
            logger.debug(f"Content too short ({len(html_content)} chars) for a product page")
            # Additional check - if it's short AND contains error indicators
            for indicator in error_indicators:
                if indicator in content_lower:
                    logger.debug(f"Error indicator '{indicator}' found in short content")
                    return True
        
        # Check for absence of typical e-commerce elements in short pages
        if len(html_content) < 2000:  # Only for short pages to avoid false positives
            ecommerce_indicators = [
                'add to cart', 'buy now', 'price', 'product',
                '₹', 'rs.', 'inr', '$', 'discount', 'offer'
            ]
            
            found_indicators = sum(1 for indicator in ecommerce_indicators if indicator in content_lower)
            if found_indicators < 2:  # If less than 2 e-commerce indicators found
                logger.debug(f"Only {found_indicators} e-commerce indicators found in short content")
                return True
        
        return False
    
    def _try_api_fallback(self, original_url, domain):
        """Try alternative approaches when main scraping fails"""
        logger.info("Trying API fallback methods")
        
        fallback_strategies = []
        
        # Strategy 1: Try mobile version
        if 'myntra.com' in domain:
            mobile_url = original_url.replace('www.myntra.com', 'm.myntra.com')
            fallback_strategies.append(('Mobile Site', mobile_url))
        elif 'amazon.in' in domain:
            mobile_url = original_url.replace('www.amazon.in', 'm.amazon.in')
            fallback_strategies.append(('Mobile Site', mobile_url))
        
        # Strategy 2: Try AMP version
        if '/buy' in original_url or '/p/' in original_url:
            amp_url = original_url.replace('/buy', '/amp').replace('/p/', '/amp/')
            fallback_strategies.append(('AMP Version', amp_url))
        
        # Try each fallback strategy
        for strategy_name, fallback_url in fallback_strategies:
            try:
                logger.debug(f"Trying {strategy_name}: {fallback_url}")
                
                # Use a simple GET request with mobile user agent
                mobile_headers = {
                    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
                }
                
                response = requests.get(fallback_url, headers=mobile_headers, timeout=15)
                if response.status_code == 200 and len(response.text) > 1000:
                    # Quick check if this looks like actual content
                    if not self._is_blocked_or_error_page(response.text, 'Unknown'):
                        logger.info(f"{strategy_name} returned valid content, trying extraction")
                        price = self._extract_aggressive_regex(response.text)
                        if price:
                            logger.info(f"Found price ₹{price} using {strategy_name}")
                            return price
                        
            except Exception as e:
                logger.debug(f"{strategy_name} failed: {e}")
                continue
        
        logger.info("All API fallback methods failed")
        return None
    
    def _parse_price(self, price_text):
        """Enhanced price parsing with better format handling"""
        if not price_text:
            return None
        
        # Convert to string and clean
        price_text = str(price_text).strip()
        
        # Remove currency symbols and extra characters, keep digits, dots, commas
        price_text = re.sub(r'[^\d.,]', '', price_text)
        
        if not price_text:
            return None
        
        # Handle different decimal formats
        try:
            if ',' in price_text and '.' in price_text:
                # Check which comes last to determine format
                last_comma = price_text.rfind(',')
                last_dot = price_text.rfind('.')
                
                if last_dot > last_comma:
                    # Format: 1,234.56 (comma as thousands separator)
                    price_text = price_text.replace(',', '')
                else:
                    # Format: 1.234,56 (European format)
                    # Replace dots with empty, comma with dot
                    price_text = price_text.replace('.', '').replace(',', '.')
            
            elif ',' in price_text:
                # Could be either 1,234 or 1,56
                parts = price_text.split(',')
                if len(parts) == 2 and len(parts[1]) <= 2:
                    # Likely European decimal format: 1,56
                    price_text = price_text.replace(',', '.')
                else:
                    # Likely thousands separator: 1,234 or 12,34,567
                    price_text = price_text.replace(',', '')
            
            # Convert to float
            price = float(price_text)
            
            # Reasonable bounds check
            if 0.01 <= price <= 10000000:  # Between 1 cent and 10 million
                return price
            else:
                return None
                
        except (ValueError, TypeError):
            return None

class EmailNotifier:
    """Handles sending email notifications to users"""
    
    def __init__(self, smtp_server, smtp_port, email_user, email_password):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.email_user = email_user
        self.email_password = email_password
    
    def send_price_alert(self, user_email, product_url, current_price, target_price):
        """Send price drop notification email to user"""
        try:
            msg = MIMEMultipart()
            msg['From'] = self.email_user
            msg['To'] = user_email
            msg['Subject'] = f"🎉 Price Drop Alert - Dealdrip"
            
            # Create HTML email body
            html_body = f"""
            <html>
                <body>
                    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                        <h2 style="color: #2c3e50;">🎉 Great News! Price Drop Detected</h2>
                        
                        <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0;">
                            <h3 style="color: #27ae60; margin-top: 0;">Your Target Price Has Been Reached!</h3>
                            
                            <p><strong>Product URL:</strong> <a href="{product_url}" target="_blank">{product_url}</a></p>
                            
                            <div style="display: flex; justify-content: space-around; text-align: center; margin: 20px 0;">
                                <div>
                                    <div style="font-size: 14px; color: #7f8c8d;">Current Price</div>
                                    <div style="font-size: 24px; font-weight: bold; color: #27ae60;">₹{current_price:.2f}</div>
                                </div>
                                <div>
                                    <div style="font-size: 14px; color: #7f8c8d;">Your Target</div>
                                    <div style="font-size: 24px; font-weight: bold; color: #3498db;">₹{target_price:.2f}</div>
                                </div>
                            </div>
                            
                            <div style="text-align: center; margin: 20px 0;">
                                <a href="{product_url}" 
                                   style="background-color: #e74c3c; color: white; padding: 12px 24px; 
                                          text-decoration: none; border-radius: 5px; font-weight: bold;">
                                    🛒 Buy Now
                                </a>
                            </div>
                        </div>
                        
                        <p style="color: #7f8c8d; font-size: 12px;">
                            This is an automated message from Dealdrip. Happy shopping! 🛍️
                        </p>
                    </div>
                </body>
            </html>
            """
            
            msg.attach(MIMEText(html_body, 'html'))
            
            # Send email
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.email_user, self.email_password)
                text = msg.as_string()
                server.sendmail(self.email_user, user_email, text)
            
            logger.info(f"Price alert email sent to {user_email}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending email to {user_email}: {e}")
            return False

# Import our Telegram+Email notification system
import subprocess

class NotificationManager:
    """Production-ready email notification manager"""
    
    def __init__(self, email_notifier):
        self.email_notifier = email_notifier
        logger.info("📧 Email notification system initialized")
    
    def send_notification(self, notification_type, user_email, user_phone, product_url, current_price, target_price):
        """Send email notification to user"""
        success = False
        
        # Use email notification system
        success = self._send_email_notification(product_url, current_price, target_price, user_email, user_phone, notification_type)
        
        if success:
            contact = user_email or 'user'
            logger.info(f"✅ Email notification sent successfully to {contact}")
        else:
            logger.error(f"❌ Email notification failed")
        
        return success
    
    def _send_email_notification(self, product_url, current_price, target_price, user_email=None, user_phone=None, notification_type='email'):
        """Send email notification via Node.js system with Python email fallback"""
        try:
            savings = target_price - current_price
            title = f"🎉 Deal Alert - ₹{current_price:.2f}"
            message = f"Price Alert! Your target has been reached!\n\n💰 Current Price: ₹{current_price:.2f}\n🎯 Target Price: ₹{target_price:.2f}\n💸 You Save: ₹{savings:.2f}\n\n🔗 Product: {product_url}\n\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n- DealDrip Bot"
            
            # Try Node.js email system first with user details
            try:
                # Build command with user-specific parameters
                cmd = [
                    'node', 'send_notification.js', 
                    title, message, product_url
                ]
                
                # Add user email if provided
                if user_email:
                    cmd.append(user_email)
                else:
                    cmd.append('null')  # Placeholder
                
                # Add user phone if provided
                if user_phone:
                    cmd.append(user_phone)
                else:
                    cmd.append('null')  # Placeholder
                    
                # Add notification type
                cmd.append(notification_type)
                
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=15, encoding='utf-8', errors='ignore')
                
                if result.stdout and 'NOTIFICATION_SUCCESS' in result.stdout:
                    logger.info("✅ Node.js email notification sent successfully!")
                    return True
                else:
                    logger.warning(f"⚠️ Node.js notification failed: {result.stdout if result.stdout else 'No output'}")
                    logger.info("🔄 Falling back to Python email notification...")
            
            except Exception as node_error:
                logger.warning(f"⚠️ Node.js notification error: {node_error}")
                logger.info("🔄 Falling back to Python email notification...")
            
            # Fallback: Use Python email system
            if user_email:
                email_success = self.email_notifier.send_price_alert(
                    user_email, product_url, current_price, target_price
                )
                if email_success:
                    logger.info("✅ Python email notification sent successfully!")
                    return True
                else:
                    logger.error("❌ Python email notification also failed")
            else:
                logger.warning("⚠️ No email address provided for fallback notification")
            
            return False
                
        except Exception as e:
            logger.error(f"❌ Error in notification system: {e}")
            return False
    
    def health_check(self):
        """Simple health check for email system"""
        return {
            "overall_healthy": True,
            "providers": {
                "email": {"status": "available", "type": "email"},
                "nodejs_email": {"status": "available", "type": "nodejs_fallback"}
            }
        }

# Initialize components
db_manager = DatabaseManager(DATABASE)
price_scraper = PriceScraper()
email_notifier = EmailNotifier(SMTP_SERVER, SMTP_PORT, EMAIL_USER, EMAIL_PASSWORD)
notification_manager = NotificationManager(email_notifier)

def check_prices():
    """
    Scheduled task that checks all active price alerts
    This function runs daily to scrape prices and send notifications
    """
    logger.info("Starting scheduled price check...")
    
    alerts = db_manager.get_all_active_alerts()
    logger.info(f"Checking {len(alerts)} active price alerts")
    
    for alert in alerts:
        alert_id, product_url, target_price, user_email, current_stored_price, user_phone, notification_type = alert
        
        try:
            # Scrape current price
            current_price = price_scraper.extract_price(product_url)
            
            if current_price is not None:
                # Update database with current price
                db_manager.update_price_info(alert_id, current_price)
                
                # Check if price dropped below target
                if current_price <= target_price:
                    logger.info(f"Price drop detected! Current: ₹{current_price:.2f}, Target: ₹{target_price:.2f}")
                    
                    # Send notification based on user preference
                    notification_sent = notification_manager.send_notification(
                        notification_type, user_email, user_phone, product_url, current_price, target_price
                    )
                    
                    if notification_sent:
                        contact = user_email if notification_type == 'email' else (user_phone if notification_type == 'whatsapp' else 'user')
                        logger.info(f"Notification sent to {contact}")
                    else:
                        logger.error(f"Failed to send notification")
                else:
                    logger.info(f"Price ₹{current_price:.2f} still above target ₹{target_price:.2f}")
            else:
                logger.warning(f"Could not extract price from {product_url}")
                
        except Exception as e:
            logger.error(f"Error processing alert {alert_id}: {e}")
    
    logger.info("Completed scheduled price check")

# Set up scheduler for daily price checks
scheduler = BackgroundScheduler()
# Run every day at 9:00 AM
scheduler.add_job(
    func=check_prices,
    trigger=CronTrigger(hour=9, minute=0),
    id='daily_price_check',
    name='Check prices daily',
    replace_existing=True
)

# For testing purposes, also run every 5 minutes (comment out for production)
# scheduler.add_job(
#     func=check_prices,
#     trigger='interval',
#     minutes=5,
#     id='test_price_check',
#     name='Test price check every 5 minutes'
# )

scheduler.start()

# Shut down the scheduler when exiting the app
atexit.register(lambda: scheduler.shutdown())

# Flask routes
@app.route('/')
def index():
    """Serve the main HTML page"""
    return send_from_directory('.', 'index.html')

@app.route('/api/track', methods=['POST'])
def track_product():
    """API endpoint to add a new product for price tracking"""
    try:
        logger.info("Received track_product request")
        data = request.get_json()
        
        # Validate input data
        required_fields = ['url', 'target_price']
        if not data or not all(key in data for key in required_fields):
            return jsonify({
                'success': False,
                'message': 'Missing required fields: url, target_price'
            }), 400
        
        product_url = data['url'].strip()
        target_price = float(data['target_price'])
        user_email = data.get('email', '').strip().lower()
        user_phone = data.get('phone', '').strip()
        notification_type = data.get('notification_type', 'email').strip().lower()
        
        # Basic validation
        if not product_url:
            return jsonify({
                'success': False,
                'message': 'URL cannot be empty'
            }), 400
        
        if target_price <= 0:
            return jsonify({
                'success': False,
                'message': 'Target price must be greater than 0'
            }), 400
        
        # Validate email (always required)
        if not user_email:
            return jsonify({
                'success': False,
                'message': 'Email address is required'
            }), 400
        
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, user_email):
            return jsonify({
                'success': False,
                'message': 'Please enter a valid email address'
            }), 400
            
        # Force notification type to email
        notification_type = 'email'
        
        # Add to database
        logger.info(f"Attempting to add alert: URL={product_url[:50]}..., Price=${target_price}, Email={user_email}, Phone={user_phone}, Type={notification_type}")
        alert_id = db_manager.add_price_alert(product_url, target_price, user_email, user_phone, notification_type)
        logger.info(f"Database operation result: alert_id={alert_id}")
        
        if alert_id:
            contact_info = f"Email={user_email}" if user_email else f"Phone={user_phone}"
            logger.info(f"New price alert added: ID={alert_id}, URL={product_url}, Price=₹{target_price:.2f}, {contact_info}, Type={notification_type}")
            
            # Try to get initial price and check if notification should be sent immediately
            try:
                initial_price = price_scraper.extract_price(product_url)
                if initial_price:
                    db_manager.update_price_info(alert_id, initial_price)
                    logger.info(f"Initial price set: ₹{initial_price:.2f}")
                    
                    # Check if current price is already below or equal to target price
                    if initial_price <= target_price:
                        logger.info(f"🎉 Current price ₹{initial_price:.2f} is already below target ₹{target_price:.2f}! Sending immediate notification.")
                        
                        # Send immediate notification
                        notification_sent = notification_manager.send_notification(
                            notification_type, user_email, user_phone, product_url, initial_price, target_price
                        )
                        
                        if notification_sent:
                            contact = user_email if notification_type == 'email' else (user_phone if notification_type == 'whatsapp' else 'user')
                            logger.info(f"Immediate notification sent to {contact}")
                            
                            return jsonify({
                                'success': True,
                                'message': f'🎉 Great news! The current price ₹{initial_price:.2f} is already below your target ₹{target_price:.2f}! Notification sent.',
                                'alert_id': alert_id,
                                'current_price': initial_price,
                                'immediate_notification': True
                            })
                        else:
                            logger.error(f"Failed to send immediate notification")
                            
                            return jsonify({
                                'success': True,
                                'message': f'🎉 Current price ₹{initial_price:.2f} is below your target ₹{target_price:.2f}, but notification failed. Tracking started.',
                                'alert_id': alert_id,
                                'current_price': initial_price,
                                'immediate_notification': False
                            })
                    else:
                        logger.info(f"Current price ₹{initial_price:.2f} is above target ₹{target_price:.2f}. Will monitor for drops.")
                        
            except Exception as e:
                logger.warning(f"Could not get initial price: {e}")
            
            return jsonify({
                'success': True,
                'message': f'Successfully started tracking! You\'ll be notified when the price drops to ₹{target_price:.2f} or below.',
                'alert_id': alert_id
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Failed to save tracking request. Please try again.'
            }), 500
            
    except ValueError as e:
        return jsonify({
            'success': False,
            'message': 'Invalid target price. Please enter a valid number.'
        }), 400
    except Exception as e:
        import traceback
        logger.error(f"Error in track_product: {e}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'message': f'An error occurred: {str(e)}'
        }), 500

@app.route('/api/test-price', methods=['POST'])
def test_price_extraction():
    """Test endpoint to check if price can be extracted from a URL"""
    try:
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({'success': False, 'message': 'URL is required'}), 400
        
        url = data['url'].strip()
        if not url:
            return jsonify({'success': False, 'message': 'URL cannot be empty'}), 400
        
        price = price_scraper.extract_price(url)
        
        if price:
            return jsonify({
                'success': True,
                'message': f'Price extracted successfully: ₹{price:.2f}',
                'price': price
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Could not extract price from this URL. Please check the URL or try a different product page.'
            })
            
    except Exception as e:
        logger.error(f"Error in test_price_extraction: {e}")
        return jsonify({
            'success': False,
            'message': 'An error occurred while testing price extraction.'
        }), 500

@app.route('/api/manual-check', methods=['POST'])
def manual_price_check():
    """Manual trigger for price checking (useful for testing)"""
    try:
        check_prices()
        return jsonify({
            'success': True,
            'message': 'Manual price check completed successfully!'
        })
    except Exception as e:
        logger.error(f"Error in manual price check: {e}")
        return jsonify({
            'success': False,
            'message': 'An error occurred during manual price check.'
        }), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Production health check endpoint for monitoring"""
    try:
        # Check notification system health
        notification_health = notification_manager.health_check()
        
        # Check database connection
        try:
            alerts = db_manager.get_all_active_alerts()
            db_healthy = True
            active_alerts_count = len(alerts)
        except Exception:
            db_healthy = False
            active_alerts_count = 0
        
        # Overall health status
        overall_healthy = (
            notification_health.get('overall_healthy', False) and 
            db_healthy
        )
        
        health_data = {
            'status': 'healthy' if overall_healthy else 'degraded',
            'timestamp': datetime.now().isoformat(),
            'services': {
                'database': {
                    'status': 'healthy' if db_healthy else 'unhealthy',
                    'active_alerts': active_alerts_count
                },
                'notifications': notification_health
            },
            'version': '2.0-production'
        }
        
        status_code = 200 if overall_healthy else 503
        return jsonify(health_data), status_code
        
    except Exception as e:
        logger.error(f"Error in health check: {e}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 503

if __name__ == '__main__':
    logger.info("Starting Dealdrip application...")
    
    # Check email configuration
    if DIRECT_EMAIL_CONFIG['enabled']:
        if EMAIL_USER and EMAIL_PASSWORD:
            logger.info(f"✅ Direct email configuration enabled for: {EMAIL_USER}")
        else:
            logger.warning("⚠️  Direct email config enabled but credentials not set!")
            logger.info("Please edit DIRECT_EMAIL_CONFIG in app.py with your email settings.")
    else:
        logger.info("Note: For email notifications to work, set these environment variables:")
        logger.info("  SMTP_SERVER, SMTP_PORT, EMAIL_USER, EMAIL_PASSWORD")
        logger.info("Or enable DIRECT_EMAIL_CONFIG in the code for easier setup.")
    
    # Run the Flask app
    app.run(debug=True, host='0.0.0.0', port=5000)
