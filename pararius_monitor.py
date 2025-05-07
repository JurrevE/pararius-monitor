import requests
import time
import json
import os
from bs4 import BeautifulSoup
from datetime import datetime
from twilio.rest import Client
import logging
import hashlib
import random

class ParariusMonitor:
    def __init__(self, search_urls, check_interval=900, data_file="seen_listings.json"):
        # logging.basicConfig() removed - should be handled by app.py
        self.logger = logging.getLogger('ParariusMonitor')
        self.search_urls = search_urls
        if not isinstance(self.search_urls, list) or not self.search_urls:
            raise ValueError("search_urls must be a non-empty list of URLs.")

        self.check_interval = check_interval
        self.data_file = data_file
        self.seen_listings = self._load_seen_listings()

        for url in self.search_urls:
            if url not in self.seen_listings:
                self.seen_listings[url] = {}

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
                loaded_data = json.load(f)
                if isinstance(loaded_data, dict):
                    self.logger.info(f"Successfully loaded seen listings state from {self.data_file}.")
                    return loaded_data
                else:
                    self.logger.warning(f"Seen listings file {self.data_file} has incorrect format. Starting fresh.")
                    return {}
        except (FileNotFoundError, json.JSONDecodeError):
            self.logger.info(f"No existing listings file found ({self.data_file}) or file corrupted. Starting fresh.")
            return {}
        except Exception as e:
            self.logger.error(f"Unexpected error loading seen listings from {self.data_file}: {e}", exc_info=True)
            return {}


    def _save_seen_listings(self):
        try:
            with open(self.data_file, 'w') as f:
                json.dump(self.seen_listings, f, indent=4)
            self.logger.info(f"Saved seen listings state to {self.data_file}")
        except Exception as e:
            self.logger.error(f"Error saving seen listings state to {self.data_file}: {e}", exc_info=True)

    def check_for_new_listings(self, url):
        self.logger.info(f"Fetching listings from: {url}")
        current_seen_listings = self.seen_listings.get(url, {})
        new_listings_found = []

        try:
            response = requests.get(url, headers=self.headers, timeout=30) # Added timeout
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            # Optional: Save HTML dump
            # html_dump_filename = f"pararius_dump_{hashlib.md5(url.encode()).hexdigest()[:8]}.html"
            # with open(html_dump_filename, "w", encoding="utf-8") as f:
            # f.write(soup.prettify())
            # self.logger.debug(f"Saved HTML dump to {html_dump_filename}")

            listings = soup.select('li.search-list__item.search-list__item--listing')
            self.logger.info(f"Found {len(listings)} potential listings on the page {url} (primary selector)")

            if not listings:
                self.logger.warning(f"No listings found with primary selector for {url}. Trying alternate selectors.")
                listings = soup.select('section.listing-search-item.listing-search-item--list.listing-search-item--for-rent')
                self.logger.info(f"Alternative selector 1 for {url}: Found {len(listings)} listings")
                if not listings:
                    listings = soup.select('section[class*="listing-search-item"]')
                    self.logger.info(f"Alternative selector 2 for {url}: Found {len(listings)} listings")
            
            if not listings:
                self.logger.warning(f"No listings found for {url} with any selector.")
                return []


            for listing in listings:
                try:
                    listing_id = listing.get('data-listing-id', '') or listing.get('id', '')
                    if not listing_id:
                        link_elem_id = listing.select_one('a.listing-search-item__link--title')
                        if link_elem_id and link_elem_id.get('href'):
                            parts = link_elem_id['href'].split('/')
                            if parts:
                                potential_id = parts[-1]
                                if potential_id and potential_id not in ['huurwoningen', 'appartement', 'studio', 'huis']:
                                    listing_id = potential_id
                    if not listing_id:
                        listing_id = hashlib.md5(listing.prettify().encode()).hexdigest()
                        self.logger.warning(f"Using content hash as ID for a listing in {url}")

                    if not listing_id:
                        self.logger.warning(f"Could not determine a unique ID for a listing in {url}. Skipping.")
                        continue

                    if listing_id not in current_seen_listings:
                        self.logger.info(f"New listing detected in {url} with ID: {listing_id}")
                        title_elem = listing.select_one('section.listing-search-item h2.listing-search-item__title, h2.listing-search-item__title a')
                        title = title_elem.text.strip() if title_elem else "No title found"

                        link_elem = listing.select_one('a.listing-search-item__link--title, a.listing-search-item__link[href]')
                        link = "https://www.pararius.nl" + link_elem['href'] if link_elem and link_elem.get('href') else url

                        price_elem = listing.select_one('div.listing-search-item__price, span.listing-search-item__price')
                        price = price_elem.text.strip() if price_elem else "Price not available"

                        address_elem = listing.select_one('div.listing-search-item__location')
                        address = address_elem.text.strip() if address_elem else "Address not available"

                        self.logger.info(f"Details: {title} - {price} - {address}")
                        listing_info = {
                            "id": listing_id, # Store the ID
                            "title": title,
                            "price": price,
                            "address": address,
                            "url": link,
                            "source_url": url,
                            "found_at": datetime.now().isoformat()
                        }
                        self.seen_listings[url][listing_id] = listing_info
                        new_listings_found.append(listing_info)
                    else:
                        self.logger.debug(f"Existing listing (already seen for {url}): {listing_id}")
                except Exception as e:
                    self.logger.error(f"Error processing a listing element from {url}: {e}", exc_info=True)
                    self.logger.debug(f"Problematic listing HTML snippet: {str(listing)[:500]}")


            return new_listings_found

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Error fetching {url}: {e}")
            return []
        except Exception as e:
            self.logger.error(f"An unexpected error occurred while processing {url}: {e}", exc_info=True)
            return []

    def send_notification(self, listing):
        try:
            if not (self.twilio_account_sid and self.twilio_auth_token and
                    self.twilio_from_number and self.notification_number):
                self.logger.error("Twilio credentials not set. Can't send notification.")
                return False

            client = Client(self.twilio_account_sid, self.twilio_auth_token)
            message_body = (
                f"🆕 P!\n\n"
                f"🏡 {listing['title']}\n"
                f"📍 {listing['address']}\n"
                f"💰 {listing['price']}\n\n"
                f"🔗 {listing['url']}\n"
                f"(S: {listing.get('source_url', 'N/A')})"
            )
            self.logger.info(f"Sending notification for listing: {listing['title']} (from {listing.get('source_url', 'N/A')})")
            message_result = client.messages.create(
                body=message_body,
                from_=self.twilio_from_number,
                to=self.notification_number
            )
            self.logger.info(f"Notification sent! Twilio SID: {message_result.sid}")
            return True
        except Exception as e:
            self.logger.error(f"Error sending notification: {e}", exc_info=True)
            return False

    def run(self):
        self.logger.info(f"Starting Pararius monitor for {len(self.search_urls)} URLs: {self.search_urls}")
        self.logger.info(f"Checking every {self.check_interval} seconds")

        self.logger.info("--- Performing initial check for Pararius listings across all URLs... ---")
        all_new_listings_initial = []
        for i, url_to_check in enumerate(self.search_urls):
            self.logger.info(f"Initial check for URL {i+1}/{len(self.search_urls)}: {url_to_check}")
            new_listings_for_url = self.check_for_new_listings(url_to_check)
            all_new_listings_initial.extend(new_listings_for_url)
            if i < len(self.search_urls) - 1: # Don't sleep after the last URL
                time.sleep(random.uniform(1, 3)) # Small polite delay

        self._save_seen_listings()

        if all_new_listings_initial:
            self.logger.info(f"Found {len(all_new_listings_initial)} new Pararius listings across all URLs on initial check!")
            for listing in all_new_listings_initial:
                self.logger.info(f"Initial new Pararius: {listing['title']} ({listing.get('address', 'N/A')}) from {listing.get('source_url', 'N/A')}")
                self.send_notification(listing)
                time.sleep(random.uniform(0.5, 1.5)) # Small delay between notifications
        else:
            self.logger.info("No new Pararius listings found on initial check across all URLs.")
        self.logger.info("--- Pararius initial check complete. ---")

        while True:
            try:
                wait_interval = self.check_interval + random.uniform(-30, 30) # Add jitter
                self.logger.info(f"Pararius: Sleeping for approximately {wait_interval:.0f} seconds...")
                time.sleep(wait_interval)

                self.logger.info(f"--- Pararius: Checking for new listings at {datetime.now().isoformat()}... ---")
                all_new_listings_loop = []
                for i, url_to_check in enumerate(self.search_urls):
                    self.logger.info(f"Loop check for URL {i+1}/{len(self.search_urls)}: {url_to_check}")
                    new_listings_for_url = self.check_for_new_listings(url_to_check)
                    all_new_listings_loop.extend(new_listings_for_url)
                    if i < len(self.search_urls) - 1: # Don't sleep after the last URL
                        time.sleep(random.uniform(1, 3)) # Small polite delay
                
                self._save_seen_listings()

                if all_new_listings_loop:
                    self.logger.info(f"Found {len(all_new_listings_loop)} new Pararius listings this cycle!")
                    for listing in all_new_listings_loop:
                        self.logger.info(f"Loop new Pararius: {listing['title']} ({listing.get('address', 'N/A')}) from {listing.get('source_url', 'N/A')}")
                        self.send_notification(listing)
                        time.sleep(random.uniform(0.5, 1.5)) # Small delay between notifications
                # else: # Already logged by check_for_new_listings if empty
                #     self.logger.info("No new Pararius listings found this cycle.")
                self.logger.info(f"--- Pararius check cycle complete at {datetime.now().isoformat()} ---")

            except KeyboardInterrupt:
                self.logger.info("KeyboardInterrupt received. Shutting down Pararius monitor.")
                self._save_seen_listings()
                break
            except Exception as e:
                self.logger.error(f"Error in Pararius monitor main loop: {e}", exc_info=True)
                error_sleep = 120 + random.uniform(0, 60)
                self.logger.info(f"Pararius: Sleeping for {error_sleep:.0f} seconds after error before retrying.")
                time.sleep(error_sleep)

# Example usage for standalone testing:
# if __name__ == "__main__":
#     logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
#     load_dotenv() # Load .env for standalone test
# 
#     test_urls = [os.getenv("PARARIUS_SEARCH_URL_1"), os.getenv("PARARIUS_SEARCH_URL_2")]
#     test_urls = [url for url in test_urls if url] # Filter out None values
# 
#     if not test_urls:
#         print("Please set PARARIUS_SEARCH_URL_1 (and optionally _2) in .env for testing.")
#     else:
#         monitor = ParariusMonitor(test_urls, check_interval=60) # Short interval for testing
#         monitor.run()

#krijg kanker