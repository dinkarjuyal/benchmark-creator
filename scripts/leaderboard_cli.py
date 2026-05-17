#!/usr/bin/env python3
"""
Leaderboard CLI - Aggregate and display benchmark results across agents.

Usage:
  python -m scripts.leaderboard_cli results/runs
  python -m scripts.leaderboard_cli results/runs --format json --output leaderboard.json
  python -m scripts.leaderboard_cli results/runs --agent mini_claude_haiku_4_5
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional, Dict
from collections import defaultdict
from dataclasses import dataclass, asdict


@dataclass
class TaskResult:
    task_id: str
    agent_name: str
    score: float
    passed: bool
    description: str
    benchmark: str
    run_id: str


@dataclass
class AgentStats:
    agent_name: str
    total_tasks: int
    passed_tasks: int
    avg_score: float
    pass_rate: float
    benchmarks: Dict[str, Dict[str, Any]]


class LeaderboardAggregator:
    def __init__(self, results_dir: Path):
        self.results_dir = Path(results_dir)
        self.results: list[TaskResult] = []
        
    def scan_results(self) -> None:
        """Scan results directory and aggregate task results."""
        for task_dir in self.results_dir.iterdir():
            if not task_dir.is_dir():
                continue
            
            # Each task_dir has subdirectories for different runs
            for run_dir in task_dir.iterdir():
                if not run_dir.is_dir():
                    continue
                    
                result_file = run_dir / "result.json"
                if not result_file.exists():
                    continue
                    
                try:
                    with open(result_file) as f:
                        result_data = json.load(f)
                    
                    task_result = self._parse_result(result_data, task_dir.name, run_dir.name)
                    if task_result:
                        self.results.append(task_result)
                except (json.JSONDecodeError, KeyError) as e:
                    print(f"⚠️  Error parsing {result_file}: {e}", file=sys.stderr)
                    continue
    
    def _parse_result(self, data: dict, task_id: str, run_id: str) -> Optional[TaskResult]:
        """Parse a single result.json file."""
        try:
            agent_name = data.get("agent_name", "unknown")
            description = data.get("description", "")
            
            # Extract score from validation step
            score = 0.0
            passed = False
            
            steps = data.get("steps", [])
            for step in steps:
                if step.get("step") == "validate":
                    # Score is in step['score'] or inferred from exit_code
                    score = step.get("score", 0.0)
                    passed = step.get("exit_code") == 0
                    break
            
            # Infer benchmark from task_id or directory structure
            benchmark = task_id.split("_")[0] if "_" in task_id else "unknown"
            
            return TaskResult(
                task_id=task_id,
                agent_name=agent_name,
                score=score,
                passed=passed,
                description=description,
                benchmark=benchmark,
                run_id=run_id,
            )
        except Exception as e:
            print(f"⚠️  Error parsing result for task {task_id}: {e}", file=sys.stderr)
            return None
    
    def get_agent_stats(self) -> Dict[str, AgentStats]:
        """Calculate statistics per agent."""
        agent_data: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "total": 0,
            "passed": 0,
            "scores": [],
            "benchmarks": defaultdict(lambda: {"total": 0, "passed": 0, "avg_score": 0.0}),
        })
        
        for result in self.results:
            agent = agent_data[result.agent_name]
            agent["total"] += 1
            agent["scores"].append(result.score)
            
            if result.passed:
                agent["passed"] += 1
            
            # Track per-benchmark stats
            bench = agent["benchmarks"][result.benchmark]
            bench["total"] += 1
            if result.passed:
                bench["passed"] += 1
            bench["scores"] = bench.get("scores", []) + [result.score]
        
        # Convert to AgentStats objects
        stats = {}
        for agent_name, data in agent_data.items():
            scores = data["scores"]
            total = data["total"]
            passed = data["passed"]
            avg_score = sum(scores) / len(scores) if scores else 0.0
            
            # Compute per-benchmark averages
            benchmarks = {}
            for bench_name, bench_data in data["benchmarks"].items():
                bench_scores = bench_data.get("scores", [])
                benchmarks[bench_name] = {
                    "total": bench_data["total"],
                    "passed": bench_data["passed"],
                    "avg_score": sum(bench_scores) / len(bench_scores) if bench_scores else 0.0,
                }
            
            stats[agent_name] = AgentStats(
                agent_name=agent_name,
                total_tasks=total,
                passed_tasks=passed,
                avg_score=avg_score,
                pass_rate=passed / total if total > 0 else 0.0,
                benchmarks=benchmarks,
            )
        
        return stats
    
    def get_leaderboard(self, agent_filter: Optional[str] = None) -> list:
        """Get sorted leaderboard by pass rate, then average score."""
        stats = self.get_agent_stats()
        
        leaderboard = []
        for agent_name in sorted(stats.keys()):
            if agent_filter and agent_filter not in agent_name:
                continue
                
            agent = stats[agent_name]
            leaderboard.append({
                "rank": 0,  # Will be set later
                "agent": agent_name,
                "total_tasks": agent.total_tasks,
                "passed": agent.passed_tasks,
                "pass_rate": round(agent.pass_rate * 100, 2),
                "avg_score": round(agent.avg_score, 4),
                "benchmarks": agent.benchmarks,
            })
        
        # Sort by pass_rate desc, then avg_score desc
        leaderboard.sort(key=lambda x: (-x["pass_rate"], -x["avg_score"]))
        
        # Add ranks
        for i, entry in enumerate(leaderboard, 1):
            entry["rank"] = i
        
        return leaderboard
    
    def get_task_results(self, agent_filter: Optional[str] = None) -> list:
        """Get all individual task results."""
        results = []
        for result in sorted(self.results, key=lambda x: (x.agent_name, x.task_id)):
            if agent_filter and agent_filter not in result.agent_name:
                continue
            
            results.append({
                "task_id": result.task_id,
                "agent": result.agent_name,
                "score": result.score,
                "passed": result.passed,
                "benchmark": result.benchmark,
                "description": result.description,
            })
        
        return results


def format_table(leaderboard: list) -> str:
    """Format leaderboard as ASCII table."""
    if not leaderboard:
        return "No results found."
    
    lines = []
    lines.append("\n🏆 BENCHMARK LEADERBOARD 🏆\n")
    lines.append(f"{'Rank':<6} {'Agent':<30} {'Tasks':<10} {'Pass Rate':<12} {'Avg Score':<12}")
    lines.append("-" * 70)
    
    for entry in leaderboard:
        lines.append(
            f"{entry['rank']:<6} {entry['agent']:<30} "
            f"{entry['passed']}/{entry['total_tasks']:<7} "
            f"{entry['pass_rate']:>5.1f}%        {entry['avg_score']:>6.4f}"
        )
    
    lines.append("")
    return "\n".join(lines)


def format_detailed(leaderboard: list) -> str:
    """Format detailed leaderboard with per-benchmark breakdown."""
    if not leaderboard:
        return "No results found."
    
    lines = []
    lines.append("\n📊 DETAILED BENCHMARK RESULTS 📊\n")
    
    for entry in leaderboard:
        lines.append(f"#{entry['rank']} {entry['agent']}")
        lines.append(f"  Overall: {entry['passed']}/{entry['total_tasks']} passed ({entry['pass_rate']:.1f}%) | Avg Score: {entry['avg_score']:.4f}")
        
        if entry['benchmarks']:
            lines.append("  By Benchmark:")
            for bench_name, bench_stats in sorted(entry['benchmarks'].items()):
                passed = bench_stats['passed']
                total = bench_stats['total']
                avg = bench_stats['avg_score']
                lines.append(f"    • {bench_name}: {passed}/{total} ({100*passed/total:.0f}%) | Avg: {avg:.4f}")
        lines.append("")
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Aggregate and display benchmark results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m scripts.leaderboard_cli results/runs
  python -m scripts.leaderboard_cli results/runs --format json --output leaderboard.json
  python -m scripts.leaderboard_cli results/runs --agent haiku
  python -m scripts.leaderboard_cli results/runs --format detailed
        """,
    )
    
    parser.add_argument(
        "results_dir",
        help="Path to results directory (e.g., results/runs)",
    )
    parser.add_argument(
        "--format",
        choices=["table", "detailed", "json", "tasks"],
        default="table",
        help="Output format (default: table)",
    )
    parser.add_argument(
        "--agent",
        help="Filter by agent name substring",
    )
    parser.add_argument(
        "--output",
        help="Save output to file (JSON formats only)",
    )
    
    args = parser.parse_args()
    
    # Check directory exists
    results_dir = Path(args.results_dir)
    if not results_dir.exists():
        print(f"❌ Results directory not found: {results_dir}", file=sys.stderr)
        return 1
    
    # Scan and aggregate
    aggregator = LeaderboardAggregator(results_dir)
    aggregator.scan_results()
    
    if not aggregator.results:
        if args.format not in ["json", "tasks"]:
            print("❌ No results found in directory.")
        return 1
    
    if args.format not in ["json", "tasks"]:
        print(f"📂 Scanning {results_dir}...", file=sys.stderr)
        print(f"✅ Found {len(aggregator.results)} task results", file=sys.stderr)
        print()
    
    # Generate output
    if args.format == "table":
        leaderboard = aggregator.get_leaderboard(args.agent)
        output = format_table(leaderboard)
        print(output)
        
    elif args.format == "detailed":
        leaderboard = aggregator.get_leaderboard(args.agent)
        output = format_detailed(leaderboard)
        print(output)
        
    elif args.format == "json":
        leaderboard = aggregator.get_leaderboard(args.agent)
        output = json.dumps(leaderboard, indent=2)
        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
            print(f"✅ Saved to {args.output}", file=sys.stderr)
        else:
            print(output)
            
    elif args.format == "tasks":
        tasks = aggregator.get_task_results(args.agent)
        output = json.dumps(tasks, indent=2)
        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
            print(f"✅ Saved to {args.output}", file=sys.stderr)
        else:
            print(output)
    
    return 0


if __name__ == "__main__":
    exit(main())
