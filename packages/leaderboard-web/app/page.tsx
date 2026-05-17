'use client'

import { useEffect, useState } from 'react'
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Cell,
} from 'recharts'

interface BenchmarkStats {
  total: number
  passed: number
  avg_score: number
}

interface LeaderboardEntry {
  rank: number
  agent: string
  total_tasks: number
  passed: number
  pass_rate: number
  avg_score: number
  benchmarks: Record<string, BenchmarkStats>
}

export default function Home() {
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null)

  useEffect(() => {
    fetchLeaderboard()
  }, [])

  const fetchLeaderboard = async () => {
    try {
      setLoading(true)
      // Try to fetch from the API endpoint
      const res = await fetch('/api/leaderboard')
      if (!res.ok) throw new Error(`API error: ${res.status}`)
      const data = await res.json()
      setLeaderboard(data)
      setError(null)
    } catch (err) {
      // Fallback: load mock data for demo
      console.error('Failed to fetch leaderboard:', err)
      setLeaderboard(generateMockData())
      setError('Using sample data (API not available)')
    } finally {
      setLoading(false)
    }
  }

  const selectedAgentData = selectedAgent
    ? leaderboard.find((e) => e.agent === selectedAgent)
    : null

  return (
    <div className="min-h-screen p-8">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="text-center mb-12">
          <h1 className="text-5xl font-bold mb-3 bg-gradient-to-r from-cyan-400 to-blue-500 bg-clip-text text-transparent">
            🐛 CDBench Leaderboard
          </h1>
          <p className="text-gray-400 text-lg">
            Controlled Multi-Fault Debugging with Reinforcement Learning and Iterative Repair
          </p>
          <p className="text-gray-500 text-sm mt-2">
            LLM Agent Performance on Debugging and Code Repair Tasks
          </p>
          {error && (
            <p className="text-yellow-400 text-sm mt-2">ℹ️ {error}</p>
          )}
        </div>

        {loading ? (
          <div className="text-center py-12">
            <p className="text-gray-400">Loading leaderboard...</p>
          </div>
        ) : leaderboard.length === 0 ? (
          <div className="text-center py-12">
            <p className="text-gray-400">No benchmark results found</p>
          </div>
        ) : (
          <>
            {/* Summary Stats */}
            <div className="grid grid-cols-3 gap-4 mb-8">
              <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
                <p className="text-gray-400 text-sm mb-2">Total Agents</p>
                <p className="text-3xl font-bold text-cyan-400">{leaderboard.length}</p>
              </div>
              <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
                <p className="text-gray-400 text-sm mb-2">Total Tasks</p>
                <p className="text-3xl font-bold text-blue-400">
                  {leaderboard[0]?.total_tasks || 0}
                </p>
              </div>
              <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
                <p className="text-gray-400 text-sm mb-2">Avg Pass Rate</p>
                <p className="text-3xl font-bold text-emerald-400">
                  {(leaderboard.reduce((sum, e) => sum + e.pass_rate, 0) / leaderboard.length).toFixed(1)}%
                </p>
              </div>
            </div>

            {/* Leaderboard Table */}
            <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden mb-8">
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-gray-700 border-b border-gray-600">
                    <tr>
                      <th className="px-6 py-3 text-left text-sm font-semibold text-gray-300">Rank</th>
                      <th className="px-6 py-3 text-left text-sm font-semibold text-gray-300 cursor-pointer hover:text-cyan-400">
                        Agent
                      </th>
                      <th className="px-6 py-3 text-left text-sm font-semibold text-gray-300">Tasks</th>
                      <th className="px-6 py-3 text-left text-sm font-semibold text-gray-300">Pass Rate</th>
                      <th className="px-6 py-3 text-left text-sm font-semibold text-gray-300">Avg Score</th>
                      <th className="px-6 py-3 text-left text-sm font-semibold text-gray-300">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {leaderboard.map((entry) => (
                      <tr
                        key={entry.agent}
                        className="border-b border-gray-700 hover:bg-gray-750 transition cursor-pointer"
                        onClick={() => setSelectedAgent(entry.agent)}
                      >
                        <td className="px-6 py-4">
                          <span className="text-lg font-bold">
                            {entry.rank === 1 ? '🥇' : entry.rank === 2 ? '🥈' : entry.rank === 3 ? '🥉' : entry.rank}
                          </span>
                        </td>
                        <td className="px-6 py-4 font-semibold text-cyan-400">{entry.agent}</td>
                        <td className="px-6 py-4 text-gray-300">
                          {entry.passed}/{entry.total_tasks}
                        </td>
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-2">
                            <div className="w-20 bg-gray-700 rounded-full h-2">
                              <div
                                className="bg-gradient-to-r from-cyan-400 to-blue-500 h-2 rounded-full"
                                style={{ width: `${entry.pass_rate}%` }}
                              ></div>
                            </div>
                            <span className="text-sm font-semibold">{entry.pass_rate.toFixed(1)}%</span>
                          </div>
                        </td>
                        <td className="px-6 py-4 text-blue-400 font-semibold">
                          {entry.avg_score.toFixed(4)}
                        </td>
                        <td className="px-6 py-4">
                          <button
                            onClick={(e) => {
                              e.stopPropagation()
                              setSelectedAgent(selectedAgent === entry.agent ? null : entry.agent)
                            }}
                            className="px-3 py-1 bg-blue-600 hover:bg-blue-700 rounded text-xs font-semibold"
                          >
                            {selectedAgent === entry.agent ? 'Hide' : 'Details'}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Pass Rate Chart */}
            <div className="grid grid-cols-2 gap-8 mb-8">
              <div className="bg-gray-800 rounded-lg border border-gray-700 p-6">
                <h2 className="text-lg font-bold mb-4 text-cyan-400">Pass Rates by Agent</h2>
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart data={leaderboard}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#444" />
                    <XAxis dataKey="agent" stroke="#999" angle={-45} textAnchor="end" height={80} />
                    <YAxis stroke="#999" />
                    <Tooltip contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #444' }} />
                    <Bar dataKey="pass_rate" fill="#06b6d4" radius={[8, 8, 0, 0]}>
                      {leaderboard.map((entry) => (
                        <Cell
                          key={`cell-${entry.agent}`}
                          fill={entry.rank === 1 ? '#fbbf24' : '#06b6d4'}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>

              <div className="bg-gray-800 rounded-lg border border-gray-700 p-6">
                <h2 className="text-lg font-bold mb-4 text-blue-400">Average Scores</h2>
                <ResponsiveContainer width="100%" height={300}>
                  <LineChart data={leaderboard}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#444" />
                    <XAxis dataKey="agent" stroke="#999" angle={-45} textAnchor="end" height={80} />
                    <YAxis stroke="#999" domain={[0, 1]} />
                    <Tooltip contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #444' }} />
                    <Line
                      type="monotone"
                      dataKey="avg_score"
                      stroke="#3b82f6"
                      dot={{ fill: '#3b82f6', r: 5 }}
                      connectNulls
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Detail View */}
            {selectedAgentData && (
              <div className="bg-gray-800 rounded-lg border border-gray-700 p-6">
                <h2 className="text-2xl font-bold mb-6 text-cyan-400">{selectedAgentData.agent} - Detailed View</h2>

                {Object.keys(selectedAgentData.benchmarks).length > 0 && (
                  <>
                    <h3 className="text-lg font-semibold mb-4 text-gray-300">Performance by Benchmark</h3>
                    <div className="grid grid-cols-2 gap-4 mb-6">
                      {Object.entries(selectedAgentData.benchmarks).map(([name, stats]) => (
                        <div key={name} className="bg-gray-750 rounded p-4 border border-gray-600">
                          <h4 className="font-semibold text-blue-400 mb-2">{name}</h4>
                          <div className="text-sm text-gray-400 space-y-1">
                            <p>
                              Passed: <span className="text-emerald-400 font-semibold">{stats.passed}/{stats.total}</span>
                            </p>
                            <p>
                              Avg Score: <span className="text-cyan-400 font-semibold">{stats.avg_score.toFixed(4)}</span>
                            </p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </>
                )}

                <button
                  onClick={() => setSelectedAgent(null)}
                  className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm font-semibold"
                >
                  Close Details
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function generateMockData(): LeaderboardEntry[] {
  return [
    {
      rank: 1,
      agent: 'claude-opus',
      total_tasks: 35,
      passed: 32,
      pass_rate: 91.4,
      avg_score: 0.918,
      benchmarks: {
        pandas: { total: 20, passed: 19, avg_score: 0.94 },
        scikit_learn: { total: 15, passed: 13, avg_score: 0.88 },
      },
    },
    {
      rank: 2,
      agent: 'gpt-4',
      total_tasks: 35,
      passed: 28,
      pass_rate: 80.0,
      avg_score: 0.805,
      benchmarks: {
        pandas: { total: 20, passed: 17, avg_score: 0.82 },
        scikit_learn: { total: 15, passed: 11, avg_score: 0.78 },
      },
    },
    {
      rank: 3,
      agent: 'claude-haiku',
      total_tasks: 35,
      passed: 22,
      pass_rate: 62.9,
      avg_score: 0.645,
      benchmarks: {
        pandas: { total: 20, passed: 14, avg_score: 0.68 },
        scikit_learn: { total: 15, passed: 8, avg_score: 0.60 },
      },
    },
    {
      rank: 4,
      agent: 'gemini-pro',
      total_tasks: 35,
      passed: 19,
      pass_rate: 54.3,
      avg_score: 0.521,
      benchmarks: {
        pandas: { total: 20, passed: 12, avg_score: 0.55 },
        scikit_learn: { total: 15, passed: 7, avg_score: 0.48 },
      },
    },
  ]
}
