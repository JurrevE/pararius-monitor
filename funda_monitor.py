from twilio.rest import Client
import logging
import random
import re # Import regex module for ID extraction
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime # Corrected import
import time
import requests

class FundaMonitor:
    def __init__(self, search_url, check_interval=900, data_file="seen_funda_listings.json"):
        # Setup logging
        self.logger = logging.getLogger(self.__class__.__name__) # Use class name for logger
        if not self.logger.handlers: # Avoid adding multiple handlers if re-instantiated
            handler = logging.StreamHandler()
            # More detailed formatter
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO) # Default level, can be overridden

        self.search_url = search_url # Assign search_url to instance variable
        self.check_interval = check_interval
        self.data_file = data_file
        self.seen_listings = self._load_seen_listings()

        # Twilio config from environment
        self.twilio_account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
        self.twilio_auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
        self.twilio_from_number = os.environ.get("TWILIO_FROM_NUMBER")
        self.notification_number = os.environ.get("NOTIFICATION_NUMBER")

        # Rotating user agents
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36"
        ]

    def _get_random_headers(self):
        return {
            "User-Agent": random.choice(self.user_agents),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
            "Accept-Language": "en-US,en;q=0.9,nl;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "max-age=0"
        }

    def _load_seen_listings(self):
        try:
            with open(self.data_file, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.logger.info(f"No existing Funda listings file found ('{self.data_file}') or file corrupted. Starting fresh.")
            return {}

    def _save_seen_listings(self):
        try:
            with open(self.data_file, 'w') as f:
                json.dump(self.seen_listings, f, indent=4)
        except IOError as e:
            self.logger.error(f"Could not save seen listings to {self.data_file}: {e}")


    def check_for_new_listings(self):
        try:
            self.logger.info(f"Fetching Funda listings from: {self.search_url}")
            response = requests.get(self.search_url, headers=self._get_random_headers(), timeout=20)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            # --- Listing Item Selectors ---
            # Primary strategy: data-test-id (often reliable for modern web apps)
            listings = soup.select('[data-test-id="search-result-item"]')
            self.logger.info(f"Found {len(listings)} potential listings using selector ('[data-test-id=\"search-result-item\"]')")

            if not listings:
                # Fallback 1: Original primary selector (div.border-b.pb-3)
                self.logger.warning("Selector '[data-test-id=\"search-result-item\"]' found no listings. Trying ('div.border-b.pb-3')...")
                listings = soup.select('div.border-b.pb-3')
                self.logger.info(f"Found {len(listings)} listings using selector ('div.border-b.pb-3')")

            if not listings:
                # Fallback 2: Older Funda structure
                self.logger.warning("Selector 'div.border-b.pb-3' found no listings. Trying ('ol.search-results li.search-result')...")
                listings = soup.select('ol.search-results li.search-result')
                self.logger.info(f"Found {len(listings)} listings using selector ('ol.search-results li.search-result')")

            if not listings:
                self.logger.warning("No listings found with any known selector. Funda structure might have changed significantly.")
                try:
                    with open(f"funda_dump_no_listings_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html", "w", encoding="utf-8") as f:
                        f.write(soup.prettify())
                    self.logger.info("Saved HTML dump for analysis (no listings found).")
                except Exception as dump_err:
                    self.logger.error(f"Failed to save no-listings HTML dump: {dump_err}")
                return []

            if listings:
                self.logger.debug(f"Sample listing HTML structure (first item of {len(listings)}):\n{listings[0].prettify()[:1000]}...")

            new_listings_details = []
            for item_index, listing_item_tag in enumerate(listings):
                listing_id = None
                title = "Title not found"
                price = "Price not found"
                address = "Address not found"
                link = ""

                try:
                    # 1. Find the main link element
                    link_elem = listing_item_tag.select_one('a[data-testid="listingDetailsAddress"]')
                    if not link_elem: # Fallback to any link that seems to go to a detail page
                        link_elem = listing_item_tag.select_one('a[href*="/koop/"], a[href*="/huur/"], a[href*="/object/"]')
                        if not link_elem: # More general detail link
                           link_elem = listing_item_tag.select_one('a[href*="/detail/"]')


                    if not link_elem:
                        self.logger.warning(f"Item {item_index}: Could not find the main link element. Skipping.")
                        self.logger.debug(f"Skipped item HTML (no link_elem): {listing_item_tag.prettify()[:500]}...")
                        continue

                    # 2. Extract URL and Listing ID
                    href_attr = link_elem.get('href')
                    if href_attr:
                        if not href_attr.startswith("http"):
                            link = "https://www.funda.nl" + href_attr.split('?')[0]
                        else:
                            link = href_attr.split('?')[0]

                        # ID Extraction Priority:
                        # a) data-object-id from the listing_item_tag itself
                        data_obj_id_attr = listing_item_tag.get('data-object-id')
                        if data_obj_id_attr:
                            id_match = re.search(r'(\d+)$', data_obj_id_attr)
                            if id_match:
                                listing_id = id_match.group(1)

                        # b) from URL if not found above
                        if not listing_id:
                            id_patterns = [
                                r'/object-(\d+)/?$',  # e.g., /object-12345678/
                                r'/(?:appartement|huis|kamer|garage|parkeerplaats|bouwgrond|project|woning)-(\d+)', # e.g., /type-12345678...
                                r'/(\d+)/?$' # generic number at end of path segment
                            ]
                            for pattern in id_patterns:
                                id_match = re.search(pattern, link) # Use the cleaned link
                                if id_match:
                                    listing_id = id_match.group(1)
                                    break
                        if not listing_id: # If still no ID, use the link as a fallback ID
                            self.logger.warning(f"Item {item_index}: Could not extract specific ID from data-attributes or URL '{link}'. Using full link as ID.")
                            listing_id = link
                    else:
                        self.logger.warning(f"Item {item_index}: Found link element but 'href' attribute is missing.")
                        listing_id = str(hash(listing_item_tag.text)) # Fallback ID

                    # 3. Extract Title (Street/Name part)
                    # Based on screenshot: <a ...><div class="flex font-semibold"><span class="truncate">TITLE</span></div>...</a>
                    title_span = link_elem.select_one('div.flex.font-semibold span.truncate')
                    if title_span and title_span.text.strip():
                        title = title_span.text.strip()
                    else: # Fallback for title
                        h_tag = link_elem.select_one('h1, h2, h3, h4') # Common header tags for title
                        if h_tag:
                            title = h_tag.text.strip().split('\n')[0] # Get first line
                        else: # Try to get text directly from the link if it's short
                            link_text = link_elem.text.strip().split('\n')[0]
                            if len(link_text) > 5 and len(link_text) < 100: # Heuristic for a title-like string
                                title = link_text
                            else:
                                self.logger.warning(f"Item {item_index} (ID: {listing_id}): Title not found via primary selectors.")


                    # 4. Extract Address (Postal Code/City part)
                    # Based on screenshot: <a ...><div class="truncate text-neutral-80">ADDRESS</div>...</a>
                    address_div = link_elem.select_one('div.truncate.text-neutral-80')
                    if address_div and address_div.text.strip():
                        address = address_div.text.strip()
                    else: # Fallback for address
                        # Look for p tags with postal code pattern inside the link_elem
                        p_tags = link_elem.select('p')
                        for p_tag in p_tags:
                            p_text = p_tag.text.strip()
                            if re.search(r'\d{4}\s?[A-Z]{2}', p_text): # Dutch postal code
                                address = p_text
                                break
                        if address == "Address not found":
                             self.logger.warning(f"Item {item_index} (ID: {listing_id}): Address not found via primary selectors.")


                    # 5. Extract Price
                    # Based on screenshot: <div class="text-xl font-semibold"><span>€ PRICE /maand</span></div> (within listing_item_tag)
                    # Note: Price element is usually within the listing_item_tag, not necessarily link_elem
                    price_el = listing_item_tag.select_one('div.text-xl.font-semibold, p.text-xl.font-semibold')
                    if price_el and '€' in price_el.text:
                        price = price_el.text.strip()
                    else: # Try data-testid for price (common in Funda)
                        price_el = listing_item_tag.select_one('[data-testid="price-rent"], [data-testid="price-sale"]')
                        if price_el:
                            price = price_el.text.strip()
                        else: # Broader search for price-like elements within listing_item_tag
                            possible_prices = listing_item_tag.find_all(string=re.compile(r'€\s*\d+([.,]\d+)?\s*(?:p\.m\.|p/m|per maand|/maand|/mnd|k\.k\.|v\.o\.n\.)?', re.IGNORECASE))
                            if possible_prices:
                                # Find the most complete looking price string from candidates
                                best_price_str = ""
                                for p_str_match in possible_prices:
                                    p_str = p_str_match.strip()
                                    # Attempt to get parent element's text if it's more complete
                                    parent_text = p_str_match.parent.get_text(separator=' ', strip=True) if p_str_match.parent else p_str
                                    if len(parent_text) > len(best_price_str) and len(parent_text) < 70: # Heuristic
                                        best_price_str = parent_text
                                if best_price_str:
                                    price = best_price_str
                                else:
                                    price = possible_prices[0].strip() # Fallback to first direct match
                            else:
                                self.logger.warning(f"Item {item_index} (ID: {listing_id}): Price not found via primary selectors.")

                    # Logging and Storing
                    self.logger.info(f"Item {item_index} Processed: ID='{listing_id}', Title='{title}', Price='{price}', Address='{address}', URL='{link}'")

                    if not listing_id: # Should be extremely rare now
                        self.logger.error(f"Item {item_index}: CRITICAL - listing_id is None before check. Skipping. HTML: {listing_item_tag.prettify()[:300]}")
                        continue

                    if listing_id not in self.seen_listings:
                        if title == "Title not found" or address == "Address not found" or price == "Price not found":
                            self.logger.warning(f"*** New listing ID {listing_id} but data is incomplete. Title: '{title}', Address: '{address}', Price: '{price}'. URL: {link}. Still adding and notifying.")
                            self.logger.debug(f"Incomplete new item HTML: {listing_item_tag.prettify()[:700]}...")

                        self.logger.info(f"*** New Funda listing detected: ID={listing_id}, Title='{title}' ***")
                        listing_info = {
                            "title": title,
                            "price": price,
                            "address": address,
                            "url": link,
                            "found_at": datetime.now().isoformat()
                        }
                        self.seen_listings[listing_id] = listing_info
                        new_listings_details.append(listing_info)
                    else:
                        self.logger.info(f"Item {item_index} (ID: {listing_id}, Title: '{title}') is an existing listing (already seen).")

                except Exception as e_item:
                    self.logger.error(f"Error processing a Funda listing item (Index: {item_index}, Tentative ID: {listing_id}): {e_item}", exc_info=True)
                    try:
                        self.logger.debug(f"Error occurred on item HTML: {listing_item_tag.prettify()[:700]}...")
                    except Exception as log_err:
                        self.logger.error(f"Could not log problematic HTML after item error: {log_err}")

            self._save_seen_listings()
            self.logger.info(f"Check complete. Found {len(new_listings_details)} new listings this run.")
            return new_listings_details

        except requests.exceptions.Timeout as req_timeout:
            self.logger.error(f"Network timeout fetching Funda page: {self.search_url} - {req_timeout}")
            return []
        except requests.exceptions.RequestException as req_err:
            self.logger.error(f"Network error fetching Funda page: {self.search_url} - {req_err}")
            return []
        except Exception as e_main:
            self.logger.error(f"Critical error in check_for_new_listings: {e_main}", exc_info=True)
            try:
                if 'response' in locals() and response: # Check if response object exists
                    with open(f"funda_dump_critical_error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html", "w", encoding="utf-8") as f:
                        f.write(response.text)
                    self.logger.info("Saved HTML dump after critical error.")
            except Exception as dump_err:
                self.logger.error(f"Failed to save error HTML dump after critical error: {dump_err}")
            return []

    def send_notification(self, listing):
        try:
            if not (self.twilio_account_sid and self.twilio_auth_token and
                    self.twilio_from_number and self.notification_number):
                self.logger.error("Twilio credentials not fully set in environment variables. Cannot send SMS notification.")
                return False

            client = Client(self.twilio_account_sid, self.twilio_auth_token)
            message_body = (
                f"🏠 F!\n\n"
                f"📌 {listing['title']}\n"
                f"📍 {listing['address']}\n"
                f"💰 {listing['price']}\n\n"
                f"🔗 {listing['url']}"
            )
            # Truncate message if too long for SMS (Twilio handles multi-part, but good practice)
            if len(message_body) > 1600: # Max length for concatenated SMS
                message_body = message_body[:1597] + "..."


            self.logger.info(f"Sending notification to {self.notification_number} for Funda listing: {listing['title']}")
            message_result = client.messages.create(
                body=message_body,
                from_=self.twilio_from_number,
                to=self.notification_number
            )
            self.logger.info(f"Funda notification sent! Twilio SID: {message_result.sid}, Status: {message_result.status}")
            return True

        except Exception as e:
            self.logger.error(f"Error sending Funda notification via Twilio: {e}", exc_info=True)
            return False

    def run(self):
        self.logger.info(f"Starting Funda monitor for {self.search_url}")
        self.logger.info(f"Check interval: {self.check_interval} seconds")
        self.logger.info(f"Saving seen listings to: {self.data_file}")

        if not (self.twilio_account_sid and self.twilio_auth_token and self.twilio_from_number and self.notification_number):
            self.logger.warning("Twilio environment variables not fully set. SMS notifications will NOT be sent.")

        self.logger.info("--- Performing initial check for Funda listings ---")
        try:
            new_initial_listings = self.check_for_new_listings()
            if new_initial_listings:
                self.logger.info(f"Found {len(new_initial_listings)} new Funda listings on initial check!")
                for listing in new_initial_listings:
                    self.logger.info(f"Initial New Listing: Title='{listing['title']}', Price='{listing['price']}', Address='{listing['address']}', URL='{listing['url']}'")
                    self.send_notification(listing)
                    time.sleep(random.uniform(1, 3)) # Small random delay
            else:
                self.logger.info("No new Funda listings found on initial check.")
        except Exception as e_initial:
            self.logger.error(f"Error during initial check: {e_initial}", exc_info=True)
        self.logger.info("--- Initial check complete ---")

        while True:
            try:
                # Add jitter to the wait interval to make scraping less predictable
                wait_interval = self.check_interval + random.uniform(-self.check_interval * 0.1, self.check_interval * 0.1)
                wait_interval = max(60, wait_interval) # Ensure at least 60s wait
                self.logger.info(f"Sleeping for approximately {wait_interval:.0f} seconds...")
                time.sleep(wait_interval)

                self.logger.info(f"--- Checking for new Funda listings at {datetime.now().isoformat()} ---")
                new_listings = self.check_for_new_listings()

                if new_listings:
                    for listing in new_listings:
                        self.send_notification(listing)
                        time.sleep(random.uniform(1, 3)) # Small random delay
                self.logger.info(f"--- Check cycle complete at {datetime.now().isoformat()} ---")

            except KeyboardInterrupt:
                self.logger.info("KeyboardInterrupt received. Shutting down Funda monitor.")
                self._save_seen_listings()
                break
            except Exception as e_loop:
                self.logger.error(f"Error in Funda monitor main loop: {e_loop}", exc_info=True)
                error_sleep = self.check_interval * 2 + random.uniform(0, 60) # Longer sleep after major error
                self.logger.info(f"Sleeping for {error_sleep:.0f} seconds after error before retrying.")
                time.sleep(error_sleep)

if __name__ == "__main__":
    # --- Basic Logging Setup for the script itself ---
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        handlers=[logging.StreamHandler()])
    logger_main = logging.getLogger(__name__)

    search_url_env = os.environ.get("FUNDA_SEARCH_URL")
    if not search_url_env:
        logger_main.error("ERROR: FUNDA_SEARCH_URL environment variable not set.")
        logger_main.info("Please set it to your desired Funda search results page URL.")
        # Example: https://www.funda.nl/zoeken/huur?selected_area=["amsterdam"]&price="1000-1500"&object_type=["apartment"]
        search_url_env = "https://www.funda.nl/zoeken/huur?selected_area=[%22leeuwarden%22]&price=%22200-800%22&object_type=[%22huis%22,%22apartment%22]" # Default for testing
        logger_main.info(f"Using default example URL for testing: {search_url_env}")
        # exit(1) # Optional: exit if URL not set for production

    check_interval_seconds = int(os.environ.get("FUNDA_CHECK_INTERVAL", "900"))
    data_filename = os.environ.get("FUNDA_DATA_FILE", "seen_funda_listings_v2.json") # Changed default to avoid overwrite

    # Check for Twilio variables (warnings only)
    if not os.environ.get("TWILIO_ACCOUNT_SID"): logger_main.warning("TWILIO_ACCOUNT_SID not set.")
    if not os.environ.get("TWILIO_AUTH_TOKEN"): logger_main.warning("TWILIO_AUTH_TOKEN not set.")
    if not os.environ.get("TWILIO_FROM_NUMBER"): logger_main.warning("TWILIO_FROM_NUMBER not set.")
    if not os.environ.get("NOTIFICATION_NUMBER"): logger_main.warning("NOTIFICATION_NUMBER not set.")

    monitor = FundaMonitor(
        search_url=search_url_env,
        check_interval=check_interval_seconds,
        data_file=data_filename
    )
    monitor.run()