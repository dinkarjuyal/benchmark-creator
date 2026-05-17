import { NextRequest, NextResponse } from 'next/server'
import { execSync } from 'child_process'
import path from 'path'

export async function GET(request: NextRequest) {
  try {
    const resultsDir = process.env.RESULTS_DIR || path.join(process.cwd(), '../../results/runs')
    const projectRoot = path.join(process.cwd(), '../..')
    
    // Call the leaderboard CLI and capture JSON output
    const command = `cd "${projectRoot}" && python3 -m scripts.leaderboard_cli "${resultsDir}" --format json`
    
    try {
      const output = execSync(command, { encoding: 'utf-8' })
      const leaderboard = JSON.parse(output)
      return NextResponse.json(leaderboard)
    } catch (execError) {
      console.error('Failed to run leaderboard CLI:', execError)
      // Return empty array - frontend will use mock data
      return NextResponse.json([])
    }
  } catch (error) {
    console.error('API error:', error)
    return NextResponse.json({ error: 'Failed to fetch leaderboard' }, { status: 500 })
  }
}
