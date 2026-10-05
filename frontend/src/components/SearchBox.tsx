import { useRef } from 'react';
import { Search, Loader2, Sparkles } from 'lucide-react';

interface SearchBoxProps {
  onSearch: (q: string) => void;
  loading: boolean;
  value: string;
  onChange: (val: string) => void;
}

export default function SearchBox({ onSearch, loading, value, onChange }: SearchBoxProps) {
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!value.trim()) return;
    onSearch(value);
    inputRef.current?.blur();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!value.trim()) return;
      onSearch(value);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="relative group w-full">
      {/* Outer glow on focus */}
      <div className="absolute -inset-px bg-gradient-to-r from-dg-primary to-dg-accent rounded-2xl opacity-0 group-focus-within:opacity-30 blur-lg transition-opacity duration-500 pointer-events-none" />

      <div className="relative bg-dg-panel/50 backdrop-blur-xl border border-white/10 rounded-2xl shadow-[0_8px_32px_rgba(0,0,0,0.5)] group-focus-within:border-white/25 transition-all duration-300">
        {/* Top row: icon + textarea */}
        <div className="flex items-start gap-3 px-5 pt-4 pb-2">
          <div className="mt-1 flex-shrink-0">
            {loading ? (
              <Loader2 className="h-5 w-5 text-dg-primary animate-spin" />
            ) : (
              <Search className="h-5 w-5 text-gray-500 group-focus-within:text-gray-300 transition-colors duration-300" />
            )}
          </div>
          <textarea
            ref={inputRef}
            rows={2}
            value={value}
            onChange={e => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={loading}
            className="flex-1 resize-none bg-transparent text-base text-white placeholder-gray-500 focus:outline-none leading-relaxed disabled:opacity-50 min-h-[3rem]"
            placeholder="Ask anything about your data... (Enter to send)"
          />
        </div>

        {/* Bottom row: hint + button */}
        <div className="flex items-center justify-between px-5 pb-3">
          <span className="text-xs text-gray-600 hidden sm:inline">Shift+Enter for new line</span>
          <button
            type="submit"
            disabled={loading || !value.trim()}
            className="ml-auto flex items-center gap-2 px-5 py-2 bg-white text-black hover:bg-gray-100 rounded-xl font-semibold text-sm transition-all duration-300 disabled:opacity-40 disabled:cursor-not-allowed shadow-[0_0_20px_rgba(255,255,255,0.15)] hover:shadow-[0_0_28px_rgba(255,255,255,0.3)]"
          >
            <Sparkles className="w-4 h-4" />
            Generate
          </button>
        </div>
      </div>
    </form>
  );
}
