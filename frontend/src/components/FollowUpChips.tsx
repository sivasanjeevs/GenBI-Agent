import { Sparkles, ArrowRight } from 'lucide-react';

interface FollowUpChipsProps {
  suggestions: string[];
  onSelect: (q: string) => void;
  loading: boolean;
}

export default function FollowUpChips({ suggestions, onSelect, loading }: FollowUpChipsProps) {
  if (!suggestions || suggestions.length === 0) return null;

  return (
    <div className="mt-5 pt-4 border-t border-white/8">
      <div className="flex items-center gap-2 mb-3">
        <Sparkles className="w-3.5 h-3.5 text-dg-accent" />
        <span className="text-[10px] font-bold uppercase tracking-[0.15em] text-gray-500">
          Suggested follow-ups
        </span>
      </div>
      <div className="flex flex-col gap-2">
        {suggestions.map((suggestion, i) => (
          <button
            key={i}
            disabled={loading}
            onClick={() => onSelect(suggestion)}
            className="group w-full text-left px-4 py-2.5 rounded-xl border border-white/8 bg-white/3
              hover:bg-dg-primary/10 hover:border-dg-primary/30 hover:shadow-[0_0_12px_rgba(139,92,246,0.1)]
              disabled:opacity-40 disabled:cursor-not-allowed
              transition-all duration-200 flex items-center justify-between gap-3"
          >
            <span className="text-sm text-gray-400 group-hover:text-gray-200 transition-colors leading-snug">
              {suggestion}
            </span>
            <ArrowRight className="w-3.5 h-3.5 text-gray-600 group-hover:text-dg-primary flex-shrink-0 transition-colors duration-200 group-hover:translate-x-0.5" />
          </button>
        ))}
      </div>
    </div>
  );
}
