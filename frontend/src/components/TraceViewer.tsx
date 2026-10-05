import { CheckCircle2, Wrench, AlertCircle, Cpu } from 'lucide-react';

interface TraceViewerProps {
  trace: {
    attempts: number;
    repaired: boolean;
    abstained: boolean;
  };
}

export default function TraceViewer({ trace }: TraceViewerProps) {
  if (!trace) return null;

  return (
    <div className="h-full p-5 flex flex-col group relative overflow-hidden hover:bg-white/2 transition-all duration-300">

      <h4 className="flex items-center gap-2 text-[10px] font-bold text-gray-500 uppercase tracking-[0.18em] mb-5">
        <Cpu className="w-3.5 h-3.5" />
        Agent Execution Trace
      </h4>

      <div className="flex flex-col items-start gap-0 w-full">

        {/* Step 1 */}
        <div className="flex items-center gap-2.5 text-xs font-semibold text-emerald-400">
          <CheckCircle2 className="w-4 h-4 flex-shrink-0 drop-shadow-[0_0_6px_rgba(52,211,153,0.5)]" />
          Plan &amp; SQL Generated
        </div>

        {/* Connector line */}
        <div className="w-px h-5 bg-white/10 ml-2" />

        {/* Step 2 */}
        {trace.abstained ? (
          <div className="flex items-center gap-2.5 text-xs font-semibold text-red-400">
            <AlertCircle className="w-4 h-4 flex-shrink-0 drop-shadow-[0_0_6px_rgba(248,113,113,0.5)]" />
            Failed after {trace.attempts} attempt{trace.attempts !== 1 ? 's' : ''}
          </div>
        ) : trace.repaired ? (
          <div className="flex items-center gap-2.5 text-xs font-semibold text-amber-400">
            <Wrench className="w-4 h-4 flex-shrink-0 drop-shadow-[0_0_6px_rgba(251,191,36,0.5)]" />
            Auto-Repaired (Attempt {trace.attempts})
          </div>
        ) : (
          <div className="flex items-center gap-2.5 text-xs font-semibold text-emerald-400">
            <CheckCircle2 className="w-4 h-4 flex-shrink-0 drop-shadow-[0_0_6px_rgba(52,211,153,0.5)]" />
            Executed Successfully
          </div>
        )}

        {/* Connector line */}
        <div className="w-px h-5 bg-white/10 ml-2" />

        {/* Step 3: Attempts info */}
        <div className="flex items-center gap-2.5 text-xs text-gray-500">
          <span className="w-4 h-4 rounded-full border border-white/10 flex-shrink-0 flex items-center justify-center text-[9px] font-bold text-gray-600">
            {trace.attempts}
          </span>
          {trace.attempts === 1 ? '1 attempt' : `${trace.attempts} total attempts`}
        </div>

      </div>
    </div>
  );
}
