# 📧 Dealdrip - Email-Only Price Tracker

A simple, reliable web application for tracking e-commerce product prices and sending **email notifications** when prices drop below your target.

## ✨ Features

- **📧 Email-Only Notifications**: Clean, simple email alerts - no confusion!
- **⏰ Automatic Price Monitoring**: Daily checks of your tracked products
- **🌐 Multi-Site Support**: Works with Amazon, Flipkart, Myntra, and many more
- **📱 Responsive Design**: Works perfectly on desktop and mobile
- **🔒 Privacy-First**: Each user gets only their own notifications
- **⚡ Lightning Fast**: Simplified system = better performance

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- Node.js 14+
- Gmail account (for sending emails)

### Installation

1. **Clone and setup**
   ```bash
   git clone <your-repo-url>
   cd dealdrip
   pip install -r requirements.txt
   npm install
   ```

2. **Configure email** (edit `.env` file)
   ```env
   EMAIL_USER=your-email@gmail.com
   EMAIL_APP_PASSWORD=your-gmail-app-password
   DEFAULT_EMAIL_RECIPIENT=your-email@gmail.com
   ```

3. **Run the app**
   ```bash
   python app.py
   ```

4. **Open in browser**: `http://localhost:5000`

## 📧 Gmail Setup (Required)

1. Enable 2-Factor Authentication on your Gmail
2. Go to Google Account Settings → Security → App Passwords
3. Generate an app password for "Mail"
4. Use this app password in your `.env` file

## 💡 How It Works

```
1. Enter product URL → 2. Set target price → 3. Add your email → 4. Get alerts!
```

**That's it!** No complex settings, no confusion. Just simple email notifications when your desired price is reached.

## 🛍️ Supported Sites

- **Amazon** (amazon.com, amazon.in)
- **Flipkart**
- **Myntra** 
- **Ajio**
- **Snapdeal**
- **eBay**
- **And many more...**

## 🏗️ System Architecture

```
User Interface → Flask Backend → Price Scraper → Email Service
     ↓              ↓              ↓              ↓
  Web Form     SQLite Database   Product APIs   Gmail SMTP
```

**Simple, reliable, effective.**

## 🎯 Why Email-Only?

- **📧 Universal**: Everyone has email, works everywhere
- **🔒 Private**: No cross-user notification mix-ups
- **⚡ Reliable**: Email infrastructure is rock-solid
- **🧹 Simple**: No complex routing or API dependencies
- **💰 Free**: No API costs or rate limits
