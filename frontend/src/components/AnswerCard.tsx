interface AnswerCardProps {
  data: any;
}

export default function AnswerCard({ data }: AnswerCardProps) {
  return (
    <div className="relative p-8 overflow-hidden group">
      {/* Dynamic background glow */}
      <div className="absolute top-0 right-0 w-[300px] h-[300px] bg-dg-primary/10 rounded-full blur-[80px] -translate-y-1/2 translate-x-1/2" />
      <div className="absolute bottom-0 left-0 w-[300px] h-[300px] bg-dg-accent/10 rounded-full blur-[80px] translate-y-1/2 -translate-x-1/2" />
      
      <div className="relative z-10">
        <h2 className="text-2xl md:text-3xl font-medium text-white mb-6 leading-relaxed tracking-wide">
          {data.answer_text}
        </h2>
        
        {data.chart && data.chart.image_base64 && (
          <div className="mt-8 rounded-2xl overflow-hidden border border-white/10 bg-black/40 backdrop-blur-md shadow-xl flex justify-center p-6 hover:border-white/20 transition-colors">
            <img 
              src={`data:image/png;base64,${data.chart.image_base64}`} 
              alt={data.chart.title || "Generated Chart"}
              className="max-w-full h-auto rounded-lg object-contain"
            />
          </div>
        )}
        
        {data.date_interpretation && (
          <div className="inline-flex items-center mt-6 px-4 py-2 rounded-full border border-dg-accent/30 bg-dg-accent/10 text-blue-300 text-sm font-semibold tracking-wider backdrop-blur-md shadow-[0_0_15px_rgba(59,130,246,0.15)]">
            <span className="opacity-70 mr-2 uppercase text-xs">Dates interpreted:</span> 
            {data.date_interpretation}
          </div>
        )}
      </div>
    </div>
  );
}
