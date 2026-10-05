interface AnswerCardProps {
  data: any;
}

export default function AnswerCard({ data }: AnswerCardProps) {
  return (
    <div className="relative p-7 overflow-hidden group">
      {/* Subtle ambient glows */}
      <div className="absolute top-0 right-0 w-64 h-64 bg-dg-primary/8 rounded-full blur-[80px] -translate-y-1/2 translate-x-1/2 pointer-events-none" />
      <div className="absolute bottom-0 left-0 w-64 h-64 bg-dg-accent/8 rounded-full blur-[80px] translate-y-1/2 -translate-x-1/2 pointer-events-none" />

      <div className="relative z-10">
        {/* Answer text — reduced from text-2xl/3xl to text-lg/xl */}
        <p className="text-lg md:text-xl font-normal text-gray-100 leading-relaxed tracking-normal">
          {data.answer_text}
        </p>

        {/* Chart — dark themed */}
        {data.chart && data.chart.image_base64 && (
          <div className="mt-6 rounded-xl overflow-hidden border border-white/8 bg-[#0d1117] shadow-xl flex justify-center p-5 hover:border-white/15 transition-colors">
            <img
              src={`data:image/png;base64,${data.chart.image_base64}`}
              alt={data.chart.title || 'Generated Chart'}
              className="max-w-full h-auto rounded-lg object-contain"
              style={{ filter: 'invert(0) hue-rotate(0deg) brightness(0.95)' }}
            />
          </div>
        )}

        {/* Date interpretation badge */}
        {data.date_interpretation && (
          <div className="inline-flex items-center gap-2 mt-5 px-3 py-1.5 rounded-full border border-dg-accent/25 bg-dg-accent/8 text-blue-300 text-xs font-medium tracking-wide">
            <span className="opacity-60 uppercase text-[10px]">Dates:</span>
            {data.date_interpretation}
          </div>
        )}
      </div>
    </div>
  );
}
