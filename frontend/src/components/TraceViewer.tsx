import { CheckCircle2, Wrench, AlertCircle } from 'lucide-react';

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
    <div className="flex items-center space-x-3 px-2">
      {/* Step 1: Planned & Generated */}
      <div className="flex items-center text-sm font-medium text-emerald-600">
        <CheckCircle2 className="w-4 h-4 mr-1.5" />
        Plan & SQL Generated
      </div>

      <div className="w-8 h-px bg-slate-200"></div>

      {/* Step 2: Execution / Repair */}
      {trace.abstained ? (
        <div className="flex items-center text-sm font-medium text-red-500">
          <AlertCircle className="w-4 h-4 mr-1.5" />
          Execution Failed ({trace.attempts} attempts)
        </div>
      ) : trace.repaired ? (
        <div className="flex items-center text-sm font-medium text-amber-600">
          <Wrench className="w-4 h-4 mr-1.5" />
          Auto-Repaired (Attempt {trace.attempts})
        </div>
      ) : (
        <div className="flex items-center text-sm font-medium text-emerald-600">
          <CheckCircle2 className="w-4 h-4 mr-1.5" />
          Executed Successfully
        </div>
      )}
    </div>
  );
}
