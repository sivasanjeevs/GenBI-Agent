import { useState, useEffect } from 'react';
import {
  X,
  RefreshCw,
  CheckCircle2,
  XCircle,
  Minus,
  Loader2,
  Zap,
  BarChart3,
  Clock,
  RotateCcw,
  Play,
} from 'lucide-react';

interface EvalRun {
  sql: string;
  rows: any[];
  row_count: number;
  elapsed_ms: number;
  total_latency_ms: number;
  attempts: number;
  repaired: boolean;
  abstained: boolean;
  error?: string | null;
  model: string;
}

interface EvalQuestion {
  question_id: string;
  question: string;
  difficulty: string;
  runs: EvalRun[];
  is_consistent: boolean;
  is_correct: boolean | null;
  avg_latency_ms: number;
  avg_retries: number;
  success_rate: number;
}

interface EvalResults {
  timestamp: string;
  model: string;
  total_questions: number;
  answerable: number;
  correct: number;
  consistent: number;
  accuracy: number;
  consistency_rate: number;
  answerability_rate: number;
  avg_retries: number;
  p50_latency_ms: number;
  p95_latency_ms: number;
  results: EvalQuestion[];
}

interface EvalDashboardProps {
  onClose: () => void;
}

const DIFFICULTY_COLOR: Record<string, string> = {
  Easy: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20',
  Medium: 'text-amber-400 bg-amber-400/10 border-amber-400/20',
  Hard: 'text-red-400 bg-red-400/10 border-red-400/20',
  unknown: 'text-gray-400 bg-gray-400/10 border-gray-400/20',
};

function GaugeRing({ value, color, label }: { value: number; color: string; label: string }) {
  const pct = Math.min(1, Math.max(0, value));
  const r = 38;
  const circ = 2 * Math.PI * r;
  const dash = pct * circ;

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative w-24 h-24">
        <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
          <circle cx="50" cy="50" r={r} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="10" />
          <circle
            cx="50"
            cy="50"
            r={r}
            fill="none"
            stroke={color}
            strokeWidth="10"
            strokeDasharray={`${dash} ${circ}`}
            strokeLinecap="round"
            style={{ transition: 'stroke-dasharray 0.8s ease-out', filter: `drop-shadow(0 0 6px ${color}88)` }}
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-lg font-bold text-white">{Math.round(pct * 100)}%</span>
        </div>
      </div>
      <span className="text-xs text-gray-500 font-medium text-center">{label}</span>
    </div>
  );
}

export default function EvalDashboard({ onClose }: EvalDashboardProps) {
  const [results, setResults] = useState<EvalResults | null>(null);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedQ, setExpandedQ] = useState<string | null>(null);

  const fetchResults = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('http://localhost:8000/eval/results');
      if (!res.ok) {
        if (res.status === 404) {
          setError('No evaluation results yet. Click "Run Evaluation" to start.');
        } else {
          setError(`Failed to load results (HTTP ${res.status})`);
        }
        setResults(null);
      } else {
        const data = await res.json();
        setResults(data);
      }
    } catch (e: any) {
      setError('Could not connect to backend. Is the server running?');
    } finally {
      setLoading(false);
    }
  };

  const triggerEval = async () => {
    setTriggering(true);
    try {
      await fetch('http://localhost:8000/eval/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) });
      // Poll after a short delay
      setTimeout(() => {
        setTriggering(false);
        fetchResults();
      }, 3000);
    } catch {
      setTriggering(false);
    }
  };

  useEffect(() => {
    fetchResults();
  }, []);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="relative w-full max-w-5xl max-h-[90vh] flex flex-col glass rounded-2xl border border-white/12 shadow-[0_0_80px_rgba(139,92,246,0.2)] overflow-hidden animate-in fade-in slide-in-from-bottom-4 duration-300">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/8 flex-shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-xl bg-dg-primary/20 border border-dg-primary/30 flex items-center justify-center">
              <BarChart3 className="w-4 h-4 text-dg-primary" />
            </div>
            <div>
              <h2 className="text-base font-bold text-white">Evaluation Dashboard</h2>
              {results && (
                <p className="text-xs text-gray-500 mt-0.5">
                  Model: <span className="text-gray-400">{results.model}</span>
                  &nbsp;·&nbsp;
                  {new Date(results.timestamp).toLocaleString()}
                </p>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={fetchResults}
              disabled={loading}
              className="p-2 rounded-xl border border-white/10 bg-white/4 text-gray-400 hover:bg-white/8 hover:text-white transition-all duration-200 disabled:opacity-40"
              title="Refresh"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
            <button
              onClick={triggerEval}
              disabled={triggering}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-dg-primary/20 border border-dg-primary/40 text-purple-300 text-sm font-semibold hover:bg-dg-primary/30 transition-all duration-200 disabled:opacity-50"
            >
              {triggering ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
              {triggering ? 'Running…' : 'Run Evaluation'}
            </button>
            <button
              onClick={onClose}
              className="p-2 rounded-xl border border-white/10 bg-white/4 text-gray-400 hover:bg-white/8 hover:text-white transition-all duration-200"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto">
          {loading && (
            <div className="flex items-center justify-center py-20 gap-3 text-gray-500">
              <Loader2 className="w-5 h-5 animate-spin text-dg-primary" />
              <span className="text-sm">Loading results…</span>
            </div>
          )}

          {error && !loading && (
            <div className="flex flex-col items-center justify-center py-16 gap-4 text-center px-8">
              <div className="w-12 h-12 rounded-2xl bg-red-500/10 border border-red-500/20 flex items-center justify-center">
                <BarChart3 className="w-6 h-6 text-red-400" />
              </div>
              <p className="text-gray-400 text-sm max-w-sm">{error}</p>
              <button
                onClick={triggerEval}
                disabled={triggering}
                className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-dg-primary text-white text-sm font-semibold hover:bg-dg-primary/80 transition-all disabled:opacity-50"
              >
                {triggering ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                Start Evaluation
              </button>
            </div>
          )}

          {results && !loading && (
            <div className="p-6 space-y-6">

              {/* Metrics Row */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {/* Gauges */}
                <div className="col-span-2 md:col-span-2 glass rounded-xl p-5 border border-white/8">
                  <h3 className="text-[10px] font-bold uppercase tracking-[0.15em] text-gray-500 mb-4">Quality Metrics</h3>
                  <div className="flex items-center justify-around">
                    <GaugeRing value={results.accuracy} color="#8b5cf6" label="Accuracy" />
                    <GaugeRing value={results.consistency_rate} color="#3b82f6" label="Consistency" />
                    <GaugeRing value={results.answerability_rate} color="#10b981" label="Answerability" />
                  </div>
                </div>

                {/* Speed */}
                <div className="glass rounded-xl p-5 border border-white/8 flex flex-col justify-between">
                  <div className="flex items-center gap-2 mb-3">
                    <Clock className="w-4 h-4 text-amber-400" />
                    <span className="text-[10px] font-bold uppercase tracking-[0.15em] text-gray-500">Speed</span>
                  </div>
                  <div className="space-y-2">
                    <div>
                      <p className="text-xs text-gray-600">p50 Latency</p>
                      <p className="text-xl font-bold text-white">{(results.p50_latency_ms / 1000).toFixed(1)}<span className="text-sm text-gray-500 font-normal">s</span></p>
                    </div>
                    <div>
                      <p className="text-xs text-gray-600">p95 Latency</p>
                      <p className="text-lg font-semibold text-amber-400">{(results.p95_latency_ms / 1000).toFixed(1)}<span className="text-sm text-gray-500 font-normal">s</span></p>
                    </div>
                  </div>
                </div>

                {/* Resilience */}
                <div className="glass rounded-xl p-5 border border-white/8 flex flex-col justify-between">
                  <div className="flex items-center gap-2 mb-3">
                    <Zap className="w-4 h-4 text-dg-primary" />
                    <span className="text-[10px] font-bold uppercase tracking-[0.15em] text-gray-500">Resilience</span>
                  </div>
                  <div className="space-y-2">
                    <div>
                      <p className="text-xs text-gray-600">Avg Retries / Q</p>
                      <p className="text-xl font-bold text-white">{results.avg_retries.toFixed(2)}</p>
                    </div>
                    <div>
                      <p className="text-xs text-gray-600">Correct / Total</p>
                      <p className="text-lg font-semibold text-dg-primary">{results.correct}<span className="text-sm text-gray-500 font-normal"> / {results.total_questions}</span></p>
                    </div>
                  </div>
                </div>
              </div>

              {/* Question Breakdown */}
              <div>
                <h3 className="text-[10px] font-bold uppercase tracking-[0.15em] text-gray-500 mb-3">Question Breakdown</h3>
                <div className="space-y-2">
                  {results.results.map((q) => {
                    const isExpanded = expandedQ === q.question_id;
                    const diffClass = DIFFICULTY_COLOR[q.difficulty] || DIFFICULTY_COLOR.unknown;

                    return (
                      <div
                        key={q.question_id}
                        className="glass rounded-xl border border-white/8 hover:border-white/15 transition-colors overflow-hidden"
                      >
                        <button
                          onClick={() => setExpandedQ(isExpanded ? null : q.question_id)}
                          className="w-full px-4 py-3 flex items-center gap-3 text-left hover:bg-white/2 transition-colors"
                        >
                          {/* Correct / incorrect indicator */}
                          {q.is_correct === true ? (
                            <CheckCircle2 className="w-4 h-4 flex-shrink-0 text-emerald-400 drop-shadow-[0_0_6px_rgba(52,211,153,0.5)]" />
                          ) : q.is_correct === false ? (
                            <XCircle className="w-4 h-4 flex-shrink-0 text-red-400 drop-shadow-[0_0_6px_rgba(248,113,113,0.5)]" />
                          ) : (
                            <Minus className="w-4 h-4 flex-shrink-0 text-gray-500" />
                          )}

                          {/* Question text */}
                          <span className="flex-1 text-sm text-gray-300 font-medium text-left truncate">
                            {q.question}
                          </span>

                          {/* Badges */}
                          <div className="flex items-center gap-2 flex-shrink-0">
                            <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${diffClass}`}>
                              {q.difficulty}
                            </span>
                            {q.is_consistent ? (
                              <span className="text-[10px] font-medium px-2 py-0.5 rounded-full border text-emerald-400 bg-emerald-400/10 border-emerald-400/20">
                                Consistent
                              </span>
                            ) : (
                              <span className="text-[10px] font-medium px-2 py-0.5 rounded-full border text-amber-400 bg-amber-400/10 border-amber-400/20">
                                Inconsistent
                              </span>
                            )}
                            <span className="flex items-center gap-1 text-[10px] text-gray-600">
                              <Clock className="w-3 h-3" />
                              {(q.avg_latency_ms / 1000).toFixed(1)}s
                            </span>
                            {q.avg_retries > 0 && (
                              <span className="flex items-center gap-1 text-[10px] text-amber-500">
                                <RotateCcw className="w-3 h-3" />
                                {q.avg_retries.toFixed(1)}
                              </span>
                            )}
                          </div>
                        </button>

                        {/* Expanded: per-run details */}
                        {isExpanded && (
                          <div className="border-t border-white/8 px-4 py-3 bg-black/20">
                            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                              {q.runs.map((run, ri) => (
                                <div
                                  key={ri}
                                  className="rounded-lg bg-white/3 border border-white/8 p-3"
                                >
                                  <div className="flex items-center justify-between mb-2">
                                    <span className="text-[10px] font-bold uppercase tracking-wider text-gray-500">
                                      Run {ri + 1}
                                    </span>
                                    {run.abstained ? (
                                      <span className="text-[10px] text-red-400">Abstained</span>
                                    ) : run.repaired ? (
                                      <span className="text-[10px] text-amber-400">Repaired</span>
                                    ) : (
                                      <span className="text-[10px] text-emerald-400">OK</span>
                                    )}
                                  </div>
                                  <p className="text-xs text-gray-400">
                                    Rows: <span className="text-white font-semibold">{run.row_count}</span>
                                  </p>
                                  <p className="text-xs text-gray-400">
                                    Time: <span className="text-white font-semibold">{(run.total_latency_ms / 1000).toFixed(2)}s</span>
                                  </p>
                                  <p className="text-xs text-gray-400">
                                    Attempts: <span className="text-white font-semibold">{run.attempts}</span>
                                  </p>
                                  <p className="text-xs text-gray-400">
                                    Model: <span className="text-gray-300 font-mono text-[10px]">{run.model}</span>
                                  </p>
                                  {run.error && (
                                    <p className="text-[10px] text-red-400 mt-1 truncate" title={run.error}>
                                      {run.error}
                                    </p>
                                  )}
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
