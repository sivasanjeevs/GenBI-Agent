import { useState } from 'react'
import SearchBox from './components/SearchBox'
import AnswerCard from './components/AnswerCard'
import TraceViewer from './components/TraceViewer'
import SqlAccordion from './components/SqlAccordion'
import { MessageSquare, X } from 'lucide-react'

export default function App() {

  const [inputVal, setInputVal] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [isTopBar, setIsTopBar] = useState(false)
  // CP5: track conversation_id for multi-turn follow-ups
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [turnCount, setTurnCount] = useState(0)

  const handleNewConversation = () => {
    setConversationId(null)
    setTurnCount(0)
    setResult(null)
    setError(null)

    setInputVal('')
    setIsTopBar(false)
  }

  const handleSearch = async (q: string) => {
    if (!q.trim()) return

    setLoading(true)
    setError(null)
    setIsTopBar(true)
    setResult(null)

    try {
      const body: Record<string, any> = { question: q }
      // CP5: attach conversation_id so backend injects prior turn context
      if (conversationId) {
        body.conversation_id = conversationId
      }

      const res = await fetch('http://localhost:8000/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`)
      const data = await res.json()
      setResult(data)
      // Store this question's ID as the conversation_id for the next question
      if (data.question_id) {
        setConversationId(data.question_id)
        setTurnCount(prev => prev + 1)
      }
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen relative overflow-hidden">
      {/* Ambient glow orbs */}
      <div className="fixed top-[-15%] left-[-10%] w-[45%] h-[45%] rounded-full bg-dg-primary/15 blur-[140px] pointer-events-none" />
      <div className="fixed bottom-[-15%] right-[-10%] w-[45%] h-[45%] rounded-full bg-dg-accent/15 blur-[140px] pointer-events-none" />

      <div className={`mx-auto max-w-5xl px-6 relative z-10 transition-all duration-700 ease-in-out ${isTopBar ? 'pt-10' : 'pt-[28vh]'}`}>

        {/* Header */}
        <div className={`flex flex-col transition-all duration-700 ease-in-out ${isTopBar ? 'mb-8 items-center' : 'items-center text-center mb-10'}`}>
          <div className={`transition-all duration-700 ${isTopBar ? 'mb-5 opacity-90' : 'mb-8'}`}>
            <h1 className={`font-bold tracking-tight text-white transition-all duration-700 ${isTopBar ? 'text-2xl' : 'text-5xl md:text-6xl mb-3'}`}>
              Rosetta <span className="text-gradient"> GenBI Agent</span>
            </h1>
            {!isTopBar && (
              <p className="text-gray-500 text-base md:text-lg max-w-xl mx-auto leading-relaxed">
                Unlock insights from your Oracle Database in plain English.
              </p>
            )}
          </div>

          {/* Search box — full width */}
          <div className="w-full max-w-3xl">
            <SearchBox
              onSearch={handleSearch}
              loading={loading}
              value={inputVal}
              onChange={setInputVal}
            />
          </div>

          {/* CP5: Conversation context badge + reset button */}
          {conversationId && turnCount > 0 && (
            <div className="flex items-center gap-2 mt-3">
              <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-dg-primary/30 bg-dg-primary/10 text-blue-300 text-xs font-medium">
                <MessageSquare className="w-3.5 h-3.5" />
                Follow-up mode &middot; {turnCount} turn{turnCount !== 1 ? 's' : ''}
              </div>
              <button
                onClick={handleNewConversation}
                id="btn-new-conversation"
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-white/10 bg-white/5 text-gray-400 text-xs font-medium hover:bg-white/10 hover:text-gray-200 transition-all duration-200"
                title="Start a new conversation (clears context)"
              >
                <X className="w-3 h-3" />
                New conversation
              </button>
            </div>
          )}
        </div>

        {/* Results */}
        {isTopBar && (
          <div className="space-y-5 pb-20">
            {/* Loading skeleton */}
            {loading && (
              <div className="glass rounded-2xl p-6 animate-pulse border border-white/8">
                <div className="flex gap-5 items-start">
                  <div className="w-10 h-10 rounded-full bg-white/8 flex-shrink-0 mt-1" />
                  <div className="flex-1 space-y-3">
                    <div className="h-3.5 bg-white/8 rounded w-3/4" />
                    <div className="h-3 bg-white/5 rounded w-full" />
                    <div className="h-3 bg-white/5 rounded w-5/6" />
                  </div>
                </div>
              </div>
            )}

            {/* Error */}
            {error && (
              <div className="glass rounded-2xl p-5 text-red-400 border border-red-500/25 shadow-[0_0_24px_rgba(239,68,68,0.1)] flex items-center gap-3 text-sm">
                <svg className="w-5 h-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <span>Failed to load answer: {error}</span>
              </div>
            )}

            {/* Answer result */}
            {!loading && !error && result && (
              <div className="space-y-5 animate-in fade-in slide-in-from-bottom-6 duration-500 fill-mode-both">

                {/* Answer card — full width */}
                <div className="glass glass-glow rounded-2xl overflow-hidden border border-white/10">
                  <AnswerCard data={result} />
                </div>

                {/* Evidence + Trace — 3:2 split */}
                <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
                  {/* Evidence & Query — wider (3/5) */}
                  <div className="md:col-span-3 glass rounded-2xl border border-white/8 overflow-hidden hover:border-white/15 transition-colors duration-300">
                    <SqlAccordion sql={result.sql} explanation={result.explanation} />
                  </div>
                  {/* Agent Trace — narrower (2/5) */}
                  <div className="md:col-span-2 glass rounded-2xl border border-white/8 overflow-hidden hover:border-white/15 transition-colors duration-300">
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
