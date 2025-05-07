import os
import threading
import logging
from flask import Flask, jsonify
from dotenv import load_dotenv

# Assuming your updated ParariusMonitor class is in pararius_monitor.py
from pararius_monitor import ParariusMonitor
# Assuming your updated FundaMonitor class is in funda_monitor.py
from funda_monitor import FundaMonitor

# Load environment variables from .env file
load_dotenv()

# Configure logging (ONCE at the application level)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
# Logger for the main application
app_logger = logging.getLogger('HousingMonitorApp') # Renamed to avoid conflict if 'logger' is used elsewhere

# Create Flask app
app = Flask(__name__)

# Global variables to store monitor instances
pararius_monitor_instance = None
funda_monitor_instance = None

def get_pararius_urls_from_env():
    """Collects all PARARIUS_SEARCH_URL_X variables from environment."""
    urls = []
    for i in range(1, 21): # Check for PARARIUS_SEARCH_URL_1 to PARARIUS_SEARCH_URL_20
        url_var = f'PARARIUS_SEARCH_URL_{i}'
        url = os.getenv(url_var)
        if url:
            urls.append(url)
        else:
            # Continue checking all numbers up to 20, allowing non-sequential numbering
            pass
    return urls

def validate_environment():
    """Validate required environment variables"""
    required_vars = [
        'TWILIO_ACCOUNT_SID',
        'TWILIO_AUTH_TOKEN',
        'TWILIO_FROM_NUMBER',
        'NOTIFICATION_NUMBER',
        'CHECK_INTERVAL'
    ]

    pararius_urls = get_pararius_urls_from_env()
    funda_url = os.getenv('FUNDA_SEARCH_URL')

    if not pararius_urls and not funda_url:
        app_logger.error("At least one search URL (PARARIUS_SEARCH_URL_X or FUNDA_SEARCH_URL) must be defined")
        return False # Simplified this part

    missing_vars = [var for var in required_vars if not os.getenv(var)]

    if 'CHECK_INTERVAL' not in missing_vars: # Only check if it's not already missing
        try:
            int(os.getenv('CHECK_INTERVAL'))
        except (ValueError, TypeError):
            app_logger.error("CHECK_INTERVAL is set but not a valid integer.")
            missing_vars.append('CHECK_INTERVAL (invalid integer)')
    elif 'CHECK_INTERVAL' in required_vars and not os.getenv('CHECK_INTERVAL'): # Explicitly missing
         pass # Already caught by missing_vars list

    if missing_vars:
        app_logger.error(f"Missing or invalid required environment variables: {', '.join(missing_vars)}")
        app_logger.error("Please set these in your .env file or environment")
        return False
    return True

def start_pararius_monitor():
    """Collects Pararius URLs and starts the monitor in a separate thread if any URLs are found."""
    global pararius_monitor_instance
    pararius_urls = get_pararius_urls_from_env()

    if not pararius_urls:
        app_logger.info("Pararius monitor not started (no PARARIUS_SEARCH_URL_X URLs configured)")
        return

    check_interval = int(os.getenv('CHECK_INTERVAL', '900'))
    app_logger.info(f"Starting Pararius monitor for {len(pararius_urls)} URLs: {pararius_urls}")
    app_logger.info(f"Check interval: {check_interval} seconds")

    try:
        pararius_monitor_instance = ParariusMonitor(pararius_urls, check_interval=check_interval)
        pararius_monitor_instance.run()
    except ValueError as e:
        app_logger.error(f"Error starting Pararius monitor: {e}. Check URL list or initialization.")
    except Exception as e:
        app_logger.error(f"An unexpected error occurred in the Pararius monitor thread: {e}", exc_info=True)

def start_funda_monitor():
    """Starts the Funda monitor in a separate thread if URL is configured."""
    global funda_monitor_instance
    search_url = os.getenv('FUNDA_SEARCH_URL')

    if not search_url:
        app_logger.info("Funda monitor not started (no FUNDA_SEARCH_URL configured)")
        return

    check_interval = int(os.getenv('CHECK_INTERVAL', '900'))
    app_logger.info(f"Starting Funda monitor for {search_url}")
    app_logger.info(f"Check interval: {check_interval} seconds")

    try:
        funda_monitor_instance = FundaMonitor(search_url, check_interval=check_interval)
        funda_monitor_instance.run()
    except Exception as e:
        app_logger.error(f"An unexpected error occurred in the Funda monitor thread: {e}", exc_info=True)

@app.route('/')
def home():
    """Home route to check if the app is running and monitors are configured."""
    monitor_status = {
        "status": "app_running",
        "monitors": {}
    }
    pararius_urls_configured = get_pararius_urls_from_env()
    funda_url_configured = os.getenv('FUNDA_SEARCH_URL')

    if pararius_urls_configured:
        monitor_status["monitors"]["pararius"] = {
            "configured_urls_count": len(pararius_urls_configured),
            "running": pararius_monitor_instance is not None and pararius_thread.is_alive()
        }
    if funda_url_configured:
        monitor_status["monitors"]["funda"] = {
            "configured_url": funda_url_configured,
            "running": funda_monitor_instance is not None and funda_thread.is_alive()
        }
    if not monitor_status["monitors"]:
        monitor_status["message"] = "No monitor URLs configured. App is running but no monitoring is active."
    return jsonify(monitor_status)

@app.route('/health')
def health():
    """Health check route - basic check if app and threads are alive."""
    pararius_running = pararius_monitor_instance is not None and pararius_thread is not None and pararius_thread.is_alive()
    funda_running = funda_monitor_instance is not None and funda_thread is not None and funda_thread.is_alive()
    
    # Check if threads were meant to be started
    pararius_configured = bool(get_pararius_urls_from_env())
    funda_configured = bool(os.getenv('FUNDA_SEARCH_URL'))

    health_status = {
        "status": "healthy_if_threads_match_config",
        "app_thread_running": True,
        "pararius_monitor": {
            "configured": pararius_configured,
            "thread_started_and_alive": pararius_running
        },
        "funda_monitor": {
            "configured": funda_configured,
            "thread_started_and_alive": funda_running
        }
    }
    # Overall app health can be more nuanced
    if (pararius_configured and not pararius_running) or \
       (funda_configured and not funda_running):
        health_status["status"] = "degraded_missing_monitor_threads"

    return jsonify(health_status)

# Global thread variables for health check
pararius_thread = None
funda_thread = None

if __name__ == '__main__':
    if validate_environment():
        app_logger.info("Environment validation successful.")

        start_pararius_flag = bool(get_pararius_urls_from_env())
        start_funda_flag = bool(os.getenv('FUNDA_SEARCH_URL'))

        if start_pararius_flag:
            pararius_thread = threading.Thread(target=start_pararius_monitor, daemon=True)
            pararius_thread.start()
            app_logger.info("Pararius monitor thread initialization initiated.")
        else:
            app_logger.info("No Pararius URLs configured. Pararius monitor thread will not be started.")

        if start_funda_flag:
            funda_thread = threading.Thread(target=start_funda_monitor, daemon=True)
            funda_thread.start()
            app_logger.info("Funda monitor thread initialization initiated.")
        else:
            app_logger.info("No Funda URL configured. Funda monitor thread will not be started.")

        if start_pararius_flag or start_funda_flag:
            port = int(os.getenv('PORT', 5000))
            app_logger.info(f"Starting Flask server on http://0.0.0.0:{port}")
            app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False) # use_reloader=False is good for threaded apps
        else:
            app_logger.info("No monitors configured to start. Flask server will not run. Application will exit.")
            # If you want the app to stay alive for health checks even with no monitors, remove this else block
            # and the conditional check for starting Flask.
    else:
        app_logger.error("Environment validation failed. Cannot start application.")