import requests
import time
import json
import os
from bs4 import BeautifulSoup
from datetime import datetime
from twilio.rest import Client
import logging
import random

class FundaMonitor:
    def __init__(self, search_url, check_interval=900, data_file="seen_funda_listings.json"):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler()]
        )
        self.logger = logging.getLogger('FundaMonitor')
        self.search_url = search_url
        self.check_interval = check_interval
        self.data_file = data_file
        self.seen_listings = self._load_seen_listings()
        
        # Twilio config from environment
        self.twilio_account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
        self.twilio_auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
        self.twilio_from_number = os.environ.get("TWILIO_FROM_NUMBER")
        self.notification_number = os.environ.get("NOTIFICATION_NUMBER")
        
        # Rotating user agents to avoid detection
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36"
        ]
    
    def _get_random_headers(self):
        return {
            "User-Agent": random.choice(self.user_agents),
            "Accept-Language": "en-US,en;q=0.9,nl;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "max-age=0"
        }
    
    def _load_seen_listings(self):
        try:
            with open(self.data_file, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.logger.info(f"No existing Funda listings file found or file corrupted. Starting fresh.")
            return {}
    
    def _save_seen_listings(self):
        with open(self.data_file, 'w') as f:
            json.dump(self.seen_listings, f)

    def check_for_new_listings(self):
        try:
            self.logger.info(f"Fetching Funda listings from: {self.search_url}")
            response = requests.get(self.search_url, headers=self._get_random_headers())
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            # Save raw HTML for debugging (optional)
            with open("funda_dump.html", "w", encoding="utf-8") as f:
                f.write(soup.prettify())
            self.logger.info("Saved HTML dump to funda_dump.html")

            # Based on screenshot, using selectors that match Funda's structure
            # Looking for listings that are typically in search results
            listings = soup.select('ol.search-results li.search-result')
            self.logger.info(f"Found {len(listings)} listings on the page")

            # Try alternative selectors if none found
            if not listings:
                self.logger.warning("No listings found with primary selector. Trying alternate selectors.")
                
                # Try some alternative selectors based on the screenshot
                listings = [l for l in soup.select('div.border-b.pb-3') if l.select_one('a[href]')]

                self.logger.info(f"Alternative selector 1: Found {len(listings)} listings")
                
                if not listings:
                    listings = soup.select('[data-test-id="search-result-item"]')
                    self.logger.info(f"Alternative selector 2: Found {len(listings)} listings")
                    
                    if not listings:
                        listings = soup.select('.search-result-main')
                        self.logger.info(f"Alternative selector 3: Found {len(listings)} listings")
            
            # Print sample structure for debugging
            if listings and len(listings) > 0:
                self.logger.info("Sample listing HTML structure:")
                self.logger.info(listings[0].prettify()[:500] + "...")
            
            new_listings = []
            for listing in listings:
                try:
                    # Extract the listing ID from data attributes or URL
                    listing_id = listing.get('data-listing-id', '') or listing.get('id', '')
                    
                    # If no ID found, try to get it from link href
                    if not listing_id:
                        link_elem = listing.select_one('a.search-result__header-title-link')
                        if link_elem and link_elem.get('href'):
                            # Extract ID from URL
                            listing_id = link_elem['href'].split('/')[-1]
                    
                    # Last resort - use content hash
                    if not listing_id:
                        listing_id = str(hash(listing.text))
                    
                    self.logger.info(f"Processing Funda listing ID: {listing_id}")
                    
                    # Extract details based on Funda's HTML structure
                    title_elem = listing.select_one('a.search-result__header-title-link, h2.search-result__header-title')
                    title = title_elem.text.strip() if title_elem else "No title"
                    
                    # Get link
                    link_elem = listing.select_one('a.search-result__header-title-link')
                    link = "https://www.funda.nl" + link_elem['href'] if link_elem and link_elem.get('href') else ""
                    
                    # Get price
                    price_elem = listing.select_one('.search-result-price, .search-result__header-price')
                    price = price_elem.text.strip() if price_elem else "Price not available"
                    
                    # Get address
                    address_elem = listing.select_one('.search-result__header-subtitle')
                    address = address_elem.text.strip() if address_elem else "Address not available"
                    
                    self.logger.info(f"Found Funda listing: {title} - {price}")
                    
                    if listing_id not in self.seen_listings:
                        self.logger.info(f"New Funda listing detected: {title}")
                        listing_info = {
                            "title": title,
                            "price": price,
                            "address": address,
                            "url": link,
                            "found_at": datetime.now().isoformat()
                        }
                        self.seen_listings[listing_id] = listing_info
                        new_listings.append(listing_info)
                    else:
                        self.logger.info(f"Existing Funda listing (already seen): {title}")
                
                except Exception as e:
                    self.logger.error(f"Error processing a Funda listing: {e}")
            
            self._save_seen_listings()
            return new_listings
            
        except Exception as e:
            self.logger.error(f"Error checking for new Funda listings: {e}")
            return []
    
    def send_notification(self, listing):
        try:
            if not (self.twilio_account_sid and self.twilio_auth_token and 
                    self.twilio_from_number and self.notification_number):
                self.logger.error("Twilio credentials not set. Can't send notification.")
                return False
            
            client = Client(self.twilio_account_sid, self.twilio_auth_token)
            message = f"New Funda listing\n\n{listing['title']}\n{listing['price']}\nLocation: {listing['address']}\nURL: {listing['url']}"
            
            self.logger.info(f"Sending notification to {self.notification_number} for Funda listing: {listing['title']}")
            
            message_result = client.messages.create(
                body=message,
                from_=self.twilio_from_number,
                to=self.notification_number
            )
            
            self.logger.info(f"Funda notification sent! Twilio SID: {message_result.sid}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error sending Funda notification: {e}")
            return False
    
    def run(self):
        self.logger.info(f"Starting Funda monitor for {self.search_url}") 
        self.logger.info(f"Checking every {self.check_interval} seconds")
        
        # Do an initial check right away
        self.logger.info("Performing initial check for Funda listings...")
        new_listings = self.check_for_new_listings()
        
        if new_listings:
            self.logger.info(f"Found {len(new_listings)} new Funda listings on initial check!")
            for listing in new_listings:
                self.logger.info(f"New Funda listing: {listing['title']} - {listing['price']}")
                self.send_notification(listing)
        else:
            self.logger.info("No new Funda listings found on initial check")
        
        # Main monitoring loop
        while True:
            try:
                self.logger.info(f"Sleeping for {self.check_interval} seconds...")
                time.sleep(self.check_interval)
                
                self.logger.info(f"Checking for new Funda listings at {datetime.now().isoformat()}")
                new_listings = self.check_for_new_listings()
                
                if new_listings:
                    self.logger.info(f"Found {len(new_listings)} new Funda listings!")
                    for listing in new_listings:
                        self.logger.info(f"New Funda listing: {listing['title']} - {listing['price']}")
                        self.send_notification(listing)
                else:
                    self.logger.info("No new Funda listings found")
                    
            except Exception as e:
                self.logger.error(f"Error in Funda monitor main loop: {e}")
                # Sleep before retrying to avoid hammering the server in case of continuous errors
                time.sleep(60)

# Example usage
if __name__ == "__main__":
    search_url = os.environ.get("FUNDA_SEARCH_URL", "https://www.funda.nl/zoeken/huur?selected_area=[%22leeuwarden%22]&price=%22200-800%22&object_type=[%22house%22,%22apartment%22]")
    check_interval = int(os.environ.get("FUNDA_CHECK_INTERVAL", "900"))
    monitor = FundaMonitor(search_url, check_interval=check_interval)
    monitor.run()