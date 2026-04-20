#!/bin/bash
# MPC Arbitrage Bot - Local Development Startup Script

set -e

echo "🚀 Starting MPC Arbitrage Bot..."

# Create necessary directories
mkdir -p config logs

# Install dependencies if not present
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

echo "📦 Activating virtual environment..."
source venv/bin/activate

echo "📦 Installing dependencies..."
pip install -r requirements.txt

echo ""
echo "✅ Setup complete!"
echo ""
echo "To start the bot:"
echo "  1. Start the bot only:"
echo "     python -m bot.main_bot"
echo ""
echo "  2. Start the dashboard only:"
echo "     streamlit run dashboard/app.py"
echo ""
echo "  3. Start both (in separate terminals):"
echo "     Terminal 1: python -m bot.main_bot"
echo "     Terminal 2: streamlit run dashboard/app.py"
echo ""
