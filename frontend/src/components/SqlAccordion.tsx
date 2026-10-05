import { useState } from 'react';
import { ChevronDown, Database, Code2 } from 'lucide-react';

interface SqlAccordionProps {
  sql: string;
  explanation: string;
}

export default function SqlAccordion({ sql, explanation }: SqlAccordionProps) {
  const [isOpen, setIsOpen] = useState(true);

  return (
    <div className="h-full flex flex-col">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full px-5 py-4 flex items-center justify-between hover:bg-white/3 transition-all duration-200"
      >
        <div className="flex items-center gap-2.5 text-gray-300 font-semibold tracking-wider text-xs uppercase">
          <Database className="w-4 h-4 text-dg-primary flex-shrink-0" />
          Evidence &amp; Query
        </div>
        <ChevronDown
          className={`w-4 h-4 text-gray-500 transition-transform duration-300 ${isOpen ? 'rotate-180' : ''}`}
        />
      </button>

      <div
        className={`overflow-hidden transition-all duration-400 ease-in-out ${
          isOpen ? 'opacity-100' : 'max-h-0 opacity-0'
        }`}
      >
        <div className="px-5 pb-5 pt-1 space-y-5 border-t border-white/5">
          {/* Reasoning */}
          <div>
            <h4 className="flex items-center gap-2 text-[10px] font-bold text-dg-primary uppercase tracking-[0.18em] mb-2.5">
              <Code2 className="w-3.5 h-3.5" />
              Reasoning
            </h4>
            <p className="text-sm text-gray-300 leading-relaxed">
              {explanation || 'No explanation provided.'}
            </p>
          </div>

          {/* SQL */}
          <div>
            <h4 className="text-[10px] font-bold text-dg-accent uppercase tracking-[0.18em] mb-2.5">
              Generated SQL
            </h4>
            <div className="bg-black/70 rounded-xl p-4 overflow-x-auto border border-white/5 hover:border-white/10 transition-colors">
              <pre className="text-sm font-mono text-sky-300 leading-relaxed whitespace-pre-wrap break-words">
                <code>{sql || '-- No SQL generated'}</code>
              </pre>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
