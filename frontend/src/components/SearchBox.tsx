import { useState, useRef, useEffect } from 'react';
import { Search, Loader2 } from 'lucide-react';

interface SearchBoxProps {
  onSearch: (q: string) => void;
  loading: boolean;
}

export default function SearchBox({ onSearch, loading }: SearchBoxProps) {
  const [val, setVal] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSearch(val);
    inputRef.current?.blur();
  };

  return (
    <form onSubmit={handleSubmit} className="relative group w-full max-w-4xl mx-auto">
      <div className="absolute inset-y-0 left-0 pl-6 flex items-center pointer-events-none z-20">
        {loading ? (
          <Loader2 className="h-6 w-6 text-dg-primary animate-spin" />
        ) : (
          <Search className="h-6 w-6 text-gray-400 group-focus-within:text-white transition-colors duration-300" />
        )}
      </div>
      
      {/* Outer glow effect on focus */}
      <div className="absolute inset-0 bg-gradient-to-r from-dg-primary to-dg-accent rounded-full opacity-0 group-focus-within:opacity-20 blur-xl transition-opacity duration-500" />
      
      <input
        ref={inputRef}
        type="text"
        value={val}
        onChange={e => setVal(e.target.value)}
        disabled={loading}
        className="relative block w-full pl-16 pr-32 py-5 sm:py-6 text-lg sm:text-xl bg-dg-panel/40 backdrop-blur-xl border border-white/10 rounded-full text-white placeholder-gray-400 focus:border-white/30 focus:bg-dg-panel/60 shadow-[0_8px_32px_rgba(0,0,0,0.5)] transition-all duration-300 disabled:opacity-50 outline-none"
        placeholder="Ask anything about your data..."
      />
      
      <button
        type="submit"
        disabled={loading || !val.trim()}
        className="absolute inset-y-2 right-2 sm:right-3 px-6 sm:px-8 bg-white text-black hover:bg-gray-100 rounded-full font-bold text-lg transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed shadow-[0_0_20px_rgba(255,255,255,0.2)] hover:shadow-[0_0_30px_rgba(255,255,255,0.4)] z-20 flex items-center gap-2"
      >
        <span>Generate</span>
      </button>
    </form>
  );
}
