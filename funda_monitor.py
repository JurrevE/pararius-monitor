import requests
import time
import json
import os
from bs4 import BeautifulSoup
from datetime import datetime
from twilio.rest import Client
import logging
import random
import re # Import regex module for ID extraction

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
            json.dump(self.seen_listings, f, indent=4) # Added indent for readability

    def check_for_new_listings(self):
        try:
            self.logger.info(f"Fetching Funda listings from: {self.search_url}")
            response = requests.get(self.search_url, headers=self._get_random_headers())
            response.raise_for_status() # Raise an exception for bad status codes
            soup = BeautifulSoup(response.text, 'html.parser')

            # Save raw HTML for debugging (optional)
            # try:
            #     with open("funda_dump.html", "w", encoding="utf-8") as f:
            #         f.write(soup.prettify())
            #     self.logger.info("Saved HTML dump to funda_dump.html")
            # except Exception as dump_err:
            #     self.logger.error(f"Failed to save HTML dump: {dump_err}")

            # --- Updated Selector Logic ---
            # Primary selector based on the provided HTML structure
            listings = soup.select('div.border-b.pb-3')
            self.logger.info(f"Found {len(listings)} potential listings using primary selector ('div.border-b.pb-3')")

            # Fallback to original selectors if the new one fails
            if not listings:
                self.logger.warning("Primary selector found no listings. Trying original selector ('ol.search-results li.search-result')...")
                listings = soup.select('ol.search-results li.search-result')
                self.logger.info(f"Found {len(listings)} listings using original selector")

            if not listings:
                 self.logger.warning("Original selector also found no listings. Trying fallback '[data-test-id=\"search-result-item\"]'...")
                 listings = soup.select('[data-test-id="search-result-item"]') # Another common pattern
                 self.logger.info(f"Found {len(listings)} listings using data-test-id selector")

            if not listings:
                 self.logger.warning("No listings found with any known selector. Funda structure might have changed.")
                 # Optionally save HTML dump here specifically when no listings are found
                 try:
                     with open("funda_dump_no_listings.html", "w", encoding="utf-8") as f:
                         f.write(soup.prettify())
                     self.logger.info("Saved HTML dump to funda_dump_no_listings.html for analysis.")
                 except Exception as dump_err:
                     self.logger.error(f"Failed to save no-listings HTML dump: {dump_err}")
                 return [] # Return empty list if no listings found

            # Print sample structure for debugging if listings were found
            if listings:
                self.logger.info("Sample listing HTML structure (first found item):")
                self.logger.info(listings[0].prettify()[:700] + "...") # Increased length slightly

            new_listings = []
            for listing in listings:
                listing_id = None
                title = "Title not found"
                price = "Price not found"
                address = "Address not found"
                link = ""

                try:
                    # --- New Extraction Logic based on provided HTML ---

                    # 1. Find the main link element (contains URL, title, address)
                    link_elem = listing.select_one('a[data-testid="listingDetailsAddress"], a.text-secondary-70') # Use data-testid first, fallback to class
                    if not link_elem:
                        link_elem = listing.select_one('a[href*="/detail/"]') # More general fallback for the link
                        if not link_elem:
                           self.logger.warning("Could not find the main link element in a listing item. Skipping.")
                           # Log the problematic item's HTML for debugging
                           self.logger.debug(f"Skipped item HTML: {listing.prettify()[:500]}...")
                           continue # Skip this listing item

                    # 2. Extract URL and Listing ID
                    href = link_elem.get('href')
                    if href:
                        link = "https://www.funda.nl" + href.split('?')[0] # Prepend base URL, remove query params

                        # Extract ID using regex for robustness (finds the number sequence)
                        match = re.search(r'/(\d+)/?$', href)
                        if match:
                            listing_id = match.group(1)
                        else:
                            self.logger.warning(f"Could not extract numeric ID from URL: {href}. Using full href as fallback ID.")
                            listing_id = href # Fallback ID
                    else:
                        self.logger.warning("Found link element but 'href' attribute is missing.")
                        listing_id = str(hash(listing.text)) # Fallback ID if no href

                    # 3. Extract Title (Street/Name part)
                    title_elem = link_elem.select_one('div.flex.font-semibold span.truncate')
                    if title_elem:
                        title = title_elem.text.strip()
                    else: # Fallback selector
                         title_elem = link_elem.select_one('h2') # Often the address is in an h2 inside the link
                         if title_elem:
                              title = title_elem.text.strip().split('\n')[0] # Take first line if multiple

                    # 4. Extract Address (Postal Code/City part)
                    address_elem = link_elem.select_one('div.truncate.text-neutral-80')
                    if address_elem:
                        address = address_elem.text.strip()
                    else: # Fallback attempt from the title element if needed
                        if title_elem and '\n' in title_elem.text:
                             try:
                                 address = title_elem.text.strip().split('\n')[1].strip()
                             except IndexError:
                                 address = "Address details not found"

                    # 5. Extract Price
                    # Price is often in a div sibling (+) to the h2 containing the link/address
                    price_container = listing.select_one('h2 + div.font-semibold, h2 + div[class*="font-semibold"]')
                    if price_container:
                         price_elem = price_container.select_one('div.truncate, span') # Look for truncate div or just a span
                         if price_elem:
                             price = price_elem.text.strip()
                         else: # Try finding price based on common text pattern directly within the container
                             price_text = price_container.text.strip()
                             if '€' in price_text and ('/maand' in price_text or '/mnd' in price_text or 'k.k.' in price_text):
                                 price = price_text
                             else:
                                 price = "Price format not recognized"
                    else:
                        # Fallback: Search more broadly if the relative selector fails
                        price_elem = listing.select_one('div[class*="price"], span[class*="price"]') # Common class names
                        if price_elem:
                             price = price_elem.text.strip()


                    # --- End of New Extraction Logic ---

                    self.logger.info(f"Processed: ID={listing_id}, Title='{title}', Price='{price}', Address='{address}', URL='{link}'")

                    if listing_id not in self.seen_listings:
                        self.logger.info(f"*** New Funda listing detected: {title} ***")
                        listing_info = {
                            "title": title,
                            "price": price,
                            "address": address, # Keep address separate
                            "url": link,
                            "found_at": datetime.now().isoformat()
                        }
                        self.seen_listings[listing_id] = listing_info
                        new_listings.append(listing_info)
                    else:
                        self.logger.info(f"Existing Funda listing (already seen): {title}")

                except Exception as e:
                    self.logger.error(f"Error processing a Funda listing item: {e}", exc_info=True) # Add traceback
                    # Log the problematic item's HTML
                    try:
                        self.logger.debug(f"Error occurred on item HTML: {listing.prettify()[:500]}...")
                    except Exception as log_err:
                         self.logger.error(f"Could not log problematic HTML: {log_err}")


            self._save_seen_listings()
            self.logger.info(f"Check complete. Found {len(new_listings)} new listings this run.")
            return new_listings

        except requests.exceptions.RequestException as req_err:
             self.logger.error(f"Network error fetching Funda page: {req_err}")
             return [] # Return empty on network errors
        except Exception as e:
            self.logger.error(f"Critical error checking for new Funda listings: {e}", exc_info=True) # Add traceback
             # Save HTML dump on critical errors for debugging
            try:
                if 'response' in locals() and response:
                    with open("funda_dump_error.html", "w", encoding="utf-8") as f:
                        f.write(response.text) # Save raw text which might be useful if parsing failed
                    self.logger.info("Saved error HTML dump to funda_dump_error.html.")
            except Exception as dump_err:
                 self.logger.error(f"Failed to save error HTML dump: {dump_err}")
            return []

    def send_notification(self, listing):
        try:
            if not (self.twilio_account_sid and self.twilio_auth_token and
                    self.twilio_from_number and self.notification_number):
                self.logger.error("Twilio credentials not set via environment variables (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, NOTIFICATION_NUMBER). Can't send notification.")
                return False

            client = Client(self.twilio_account_sid, self.twilio_auth_token)
            # Refined message format
            message_body = (
                f"🏠 New Funda Listing!\n\n"
                f"📌 {listing['title']}\n"
                f"📍 {listing['address']}\n"
                f"💰 {listing['price']}\n\n"
                f"🔗 {listing['url']}"
            )

            self.logger.info(f"Sending notification to {self.notification_number} for Funda listing: {listing['title']}")

            message_result = client.messages.create(
                body=message_body,
                from_=self.twilio_from_number,
                to=self.notification_number
            )

            self.logger.info(f"Funda notification sent! Twilio SID: {message_result.sid}")
            return True

        except Exception as e:
            self.logger.error(f"Error sending Funda notification via Twilio: {e}", exc_info=True) # Add traceback
            return False

    def run(self):
        self.logger.info(f"Starting Funda monitor for {self.search_url}")
        self.logger.info(f"Check interval: {self.check_interval} seconds")
        self.logger.info(f"Saving seen listings to: {self.data_file}")
        # Check for Twilio creds at start
        if not (self.twilio_account_sid and self.twilio_auth_token and self.twilio_from_number and self.notification_number):
             self.logger.warning("Twilio environment variables not fully set. Notifications will not be sent.")


        # Perform an initial check immediately
        self.logger.info("--- Performing initial check for Funda listings ---")
        new_initial_listings = self.check_for_new_listings()

        if new_initial_listings:
            self.logger.info(f"Found {len(new_initial_listings)} new Funda listings on initial check!")
            for listing in new_initial_listings:
                # Log details before sending
                self.logger.info(f"Initial New Listing: Title='{listing['title']}', Price='{listing['price']}', Address='{listing['address']}', URL='{listing['url']}'")
                self.send_notification(listing)
                time.sleep(1) # Small delay between initial notifications
        else:
            self.logger.info("No new Funda listings found on initial check.")
        self.logger.info("--- Initial check complete ---")


        # Main monitoring loop
        while True:
            try:
                wait_interval = self.check_interval + random.uniform(-30, 30) # Add jitter
                self.logger.info(f"Sleeping for approximately {wait_interval:.0f} seconds...")
                time.sleep(wait_interval)

                self.logger.info(f"--- Checking for new Funda listings at {datetime.now().isoformat()} ---")
                new_listings = self.check_for_new_listings()

                if new_listings:
                    # Already logged inside check_for_new_listings
                    for listing in new_listings:
                        self.send_notification(listing)
                        time.sleep(1) # Small delay between notifications
                # else: # No need to log this again, check_for_new_listings does it
                #     self.logger.info("No new Funda listings found this cycle.")
                self.logger.info(f"--- Check cycle complete at {datetime.now().isoformat()} ---")


            except KeyboardInterrupt:
                 self.logger.info("KeyboardInterrupt received. Shutting down Funda monitor.")
                 self._save_seen_listings() # Ensure data is saved on exit
                 break
            except Exception as e:
                self.logger.error(f"Error in Funda monitor main loop: {e}", exc_info=True)
                # Sleep longer after a major loop error
                error_sleep = 120 + random.uniform(0, 60)
                self.logger.info(f"Sleeping for {error_sleep:.0f} seconds after error before retrying.")
                time.sleep(error_sleep)

# Example usage (ensure environment variables are set)
if __name__ == "__main__":
    # Get Funda URL from environment variable, or use the default Leeuwarden example
    # Example: https://www.funda.nl/zoeken/huur?selected_area=["amsterdam"]&price="1000-1500"&object_type=["apartment"]
    search_url_env = os.environ.get("FUNDA_SEARCH_URL")
    if not search_url_env:
         print("ERROR: FUNDA_SEARCH_URL environment variable not set.")
         print("Please set it to your desired Funda search results page URL.")
         # Example default (you should replace this)
         search_url_env = "https://www.funda.nl/zoeken/huur?selected_area=[%22leeuwarden%22]&price=%22200-800%22&object_type=[%22house%22,%22apartment%22]"
         print(f"Using default example URL: {search_url_env}")
         # exit(1) # Optional: exit if URL not set

    check_interval_seconds = int(os.environ.get("FUNDA_CHECK_INTERVAL", "900")) # Default 15 minutes
    data_filename = os.environ.get("FUNDA_DATA_FILE", "seen_funda_listings.json") # Allow overriding data file name

    # --- Ensure Twilio Variables are set ---
    if not os.environ.get("TWILIO_ACCOUNT_SID"): print("Warning: TWILIO_ACCOUNT_SID not set.")
    if not os.environ.get("TWILIO_AUTH_TOKEN"): print("Warning: TWILIO_AUTH_TOKEN not set.")
    if not os.environ.get("TWILIO_FROM_NUMBER"): print("Warning: TWILIO_FROM_NUMBER not set.")
    if not os.environ.get("NOTIFICATION_NUMBER"): print("Warning: NOTIFICATION_NUMBER not set.")
    # ---

    monitor = FundaMonitor(
        search_url=search_url_env,
        check_interval=check_interval_seconds,
        data_file=data_filename
        )
    monitor.run()