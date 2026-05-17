import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'CDBench Leaderboard',
  description: 'CDBench: Controlled Multi-Fault Debugging with Reinforcement Learning and Iterative Repair',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className="bg-gradient-to-br from-gray-900 to-gray-800 text-white">
        {children}
      </body>
    </html>
  )
}
