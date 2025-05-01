import os
import threading
import logging
from flask import Flask, jsonify
from dotenv import load_dotenv
from pararius_monitor import ParariusMonitor
from funda_monitor import FundaMonitor

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger('HousingMonitorApp')

# Create Flask app
app = Flask(__name__)

# Global variables to store monitor instances
pararius_monitor = None
funda_monitor = None

def validate_environment():
    """Validate required environment variables"""
    required_vars = [
        'TWILIO_ACCOUNT_SID',
        'TWILIO_AUTH_TOKEN',
        'TWILIO_FROM_NUMBER',
        'NOTIFICATION_NUMBER'
    ]
    
    # Check for at least one search URL
    if not os.getenv('PARARIUS_SEARCH_URL') and not os.getenv('FUNDA_SEARCH_URL'):
        logger.error("At least one search URL (PARARIUS_SEARCH_URL or FUNDA_SEARCH_URL) must be defined")
        required_vars.append('PARARIUS_SEARCH_URL or FUNDA_SEARCH_URL')
    
    missing_vars = [var for var in required_vars if not os.getenv(var) and var not in ['PARARIUS_SEARCH_URL or FUNDA_SEARCH_URL']]
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        logger.error("Please set these in your environment variables")
        return False
    
    return True

def start_pararius_monitor():
    """Start the Pararius monitor in a separate thread"""
    global pararius_monitor
    
    search_url = os.getenv('PARARIUS_SEARCH_URL')
    if not search_url:
        logger.info("Pararius monitor not started (no URL configured)")
        return
        
    check_interval = int(os.getenv('PARARIUS_CHECK_INTERVAL', '900'))  # Default to 15 minutes
    
    logger.info(f"Starting Pararius monitor for {search_url}")
    logger.info(f"Check interval: {check_interval} seconds")
    
    pararius_monitor = ParariusMonitor(search_url, check_interval=check_interval)
    pararius_monitor.run()

def start_funda_monitor():
    """Start the Funda monitor in a separate thread"""
    global funda_monitor
    
    search_url = os.getenv('FUNDA_SEARCH_URL')
    if not search_url:
        logger.info("Funda monitor not started (no URL configured)")
        return
        
    check_interval = int(os.getenv('FUNDA_CHECK_INTERVAL', '900'))  # Default to 15 minutes
    
    logger.info(f"Starting Funda monitor for {search_url}")
    logger.info(f"Check interval: {check_interval} seconds")
    
    funda_monitor = FundaMonitor(search_url, check_interval=check_interval)
    funda_monitor.run()

@app.route('/')
def home():
    """Home route to check if the app is running"""
    monitor_status = {
        "status": "running",
        "monitors": {}
    }
    
    if os.getenv('PARARIUS_SEARCH_URL'):
        monitor_status["monitors"]["pararius"] = {
            "url": os.getenv('PARARIUS_SEARCH_URL'),
            "running": pararius_monitor is not None
        }
        
    if os.getenv('FUNDA_SEARCH_URL'):
        monitor_status["monitors"]["funda"] = {
            "url": os.getenv('FUNDA_SEARCH_URL'),
            "running": funda_monitor is not None
        }
    
    return jsonify(monitor_status)

@app.route('/health')
def health():
    """Health check route"""
    return jsonify({
        "status": "healthy",
        "pararius_monitor_running": pararius_monitor is not None,
        "funda_monitor_running": funda_monitor is not None
    })

if __name__ == '__main__':
    # Validate environment variables before starting
    if validate_environment():
        # Start both monitors in separate threads if configured
        
        # Start Pararius monitor if URL is configured
        if os.getenv('PARARIUS_SEARCH_URL'):
            pararius_thread = threading.Thread(target=start_pararius_monitor, daemon=True)
            pararius_thread.start()
            logger.info("Pararius monitor thread started")
        
        # Start Funda monitor if URL is configured
        if os.getenv('FUNDA_SEARCH_URL'):
            funda_thread = threading.Thread(target=start_funda_monitor, daemon=True)
            funda_thread.start()
            logger.info("Funda monitor thread started")
        
        # Start Flask server
        port = int(os.getenv('PORT', 5000))
        app.run(host='0.0.0.0', port=port)
    else:
        logger.error("Cannot start application. Missing required environment variables.")