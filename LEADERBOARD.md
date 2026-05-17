# 🐛 CDBench Leaderboard System

A complete system for aggregating and visualizing **CDBench** (Controlled Multi-Fault Debugging with Reinforcement Learning and Iterative Repair) results with both CLI and web interfaces.

## Overview

The leaderboard system consists of:

1. **CLI Tool** (`scripts/leaderboard_cli.py`) - Aggregate results and export data
2. **Next.js Web Dashboard** (`packages/leaderboard-web/`) - Beautiful interactive visualization
3. **Sample Benchmark** (`benchmarks/cdbench_demo/`) - Demo tasks to get started

## Quick Start

### 1. View Results via CLI

```bash
# Show table format (default)
python3 -m scripts.leaderboard_cli results/runs

# Show detailed breakdown by benchmark
python3 -m scripts.leaderboard_cli results/runs --format detailed

# Export as JSON
python3 -m scripts.leaderboard_cli results/runs --format json > leaderboard.json

# Filter by agent name
python3 -m scripts.leaderboard_cli results/runs --agent haiku
```

### 2. Start Web Dashboard

```bash
cd packages/leaderboard-web
npm install
npm run dev
```

Visit `http://localhost:3000` to see the interactive leaderboard.

### 3. Run Sample Benchmark

```bash
# Generate sample tasks (already in benchmarks/cdbench_demo/)
# Then run a task:
python3 -m harness.run_task benchmarks/cdbench_demo/tasks/basic_list_comprehension_01 \
  --agent mini_claude_haiku_4_5 \
  --runtime local
```

## CLI Reference

### Usage

```bash
python3 -m scripts.leaderboard_cli <results_dir> [OPTIONS]
```

### Arguments

- `results_dir` - Path to results directory (e.g., `results/runs`)

### Options

- `--format {table|detailed|json|tasks}` - Output format (default: `table`)
- `--agent SUBSTRING` - Filter results by agent name
- `--output FILE` - Save JSON output to file

### Examples

```bash
# Show leaderboard table
python3 -m scripts.leaderboard_cli results/runs

# Show detailed view with per-benchmark stats
python3 -m scripts.leaderboard_cli results/runs --format detailed

# Export leaderboard to JSON
python3 -m scripts.leaderboard_cli results/runs --format json --output leaderboard.json

# Show only specific agent results
python3 -m scripts.leaderboard_cli results/runs --agent claude

# Export all task results as JSON
python3 -m scripts.leaderboard_cli results/runs --format tasks --output tasks.json
```

## Output Formats

### Table Format

```
🏆 BENCHMARK LEADERBOARD 🏆

Rank   Agent                          Tasks      Pass Rate    Avg Score   
----------------------------------------------------------------------
1      claude-opus                    32/35      91.4%        0.9180
2      gpt-4                          28/35      80.0%        0.8050
3      claude-haiku                   22/35      62.9%        0.6450
```

### Detailed Format

```
📊 DETAILED BENCHMARK RESULTS 📊

#1 claude-opus
  Overall: 32/35 passed (91.4%) | Avg Score: 0.9180
  By Benchmark:
    • pandas: 19/20 (95%) | Avg: 0.9400
    • scikit_learn: 13/15 (87%) | Avg: 0.8800

#2 gpt-4
  Overall: 28/35 passed (80.0%) | Avg Score: 0.8050
  By Benchmark:
    • pandas: 17/20 (85%) | Avg: 0.8200
    • scikit_learn: 11/15 (73%) | Avg: 0.7800
```

### JSON Format

```json
[
  {
    "rank": 1,
    "agent": "claude-opus",
    "total_tasks": 35,
    "passed": 32,
    "pass_rate": 91.4,
    "avg_score": 0.918,
    "benchmarks": {
      "pandas": {
        "total": 20,
        "passed": 19,
        "avg_score": 0.94
      },
      "scikit_learn": {
        "total": 15,
        "passed": 13,
        "avg_score": 0.88
      }
    }
  }
]
```

## Web Dashboard Features

### Leaderboard Page (`/`)

- **📊 Summary Stats** - Total agents, tasks, and average pass rate
- **🏆 Leaderboard Table** - Ranked agent performance with pass rates
- **📈 Pass Rate Chart** - Bar chart comparing agent performance
- **📊 Score Chart** - Line chart showing average scores
- **🔍 Detailed View** - Click any agent to see per-benchmark breakdown

### Interactive Features

- **Click agent row** to view detailed breakdown by benchmark
- **Hover over bars** to see exact values
- **Responsive design** - Works on desktop, tablet, and mobile
- **Dark theme** - Easy on the eyes
- **Real-time** - Fetches latest data from CLI via API

## API Integration

The web dashboard fetches leaderboard data via `/api/leaderboard` which runs the Python CLI tool.

### Endpoint

```
GET /api/leaderboard
```

**Response:**

```json
[
  {
    "rank": 1,
    "agent": "claude-opus",
    "total_tasks": 35,
    "passed": 32,
    "pass_rate": 91.4,
    "avg_score": 0.918,
    "benchmarks": { ... }
  }
]
```

### Configuration

Set environment variable in `.env.local`:

```
RESULTS_DIR=/path/to/results/runs
```

If not set, defaults to `../../results/runs` relative to web root.

## Sample Benchmark

The `benchmarks/cdbench_demo/` directory contains 3 simple Python tasks:

1. **`basic_list_comprehension_01`** - List comprehension with filtering
2. **`dict_merge_behavior_02`** - Dictionary merge operator (Python 3.9+)
3. **`string_format_none_03`** - String formatting with None values

### Structure

```
benchmarks/cdbench_demo/
  benchmark.json                # Benchmark metadata
  tasks/
    basic_list_comprehension_01/
      prompt.txt               # Question shown to agent
      task.json               # Task metadata
      validator.py            # Scoring script
    ...
```

### Running a Sample Task

```bash
python3 -m harness.run_task \
  benchmarks/cdbench_demo/tasks/basic_list_comprehension_01 \
  --agent mini_claude_haiku_4_5 \
  --runtime local
```

Results will be saved to `results/runs/` and appear in the leaderboard.

## Extending the System

### Add New Benchmark Tasks

Create a new task directory:

```bash
mkdir benchmarks/cdbench_demo/tasks/my_new_task

# Create required files:
# - prompt.txt (question for agent)
# - task.json (metadata)
# - validator.py (scoring logic)
```

### Create Custom Aggregation

Use the `LeaderboardAggregator` class:

```python
from scripts.leaderboard_cli import LeaderboardAggregator
from pathlib import Path

aggregator = LeaderboardAggregator(Path("results/runs"))
aggregator.scan_results()

# Get leaderboard
leaderboard = aggregator.get_leaderboard()

# Get agent stats
stats = aggregator.get_agent_stats()

# Get individual task results
tasks = aggregator.get_task_results(agent_filter="claude")
```

### Modify Web Dashboard

The web dashboard is a standard Next.js app:

```bash
cd packages/leaderboard-web

# Edit pages
nano app/page.tsx

# Add components
touch app/components/MyComponent.tsx

# Run dev server
npm run dev
```

## Troubleshooting

### "No results found"

Check that your `results/runs/` directory has properly formatted `result.json` files.

Required structure:

```
results/runs/
  task_name_1/
    run_id_1/
      result.json
      ...
  task_name_2/
    run_id_2/
      result.json
```

### Web dashboard shows only mock data

Make sure the Python environment is properly set up:

```bash
# Check Python version (3.9+)
python3 --version

# Try running CLI directly
python3 -m scripts.leaderboard_cli results/runs --format json
```

If the CLI works but the API doesn't, check Next.js logs for errors.

### Performance with large result sets

For 1000+ tasks, consider:

1. **Pagination** - Add pagination to the CLI and web dashboard
2. **Caching** - Cache aggregated results periodically
3. **Filtering** - Show subset of benchmarks by default
4. **Batch export** - Export results to S3 or similar

## Architecture

```
benchmark-creator/
├── scripts/
│   ├── leaderboard_cli.py        # CLI tool for aggregation
│   └── demo_leaderboard.sh       # Demo script
├── packages/
│   └── leaderboard-web/           # Next.js web dashboard
│       ├── app/
│       │   ├── page.tsx          # Main leaderboard page
│       │   └── api/
│       │       └── leaderboard/  # API endpoint
│       └── package.json
└── benchmarks/
    └── sample_demo/               # Sample benchmark tasks
        └── tasks/
            ├── basic_list_...
            ├── dict_merge_...
            └── string_format_...
```

## Performance Metrics

The system is optimized for:

- **Speed**: O(n) scan of results directory (minimal parsing)
- **Scalability**: Handles 1000+ tasks efficiently
- **Memory**: Streaming JSON parsing (not loading all at once)
- **Visualization**: Client-side rendering with Recharts

## License

Same as benchmark-creator
