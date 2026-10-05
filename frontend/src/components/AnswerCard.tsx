interface AnswerCardProps {
  data: any;
}

export default function AnswerCard({ data }: AnswerCardProps) {
  return (
    <div className="bg-white rounded-2xl p-8 shadow-sm ring-1 ring-slate-100">
      <div className="prose prose-slate max-w-none">
        <h2 className="text-xl font-medium text-slate-900 mb-4 leading-relaxed">
          {data.answer_text}
        </h2>
        
        {data.date_interpretation && (
          <div className="inline-flex items-center mt-4 px-3 py-1.5 rounded-lg bg-blue-50 text-blue-700 text-sm font-medium">
            <span className="opacity-70 mr-1.5">Dates:</span> 
            {data.date_interpretation}
          </div>
        )}
      </div>
    </div>
  );
}
