# CDBench Leaderboard Web

A beautiful Next.js dashboard for visualizing CDBench (Controlled Multi-Fault Debugging) results.

## Features

- 📊 Real-time leaderboard with agent rankings
- 📈 Interactive charts (pass rates, average scores)
- 🎯 Per-benchmark performance breakdown
- 🎨 Modern dark theme UI
- 📱 Responsive design

## Setup

```bash
cd packages/leaderboard-web
npm install
npm run dev
```

Visit `http://localhost:3000` to see the leaderboard.

## Configuration

Set the `RESULTS_DIR` environment variable to point to your benchmark results:

```bash
RESULTS_DIR=/path/to/results/runs npm run dev
```

If not set, defaults to `../../results/runs` relative to the project.

## Building for Production

```bash
npm run build
npm start
```

## Data Integration

The frontend fetches leaderboard data from the `/api/leaderboard` endpoint, which runs the Python CLI tool to aggregate results. The page includes fallback mock data for demonstration.
