import { useState } from 'react';
import { ChevronDown, Database, Code } from 'lucide-react';

interface SqlAccordionProps {
  sql: string;
  explanation: string;
}

export default function SqlAccordion({ sql, explanation }: SqlAccordionProps) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="h-full flex flex-col group">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full px-6 py-5 flex items-center justify-between bg-dg-panel/30 hover:bg-dg-panel/70 transition-all duration-300"
      >
        <div className="flex items-center text-gray-200 font-semibold tracking-wide text-sm uppercase">
          <Database className="w-4 h-4 mr-3 text-dg-primary" />
          Evidence & Query
        </div>
        <ChevronDown 
          className={`w-5 h-5 text-gray-400 transition-transform duration-500 ease-[cubic-bezier(0.87,0,0.13,1)] ${isOpen ? 'rotate-180' : ''}`} 
        />
      </button>
      
      <div className={`transition-all duration-500 ease-[cubic-bezier(0.87,0,0.13,1)] overflow-hidden ${isOpen ? 'max-h-[1000px] opacity-100' : 'max-h-0 opacity-0'}`}>
        <div className="p-6 bg-dg-bg/50 border-t border-white/5 space-y-6">
          <div>
            <h4 className="text-xs font-bold text-dg-primary uppercase tracking-[0.2em] mb-3 flex items-center">
              <Code className="w-4 h-4 mr-2" />
              Reasoning
            </h4>
            <p className="text-sm text-gray-300 leading-relaxed font-medium">
              {explanation || "No explanation provided."}
            </p>
          </div>
          
          <div>
            <h4 className="text-xs font-bold text-dg-accent uppercase tracking-[0.2em] mb-3">Generated SQL</h4>
            <div className="bg-black/60 rounded-xl p-5 overflow-x-auto shadow-inner border border-white/5 relative group-hover:border-white/10 transition-colors">
              <pre className="text-sm font-mono text-blue-200 leading-relaxed">
                <code>{sql || "-- No SQL generated"}</code>
              </pre>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
