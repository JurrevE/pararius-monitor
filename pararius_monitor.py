import requests
import time
import json
import os
from bs4 import BeautifulSoup
from datetime import datetime
from twilio.rest import Client
import logging

class ParariusMonitor:
    def __init__(self, search_url, check_interval=900, data_file="seen_listings.json"):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler()]
        )
        self.logger = logging.getLogger('ParariusMonitor')
        self.search_url = search_url
        self.check_interval = check_interval
        self.data_file = data_file
        self.seen_listings = self._load_seen_listings()
        
        # Twilio config from environment
        self.twilio_account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
        self.twilio_auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
        self.twilio_from_number = os.environ.get("TWILIO_FROM_NUMBER")
        self.notification_number = os.environ.get("NOTIFICATION_NUMBER")
        
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
    
    def _load_seen_listings(self):
        try:
            with open(self.data_file, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.logger.info(f"No existing listings file found or file corrupted. Starting fresh.")
            return {}
    
    def _save_seen_listings(self):
        with open(self.data_file, 'w') as f:
            json.dump(self.seen_listings, f)

    def check_for_new_listings(self):
        try:
            self.logger.info(f"Fetching listings from: {self.search_url}")
            response = requests.get(self.search_url, headers=self.headers)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            # 🔍 DEBUG: Save raw HTML for inspection
            with open("pararius_dump.html", "w", encoding="utf-8") as f:
                f.write(soup.prettify())
            self.logger.info("Saved HTML dump to pararius_dump.html")

            # FIXED: Correct CSS selector based on actual HTML inspection
            listings = soup.select('li.search-list__item.search-list__item--listing')
            self.logger.info(f"Found {len(listings)} listings on the page")

            # More detailed debugging
            if not listings:
                self.logger.warning("No listings found with primary selector. Trying alternate selectors.")
                # Try alternative selectors in case the site structure changed
                listings = soup.select('.search-list__item.search-list__item--listing')
                self.logger.info(f"Alternative selector 1: Found {len(listings)} listings")
                
                if not listings:
                    # Try additional selectors based on the HTML inspection
                    listings = soup.select('section.listing-search-item.listing-search-item--list.listing-search-item--for-rent')
                    self.logger.info(f"Alternative selector 2: Found {len(listings)} listings")
                    
                    if not listings:
                        listings = soup.select('section[class*="listing-search-item"]')
                        self.logger.info(f"Alternative selector 3: Found {len(listings)} listings")

            # Print the first few listings HTML for debugging
            if listings and len(listings) > 0:
                self.logger.info("Sample listing HTML structure:")
                self.logger.info(listings[0].prettify()[:500] + "...")  # Print first 500 chars
            
            new_listings = []
            for listing in listings:
                try:
                    # Try multiple ways to get a unique identifier
                    listing_id = listing.get('data-listing-id', '') or listing.get('id', '')
                    
                    # If we still don't have an ID, try to extract one from a link
                    if not listing_id:
                        link_elem = listing.select_one('a.listing-search-item__link--title')
                        if link_elem and link_elem.get('href'):
                            # Extract ID from URL
                            listing_id = link_elem['href'].split('/')[-1]
                    
                    # If we still don't have an ID, use a hash of content as last resort
                    if not listing_id:
                        listing_id = hash(listing.text)
                    
                    self.logger.info(f"Processing listing ID: {listing_id}")
                    
                    # Updated selectors based on inspected HTML structure
                    title_elem = listing.select_one('section.listing-search-item h2.listing-search-item__title')
                    title = title_elem.text.strip() if title_elem else "No title"
                    
                    # Try to find the link using the correct classes from inspection
                    link_elem = listing.select_one('a.listing-search-item__link.listing-search-item__link--title')
                    if not link_elem:
                        link_elem = listing.select_one('a[data-action="click:listing-search-item#onClick"]')
                    link = "https://www.pararius.nl" + link_elem['href'] if link_elem and link_elem.get('href') else ""
                    
                    # Updated price and address selectors
                    price_elem = listing.select_one('div.listing-search-item__price')
                    price = price_elem.text.strip() if price_elem else "Price not available"
                    
                    address_elem = listing.select_one('div.listing-search-item__location')
                    address = address_elem.text.strip() if address_elem else "Address not available"
                    
                    self.logger.info(f"Found listing: {title} - {price}")
                    
                    if listing_id not in self.seen_listings:
                        self.logger.info(f"New listing detected: {title}")
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
                        self.logger.info(f"Existing listing (already seen): {title}")
                
                except Exception as e:
                    self.logger.error(f"Error processing a listing: {e}")
            
            self._save_seen_listings()
            return new_listings
            
        except Exception as e:
            self.logger.error(f"Error checking for new listings: {e}")
            return []
    
    def send_notification(self, listing):
        try:
            if not (self.twilio_account_sid and self.twilio_auth_token and 
                    self.twilio_from_number and self.notification_number):
                self.logger.error("Twilio credentials not set. Can't send notification.")
                return False
            
            client = Client(self.twilio_account_sid, self.twilio_auth_token)
            message = f"N listing\n\n{listing['title']}\n{listing['price']}\nL: {listing['url']}"
            
            self.logger.info(f"Sending notification to {self.notification_number} for listing: {listing['title']}")
            
            message_result = client.messages.create(
                body=message,
                from_=self.twilio_from_number,
                to=self.notification_number
            )
            
            self.logger.info(f"Notification sent! Twilio SID: {message_result.sid}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error sending notification: {e}")
            return False
    
    def run(self):
        self.logger.info(f"Starting Pararius monitor for {self.search_url}") 
        self.logger.info(f"Checking every {self.check_interval} seconds")
        
        # Do an initial check right away
        self.logger.info("Performing initial check for listings...")
        new_listings = self.check_for_new_listings()
        
        if new_listings:
            self.logger.info(f"Found {len(new_listings)} new listings on initial check!")
            for listing in new_listings:
                self.logger.info(f"New listing: {listing['title']} - {listing['price']}")
                self.send_notification(listing)
        else:
            self.logger.info("No new listings found on initial check")
        
        # Main monitoring loop
        while True:
            self.logger.info(f"Sleeping for {self.check_interval} seconds...")
            time.sleep(self.check_interval)
            
            self.logger.info(f"Checking for new listings at {datetime.now().isoformat()}")
            new_listings = self.check_for_new_listings()
            
            if new_listings:
                self.logger.info(f"Found {len(new_listings)} new listings!")
                for listing in new_listings:
                    self.logger.info(f"New listing: {listing['title']} - {listing['price']}")
                    self.send_notification(listing)
            else:
                self.logger.info("No new listings found")

# Example usage
if __name__ == "__main__":
    search_url = os.environ.get("PARARIUS_SEARCH_URL", "https://www.pararius.nl/huurwoningen/amsterdam/1-2-slaapkamers/0-1500")
    check_interval = int(os.environ.get("CHECK_INTERVAL", "900"))
    monitor = ParariusMonitor(search_url, check_interval=check_interval)
    monitor.run()
    #inshallah