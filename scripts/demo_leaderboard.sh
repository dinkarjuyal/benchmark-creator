#!/bin/bash
# Demo script - show how to use the leaderboard CLI and start the web server

set -e

echo "🏆 Benchmark Creator - Leaderboard Demo 🏆"
echo ""
echo "This demo shows how to:"
echo "  1. View leaderboard from CLI"
echo "  2. Start the Next.js web dashboard"
echo ""

# Show CLI usage
echo "📊 CLI Leaderboard Formats"
echo "=================================="
echo ""
echo "Table format (default):"
python3 -m scripts.leaderboard_cli results/runs --format table

echo ""
echo "Detailed format with per-benchmark breakdown:"
python3 -m scripts.leaderboard_cli results/runs --format detailed | head -20

echo ""
echo "JSON format (for integration):"
python3 -m scripts.leaderboard_cli results/runs --format json | head -30

echo ""
echo "=================================="
echo "✅ CLI Demo Complete!"
echo ""
echo "🌐 To start the web dashboard:"
echo ""
echo "   cd packages/leaderboard-web"
echo "   npm install"
echo "   npm run dev"
echo ""
echo "Then visit: http://localhost:3000"
echo ""
