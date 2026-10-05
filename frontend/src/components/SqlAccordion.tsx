import { useState } from 'react';
import { ChevronDown, Database, Code } from 'lucide-react';

interface SqlAccordionProps {
  sql: string;
  explanation: string;
}

export default function SqlAccordion({ sql, explanation }: SqlAccordionProps) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="bg-white rounded-2xl shadow-sm ring-1 ring-slate-100 overflow-hidden">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full px-6 py-4 flex items-center justify-between bg-slate-50/50 hover:bg-slate-50 transition-colors"
      >
        <div className="flex items-center text-slate-700 font-medium text-sm">
          <Database className="w-4 h-4 mr-2 text-slate-400" />
          Query Details & Evidence
        </div>
        <ChevronDown 
          className={`w-5 h-5 text-slate-400 transition-transform duration-300 ${isOpen ? 'rotate-180' : ''}`} 
        />
      </button>
      
      <div className={`transition-all duration-300 ease-in-out ${isOpen ? 'max-h-[800px] opacity-100' : 'max-h-0 opacity-0'}`}>
        <div className="p-6 border-t border-slate-100 space-y-6">
          <div>
            <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2 flex items-center">
              <Code className="w-3.5 h-3.5 mr-1.5" />
              Reasoning
            </h4>
            <p className="text-sm text-slate-600 leading-relaxed">
              {explanation || "No explanation provided."}
            </p>
          </div>
          
          <div>
            <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Generated SQL</h4>
            <div className="bg-slate-900 rounded-xl p-4 overflow-x-auto">
              <pre className="text-sm font-mono text-blue-300">
                <code>{sql || "-- No SQL generated"}</code>
              </pre>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
