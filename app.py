import os
import threading
import logging
from flask import Flask, jsonify
from dotenv import load_dotenv
from pararius_monitor import ParariusMonitor

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger('ParariusApp')

# Create Flask app
app = Flask(__name__)

# Global variable to store monitor instance
monitor = None

def validate_environment():
    """Validate required environment variables"""
    required_vars = [
        'PARARIUS_SEARCH_URL',
        'TWILIO_ACCOUNT_SID',
        'TWILIO_AUTH_TOKEN',
        'TWILIO_FROM_NUMBER',
        'NOTIFICATION_NUMBER'
    ]
    
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        logger.error("Please set these in your Railway project variables")
        return False
    
    return True

def start_monitor():
    """Start the Pararius monitor in a separate thread"""
    global monitor
    
    search_url = os.getenv('PARARIUS_SEARCH_URL')
    check_interval = int(os.getenv('CHECK_INTERVAL', '900'))  # Default to 15 minutes
    
    logger.info(f"Starting Pararius monitor for {search_url}")
    logger.info(f"Check interval: {check_interval} seconds")
    
    monitor = ParariusMonitor(search_url, check_interval=check_interval)
    monitor.run()

@app.route('/')
def home():
    """Home route to check if the app is running"""
    return jsonify({
        "status": "running",
        "monitoring": os.getenv('PARARIUS_SEARCH_URL', 'No URL configured')
    })

@app.route('/health')
def health():
    """Health check route"""
    global monitor
    
    return jsonify({
        "status": "healthy",
        "monitor_running": monitor is not None
    })

if __name__ == '__main__':
    # Validate environment variables before starting
    if validate_environment():
        # Start monitor in a separate thread
        monitor_thread = threading.Thread(target=start_monitor, daemon=True)
        monitor_thread.start()
        
        # Start Flask server
        port = int(os.getenv('PORT', 5000))
        app.run(host='0.0.0.0', port=port)
    else:
        logger.error("Cannot start application. Missing required environment variables.")