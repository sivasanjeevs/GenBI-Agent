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
    <div className="min-h-screen transition-all duration-700 ease-in-out relative overflow-hidden">
      {/* Glow Orbs behind everything */}
      <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] rounded-full bg-dg-primary/20 blur-[120px] pointer-events-none" />
      <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] rounded-full bg-dg-accent/20 blur-[120px] pointer-events-none" />

      <div className={`mx-auto max-w-5xl px-4 relative z-10 ${isTopBar ? 'pt-8' : 'pt-[30vh]'}`}>
        
        {/* Header State Transition */}
        <div className={`flex flex-col transition-all duration-700 ease-in-out ${isTopBar ? 'mb-10 items-center' : 'items-center text-center mb-12'}`}>
          <div className={`transition-all duration-700 ${isTopBar ? 'flex items-center gap-4 mb-6 opacity-90 scale-90' : 'mb-10'}`}>
            <h1 className={`font-extrabold tracking-tight text-white ${isTopBar ? 'text-3xl' : 'text-6xl md:text-7xl mb-4'}`}>
              Rosetta <span className="text-gradient">AI</span>
            </h1>
            {!isTopBar && (
              <p className="text-gray-400 text-lg md:text-xl font-medium max-w-2xl mx-auto">
                Unlock insights from your Oracle Database at the speed of thought.
              </p>
            )}
          </div>
          
          <div className="w-full max-w-3xl">
            <SearchBox onSearch={handleSearch} loading={loading} />
          </div>
        </div>

        {/* Results Area */}
        {isTopBar && (
          <div className="space-y-8 pb-24 transition-opacity duration-700">
            {loading && (
              <div className="glass glass-glow rounded-3xl p-8 animate-pulse border border-white/10">
                <div className="flex space-x-6 items-center">
                  <div className="w-12 h-12 rounded-full bg-white/10 flex-shrink-0"></div>
                  <div className="flex-1 space-y-4 py-1">
                    <div className="h-4 bg-white/10 rounded w-3/4"></div>
                    <div className="space-y-2">
                      <div className="h-3 bg-white/5 rounded w-full"></div>
                      <div className="h-3 bg-white/5 rounded w-5/6"></div>
                    </div>
                  </div>
                </div>
              </div>
            )}
            
            {error && (
              <div className="glass rounded-3xl p-6 text-red-400 border border-red-500/30 shadow-[0_0_30px_rgba(239,68,68,0.15)] flex items-center gap-4">
                <svg className="w-6 h-6 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <span>Failed to load answer: {error}</span>
              </div>
            )}

            {!loading && !error && result && (
              <div className="space-y-8 animate-in fade-in slide-in-from-bottom-8 duration-700 fill-mode-both">
                <div className="glass glass-glow rounded-3xl overflow-hidden border border-white/10">
                  <AnswerCard data={result} />
                </div>
                
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div className="glass rounded-2xl border border-white/10 overflow-hidden hover:border-white/20 transition-colors">
                    <SqlAccordion sql={result.sql} explanation={result.explanation} />
                  </div>
                  <div className="glass rounded-2xl border border-white/10 overflow-hidden hover:border-white/20 transition-colors">
                    <TraceViewer trace={result.trace} />
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
