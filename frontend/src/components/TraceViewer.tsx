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
    <div className="h-full p-6 flex flex-col justify-center items-center group relative overflow-hidden bg-dg-panel/30 hover:bg-dg-panel/50 transition-all duration-300">
      
      {/* Background decoration */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-48 h-48 bg-white/5 rounded-full blur-2xl group-hover:bg-dg-primary/10 transition-colors duration-500" />
      
      <h4 className="text-xs font-bold text-gray-400 uppercase tracking-[0.2em] mb-6 flex items-center relative z-10 w-full text-left">
        <Cpu className="w-4 h-4 mr-2" />
        Agent Execution Trace
      </h4>
      
      <div className="flex flex-col items-start space-y-4 w-full relative z-10 pl-2">
        {/* Step 1: Planned & Generated */}
        <div className="flex items-center text-sm font-semibold text-emerald-400 tracking-wide">
          <CheckCircle2 className="w-5 h-5 mr-3 drop-shadow-[0_0_8px_rgba(52,211,153,0.5)]" />
          Plan & SQL Generated
        </div>

        <div className="w-px h-6 bg-white/10 ml-2.5"></div>

        {/* Step 2: Execution / Repair */}
        {trace.abstained ? (
          <div className="flex items-center text-sm font-semibold text-red-400 tracking-wide">
            <AlertCircle className="w-5 h-5 mr-3 drop-shadow-[0_0_8px_rgba(248,113,113,0.5)]" />
            Execution Failed ({trace.attempts} attempts)
          </div>
        ) : trace.repaired ? (
          <div className="flex items-center text-sm font-semibold text-amber-400 tracking-wide">
            <Wrench className="w-5 h-5 mr-3 drop-shadow-[0_0_8px_rgba(251,191,36,0.5)]" />
            Auto-Repaired (Attempt {trace.attempts})
          </div>
        ) : (
          <div className="flex items-center text-sm font-semibold text-emerald-400 tracking-wide">
            <CheckCircle2 className="w-5 h-5 mr-3 drop-shadow-[0_0_8px_rgba(52,211,153,0.5)]" />
            Executed Successfully
          </div>
        )}
      </div>
    </div>
  );
}
