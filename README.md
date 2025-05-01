# Pararius Listing Monitor

This application monitors [Pararius](https://www.pararius.com) for new rental listings and sends you notifications via SMS/WhatsApp when new properties become available. It's designed to be deployed on Railway for 24/7 monitoring.

## Features

- Automatically checks Pararius at regular intervals
- Remembers previously seen listings to avoid duplicate notifications
- Sends immediate notifications via Twilio (SMS/WhatsApp)
- Customizable search filters and check frequency
- Runs on Railway's free tier

## How It Works

1. The app periodically checks your specified Pararius search URL
2. When new listings are found, it sends you a notification with details
3. A simple web server runs to keep the Railway deployment active

## Deployment Instructions

### 1. Prerequisites

- [Twilio](https://www.twilio.com) account (for sending notifications)
- [Railway](https://railway.app) account (for hosting the app)
- [GitHub](https://github.com) account (to deploy from)

### 2. Fork/Clone This Repository

Fork this repository to your GitHub account or clone it and create a new repository:

```bash
git clone <this-repo-url>
cd pararius-monitor
git remote set-url origin <your-new-repo-url>
git push -u origin main
```

### 3. Set Up Railway Project

1. Go to [Railway](https://railway.app) and log in
2. Click "New Project" → "Deploy from GitHub repo"
3. Select your repository
4. Click "Deploy Now"

### 4. Configure Environment Variables

In your Railway project:

1. Go to "Variables"
2. Add the following variables:

```
PARARIUS_SEARCH_URL=https://www.pararius.com/apartments/amsterdam/1-2-bedrooms/0-1500
CHECK_INTERVAL=900
TWILIO_ACCOUNT_SID=your_account_sid_here
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_FROM_NUMBER=+1234567890
NOTIFICATION_NUMBER=+1234567890
```

Replace the values with your actual Twilio credentials and desired Pararius search URL.

### 5. Deploy

After setting the variables, Railway will automatically redeploy your application. You can check the deployment status in the "Deployments" tab.

## Customizing Your Search

1. Go to [Pararius](https://www.pararius.com)
2. Apply filters for your desired location, price range, number of bedrooms, etc.
3. Copy the URL from your browser
4. Update the `PARARIUS_SEARCH_URL` environment variable in Railway

## Troubleshooting

Check the application logs in Railway for any errors:

1. Go to your project in Railway
2. Click on "Deployments" tab
3. Select the latest deployment
4. View the logs

Common issues:
- Invalid Twilio credentials - Check your Account SID and Auth Token
- Pararius structure changes - The website may change, requiring code updates
- Rate limiting - Try increasing your CHECK_INTERVAL

## Local Development

To run the application locally:

1. Create a `.env` file based on `.env.template`
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Run the application:
   ```
   python app.py
   ```

## Important Notes

- Railway's free tier has usage limitations - monitor your usage
- Set a reasonable check interval (15+ minutes recommended) to avoid IP blocking
- Use responsibly and respect Pararius's terms of service