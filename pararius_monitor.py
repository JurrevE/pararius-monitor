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
        """
        Initialize the Pararius monitor
        
        Args:
            search_url: The Pararius search URL to monitor (with your filters applied)
            check_interval: Time between checks in seconds (default: 15 minutes)
            data_file: File to store seen listings
        """
        # Set up logging
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
        
        # Twilio configuration
        self.twilio_account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
        self.twilio_auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
        self.twilio_from_number = os.environ.get("TWILIO_FROM_NUMBER")
        self.notification_number = os.environ.get("NOTIFICATION_NUMBER")
        
        # Headers to mimic a browser
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
    
    def _load_seen_listings(self):
        """Load previously seen listings from file"""
        try:
            with open(self.data_file, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
    
    def _save_seen_listings(self):
        """Save seen listings to file"""
        with open(self.data_file, 'w') as f:
            json.dump(self.seen_listings, f)
    
    def check_for_new_listings(self):
        """Check Pararius for new listings"""
        try:
            response = requests.get(self.search_url, headers=self.headers)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            listings = soup.select('ul.search-list li.search-list__item--listing')
            
            new_listings = []
            for listing in listings:
                # Extract listing information
                try:
                    listing_id = listing.get('data-listing-id', '') or listing.get('id', '')
                    if not listing_id:
                        continue
                    
                    title_elem = listing.select_one('.listing-search-item__title')
                    title = title_elem.text.strip() if title_elem else "No title"
                    
                    link_elem = listing.select_one('a.listing-search-item__link--title')
                    link = f"https://www.pararius.com{link_elem['href']}" if link_elem else ""
                    
                    price_elem = listing.select_one('.listing-search-item__price')
                    price = price_elem.text.strip() if price_elem else "Price not available"
                    
                    address_elem = listing.select_one('.listing-search-item__location')
                    address = address_elem.text.strip() if address_elem else "Address not available"
                    
                    # Check if this is a new listing
                    if listing_id not in self.seen_listings:
                        listing_info = {
                            "title": title,
                            "price": price,
                            "address": address,
                            "url": link,
                            "found_at": datetime.now().isoformat()
                        }
                        
                        self.seen_listings[listing_id] = listing_info
                        new_listings.append(listing_info)
                
                except Exception as e:
                    print(f"Error processing a listing: {e}")
            
            self._save_seen_listings()
            return new_listings
            
        except Exception as e:
            print(f"Error checking for new listings: {e}")
            return []
    
    def send_notification(self, listing):
        """Send notification about new listing"""
        try:
            if not (self.twilio_account_sid and self.twilio_auth_token and 
                   self.twilio_from_number and self.notification_number):
                print("Twilio credentials not set. Can't send notification.")
                return False
            
            client = Client(self.twilio_account_sid, self.twilio_auth_token)
            
            message = f"New listing found!\n\n{listing['title']}\n{listing['price']}\n{listing['address']}\n\nView it here: {listing['url']}"
            
            # Send SMS
            client.messages.create(
                body=message,
                from_=self.twilio_from_number,
                to=self.notification_number
            )
            
            print(f"Notification sent for {listing['title']}")
            return True
            
        except Exception as e:
            print(f"Error sending notification: {e}")
            return False
    
    def run(self):
        """Main monitoring loop"""
        self.logger.info(f"Starting Pararius monitor for {self.search_url}")
        self.logger.info(f"Checking every {self.check_interval} seconds")
        
        while True:
            self.logger.info(f"Checking for new listings at {datetime.now().isoformat()}")
            new_listings = self.check_for_new_listings()
            
            if new_listings:
                self.logger.info(f"Found {len(new_listings)} new listings!")
                for listing in new_listings:
                    self.logger.info(f"New listing: {listing['title']} - {listing['price']}")
                    self.send_notification(listing)
            else:
                self.logger.info("No new listings found")
            
            self.logger.info(f"Next check in {self.check_interval} seconds")
            time.sleep(self.check_interval)


# Example usage
if __name__ == "__main__":
    # Set up your search URL with filters
    # For example: Amsterdam, 1-2 bedrooms, max €1500
    search_url = "https://www.pararius.com/apartments/amsterdam/1-2-bedrooms/0-1500"
    
    # Create and run the monitor
    monitor = ParariusMonitor(search_url, check_interval=900)  # Check every 15 minutes
    monitor.run()