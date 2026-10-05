import { useState } from 'react'
import SearchBox from './components/SearchBox'
import AnswerCard from './components/AnswerCard'
import TraceViewer from './components/TraceViewer'
import SqlAccordion from './components/SqlAccordion'

export default function App() {
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [isTopBar, setIsTopBar] = useState(false)

  const handleSearch = async (q: string) => {
    if (!q.trim()) return
    setQuery(q)
    setLoading(true)
    setError(null)
    setIsTopBar(true)
    setResult(null)

    try {
      const res = await fetch('http://localhost:8000/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q })
      })
      if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`)
      const data = await res.json()
      setResult(data)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen transition-all duration-700 ease-in-out">
      <div className={`mx-auto max-w-4xl px-4 ${isTopBar ? 'pt-10' : 'pt-[35vh]'}`}>
        
        {/* Header State Transition */}
        <div className={`flex flex-col transition-all duration-500 ${isTopBar ? 'mb-8' : 'items-center text-center mb-10'}`}>
          <h1 className={`font-semibold tracking-tight text-blue-900 transition-all duration-500 ${isTopBar ? 'text-2xl mb-5 opacity-90' : 'text-5xl mb-8'}`}>
            Rosetta
          </h1>
          <div className="w-full">
            <SearchBox onSearch={handleSearch} loading={loading} />
          </div>
        </div>

        {/* Results Area */}
        {isTopBar && (
          <div className="space-y-6 pb-24 transition-opacity duration-500">
            {loading && (
              <div className="rounded-2xl bg-white p-8 shadow-sm">
                <div className="animate-pulse flex space-x-4">
                  <div className="flex-1 space-y-4 py-1">
                    <div className="h-4 bg-slate-200 rounded w-3/4"></div>
                    <div className="space-y-2">
                      <div className="h-4 bg-slate-200 rounded"></div>
                      <div className="h-4 bg-slate-200 rounded w-5/6"></div>
                    </div>
                  </div>
                </div>
              </div>
            )}
            
            {error && (
              <div className="rounded-2xl bg-red-50 p-6 text-red-800 border border-red-100 shadow-sm">
                Failed to load answer: {error}
              </div>
            )}

            {!loading && !error && result && (
              <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-700">
                <AnswerCard data={result} />
                <TraceViewer trace={result.trace} />
                <SqlAccordion sql={result.sql} explanation={result.explanation} />
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
