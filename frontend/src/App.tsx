import { useState } from 'react'
import SearchBox from './components/SearchBox'
import AnswerCard from './components/AnswerCard'
import TraceViewer from './components/TraceViewer'
import SqlAccordion from './components/SqlAccordion'
import ConversationPanel from './components/ConversationPanel'
import type { ConversationTurn } from './components/ConversationPanel'
import FollowUpChips from './components/FollowUpChips'
import EvalDashboard from './components/EvalDashboard'
import { BarChart3 } from 'lucide-react'

export default function App() {
  const [inputVal, setInputVal] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isTopBar, setIsTopBar] = useState(false)

  // Conversation turns — full list for left panel
  const [turns, setTurns] = useState<ConversationTurn[]>([])
  // Currently displayed turn (may be an older one the user clicked)
  const [activeTurn, setActiveTurn] = useState<ConversationTurn | null>(null)
  // conversation_id for CP5 follow-up chaining
  const [conversationId, setConversationId] = useState<string | null>(null)

  // Eval dashboard visibility
  const [showEval, setShowEval] = useState(false)

  const handleNewConversation = () => {
    setConversationId(null)
    setTurns([])
    setActiveTurn(null)
    setError(null)
    setInputVal('')
    setIsTopBar(false)
  }

  const handleSearch = async (q: string) => {
    if (!q.trim()) return

    setLoading(true)
    setError(null)
    setIsTopBar(true)
    // Clear active turn while loading
    setActiveTurn(null)

    try {
      const body: Record<string, any> = { question: q }
      if (conversationId) body.conversation_id = conversationId

      const res = await fetch('http://localhost:8000/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`)
      const data = await res.json()

      // Build a turn object from the full response
      const newTurn: ConversationTurn = {
        question_id: data.question_id,
        question: q,
        answer_text: data.answer_text,
        sql: data.sql,
        row_count: data.row_count,
        elapsed_ms: data.elapsed_ms,
        date_interpretation: data.date_interpretation,
        explanation: data.explanation,
        trace: data.trace,
        chart: data.chart,
        follow_up_suggestions: data.follow_up_suggestions || [],
        columns: data.columns,
        data: data.data,
        timestamp: new Date().toISOString(),
      }

      setTurns(prev => [...prev, newTurn])
      setActiveTurn(newTurn)
      setConversationId(data.question_id)
      setInputVal('')
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  // When user clicks a turn in the left panel, display it
  const handleSelectTurn = (turn: ConversationTurn) => {
    setActiveTurn(turn)
  }

  // Follow-up chip click: run the suggested question
  const handleFollowUp = (suggestion: string) => {
    setInputVal(suggestion)
    handleSearch(suggestion)
  }

  const hasTurns = turns.length > 0

  return (
    <div className="min-h-screen relative overflow-hidden flex">
      {/* Ambient glow orbs */}
      <div className="fixed top-[-15%] left-[-10%] w-[45%] h-[45%] rounded-full bg-dg-primary/15 blur-[140px] pointer-events-none z-0" />
      <div className="fixed bottom-[-15%] right-[-10%] w-[45%] h-[45%] rounded-full bg-dg-accent/15 blur-[140px] pointer-events-none z-0" />

      {/* ── Left conversation panel ──────────────────────────────────────────── */}
      {hasTurns && (
        <aside
          className="fixed left-0 top-0 h-full z-20 w-64 flex-shrink-0
            glass border-r border-white/8 shadow-[4px_0_30px_rgba(0,0,0,0.3)]
            animate-in slide-in-from-left-4 duration-400"
        >
          <ConversationPanel
            turns={turns}
            activeId={activeTurn?.question_id ?? null}
            onSelect={handleSelectTurn}
            onNewConversation={handleNewConversation}
          />
        </aside>
      )}

      {/* ── Main content area ────────────────────────────────────────────────── */}
      <div
        className={`flex-1 relative z-10 transition-all duration-500 ${
          hasTurns ? 'ml-64' : 'ml-0'
        }`}
      >
        {/* ── Eval button — top right corner ───────────────────────────────── */}
        <div className="fixed top-4 right-5 z-30">
          <button
            id="btn-eval-dashboard"
            onClick={() => setShowEval(true)}
            className="flex items-center gap-2 px-4 py-2 rounded-xl glass border border-white/12
              text-gray-400 text-xs font-semibold uppercase tracking-wider
              hover:bg-dg-primary/15 hover:border-dg-primary/30 hover:text-purple-300
              hover:shadow-[0_0_20px_rgba(139,92,246,0.2)]
              transition-all duration-300"
          >
            <BarChart3 className="w-4 h-4" />
            Evaluation
          </button>
        </div>

        <div
          className={`mx-auto max-w-4xl px-6 relative transition-all duration-700 ease-in-out ${
            isTopBar ? 'pt-10' : 'pt-[28vh]'
          }`}
        >
          {/* ── Header ─────────────────────────────────────────────────────── */}
          <div
            className={`flex flex-col transition-all duration-700 ease-in-out ${
              isTopBar ? 'mb-8 items-center' : 'items-center text-center mb-10'
            }`}
          >
            <div className={`transition-all duration-700 ${isTopBar ? 'mb-5 opacity-90' : 'mb-8'}`}>
              <h1
                className={`font-bold tracking-tight text-white transition-all duration-700 ${
                  isTopBar ? 'text-2xl' : 'text-5xl md:text-6xl mb-3'
                }`}
              >
                Rosetta <span className="text-gradient">GenBI Agent</span>
              </h1>
              {!isTopBar && (
                <p className="text-gray-500 text-base md:text-lg max-w-xl mx-auto leading-relaxed">
                  Unlock insights from your Oracle Database in plain English.
                </p>
              )}
            </div>

            {/* Search box */}
            <div className="w-full max-w-3xl">
              <SearchBox
                onSearch={handleSearch}
                loading={loading}
                value={inputVal}
                onChange={setInputVal}
              />
            </div>
          </div>

          {/* ── Results area ────────────────────────────────────────────────── */}
          {isTopBar && (
            <div className="space-y-5 pb-24">

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

              {/* Answer result (active turn) */}
              {!loading && !error && activeTurn && (
                <div className="space-y-5 animate-in fade-in slide-in-from-bottom-6 duration-500 fill-mode-both">

                  {/* Answer card */}
                  <div className="glass glass-glow rounded-2xl overflow-hidden border border-white/10">
                    <AnswerCard data={{
                      answer_text: activeTurn.answer_text,
                      chart: activeTurn.chart,
                      date_interpretation: activeTurn.date_interpretation,
                    }} />

                    {/* Follow-up chips — inside the answer card */}
                    {activeTurn.follow_up_suggestions && activeTurn.follow_up_suggestions.length > 0 && (
                      <div className="px-7 pb-6">
                        <FollowUpChips
                          suggestions={activeTurn.follow_up_suggestions}
                          onSelect={handleFollowUp}
                          loading={loading}
                        />
                      </div>
                    )}
                  </div>

                  {/* Evidence + Trace — 3:2 split */}
                  <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
                    <div className="md:col-span-3 glass rounded-2xl border border-white/8 overflow-hidden hover:border-white/15 transition-colors duration-300">
                      <SqlAccordion sql={activeTurn.sql} explanation={activeTurn.explanation} />
                    </div>
                    <div className="md:col-span-2 glass rounded-2xl border border-white/8 overflow-hidden hover:border-white/15 transition-colors duration-300">
                      <TraceViewer trace={activeTurn.trace} />
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── Eval Dashboard modal ─────────────────────────────────────────────── */}
      {showEval && <EvalDashboard onClose={() => setShowEval(false)} />}
    </div>
  )
}
