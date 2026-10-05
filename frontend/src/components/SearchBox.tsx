import { useState } from 'react';
import { Search, Loader2 } from 'lucide-react';

interface SearchBoxProps {
  onSearch: (q: string) => void;
  loading: boolean;
}

export default function SearchBox({ onSearch, loading }: SearchBoxProps) {
  const [val, setVal] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSearch(val);
  };

  return (
    <form onSubmit={handleSubmit} className="relative group">
      <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
        {loading ? (
          <Loader2 className="h-5 w-5 text-blue-400 animate-spin" />
        ) : (
          <Search className="h-5 w-5 text-slate-400 group-focus-within:text-blue-500 transition-colors" />
        )}
      </div>
      <input
        type="text"
        value={val}
        onChange={e => setVal(e.target.value)}
        disabled={loading}
        className="block w-full pl-12 pr-4 py-4 bg-white border-0 ring-1 ring-slate-200 rounded-2xl text-lg text-slate-900 placeholder-slate-400 focus:ring-2 focus:ring-blue-500 shadow-sm transition-all focus:shadow-md disabled:bg-slate-50 outline-none"
        placeholder="Ask a question about your data..."
      />
      <button
        type="submit"
        disabled={loading || !val.trim()}
        className="absolute inset-y-2 right-2 px-6 bg-gradient-to-r from-blue-600 to-cyan-500 hover:from-blue-500 hover:to-cyan-400 text-white rounded-xl font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-sm hover:shadow-md"
      >
        Ask
      </button>
    </form>
  );
}
