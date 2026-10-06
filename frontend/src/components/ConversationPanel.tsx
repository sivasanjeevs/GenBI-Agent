import { MessageSquare, Clock, Database, ChevronRight } from 'lucide-react';

export interface ConversationTurn {
  question_id: string;
  question: string;
  answer_text: string;
  sql: string;
  row_count: number;
  elapsed_ms: number;
  date_interpretation?: string | null;
  explanation: string;
  trace: { attempts: number; repaired: boolean; abstained: boolean };
  chart?: any;
  follow_up_suggestions?: string[];
  columns?: string[];
  data?: any[];
  timestamp?: string;
}

interface ConversationPanelProps {
  turns: ConversationTurn[];
  activeId: string | null;
  onSelect: (turn: ConversationTurn) => void;
  onNewConversation: () => void;
}

export default function ConversationPanel({
  turns,
  activeId,
  onSelect,
  onNewConversation,
}: ConversationPanelProps) {
  if (turns.length === 0) return null;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 pt-5 pb-3 flex items-center justify-between border-b border-white/8">
        <div className="flex items-center gap-2">
          <MessageSquare className="w-4 h-4 text-dg-primary" />
          <span className="text-xs font-bold uppercase tracking-[0.15em] text-gray-400">
            Conversation
          </span>
        </div>
        <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-dg-primary/15 text-purple-300 border border-dg-primary/20">
          {turns.length} turn{turns.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Turn list */}
      <div className="flex-1 overflow-y-auto py-2 space-y-1 px-2">
        {turns.map((turn, idx) => {
          const isActive = turn.question_id === activeId;
          const isAbstained = turn.trace?.abstained;

          return (
            <button
              key={turn.question_id}
              onClick={() => onSelect(turn)}
              className={`w-full text-left rounded-xl px-3 py-3 transition-all duration-200 group relative overflow-hidden ${
                isActive
                  ? 'bg-dg-primary/15 border border-dg-primary/30 shadow-[0_0_12px_rgba(139,92,246,0.15)]'
                  : 'border border-transparent hover:bg-white/4 hover:border-white/10'
              }`}
            >
              {/* Turn number */}
              <div className="flex items-start gap-2.5">
                <span
                  className={`flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold mt-0.5 ${
                    isActive
                      ? 'bg-dg-primary text-white'
                      : 'bg-white/8 text-gray-500'
                  }`}
                >
                  {idx + 1}
                </span>

                <div className="flex-1 min-w-0">
                  {/* Question text — truncated to 2 lines */}
                  <p
                    className={`text-xs leading-relaxed font-medium line-clamp-2 ${
                      isActive ? 'text-white' : 'text-gray-300 group-hover:text-white'
                    } transition-colors`}
                  >
                    {turn.question}
                  </p>

                  {/* Meta badges */}
                  <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                    {/* Row count */}
                    <span className="flex items-center gap-1 text-[10px] text-gray-600">
                      <Database className="w-2.5 h-2.5" />
                      {isAbstained ? (
                        <span className="text-red-400/70">abstained</span>
                      ) : (
                        <span>{turn.row_count} row{turn.row_count !== 1 ? 's' : ''}</span>
                      )}
                    </span>

                    {/* Repaired badge */}
                    {turn.trace?.repaired && !isAbstained && (
                      <span className="text-[10px] text-amber-400/70">repaired</span>
                    )}

                    {/* Speed */}
                    {turn.elapsed_ms > 0 && (
                      <span className="flex items-center gap-1 text-[10px] text-gray-600">
                        <Clock className="w-2.5 h-2.5" />
                        {(turn.elapsed_ms / 1000).toFixed(1)}s
                      </span>
                    )}
                  </div>
                </div>

                {/* Active indicator */}
                <ChevronRight
                  className={`flex-shrink-0 w-3.5 h-3.5 mt-0.5 transition-all duration-200 ${
                    isActive ? 'text-dg-primary opacity-100' : 'text-gray-600 opacity-0 group-hover:opacity-60'
                  }`}
                />
              </div>
            </button>
          );
        })}
      </div>

      {/* Footer */}
      <div className="px-3 pb-4 pt-2 border-t border-white/8">
        <button
          onClick={onNewConversation}
          className="w-full py-2 rounded-xl border border-white/10 bg-white/3 text-gray-500 text-xs font-medium hover:bg-white/8 hover:text-gray-300 hover:border-white/20 transition-all duration-200 flex items-center justify-center gap-1.5"
        >
          <span className="text-base leading-none">+</span>
          New conversation
        </button>
      </div>
    </div>
  );
}
