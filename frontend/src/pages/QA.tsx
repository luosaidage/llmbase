import { useState } from 'react';
import { Icon } from '../components/Icon';
import { Markdown } from '../components/Markdown';
import { Shimmer } from '../components/Loading';
import { api } from '../lib/api';

interface QAPair { question: string; answer: string; }

export function QA() {
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState('');
  const [loading, setLoading] = useState(false);
  const [fileBack, setFileBack] = useState(true);
  const [history, setHistory] = useState<QAPair[]>([]);

  async function ask(deep: boolean) {
    if (!question.trim() || loading) return;
    setLoading(true);
    setAnswer('');
    try {
      const res = await api.ask(question, deep, fileBack);
      setAnswer(res.answer);
      setHistory(prev => [{ question, answer: res.answer }, ...prev]);
    } catch (e) {
      setAnswer('Error: Failed to get response. Check API connection.');
    }
    setLoading(false);
  }

  return (
    <div className="p-8 max-w-[800px] mx-auto">
      <div className="mb-6">
        <p className="text-xs uppercase tracking-widest text-on-surface-variant mb-1">Editorial Intelligence</p>
        <h1 className="font-headline text-3xl font-bold">Curate Insights.</h1>
      </div>

      {/* Input */}
      <div className="bg-surface-container rounded-xl border border-outline-variant/30 p-5 mb-6">
        <textarea
          placeholder="Ask LLMBase anything about your curated wiki..."
          className="w-full bg-transparent text-on-surface placeholder:text-outline outline-none resize-none text-base font-body"
          rows={3}
          value={question}
          onChange={e => setQuestion(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(false); } }}
        />
        <div className="flex items-center justify-between mt-3 pt-3 border-t border-outline-variant/20">
          <label className="flex items-center gap-2 text-sm text-on-surface-variant cursor-pointer">
            <input
              type="checkbox"
              checked={fileBack}
              onChange={e => setFileBack(e.target.checked)}
              className="rounded border-outline-variant"
            />
            File answer to wiki
          </label>
          <div className="flex gap-2">
            <button
              onClick={() => ask(true)}
              disabled={loading}
              className="flex items-center gap-1.5 px-4 py-2 bg-secondary-container/20 text-secondary rounded-lg text-sm hover:bg-secondary-container/30 transition-colors disabled:opacity-50"
            >
              <Icon name="psychology" className="text-[16px]" /> Deep Research
            </button>
            <button
              onClick={() => ask(false)}
              disabled={loading}
              className="flex items-center gap-1.5 px-5 py-2 bg-primary text-on-primary rounded-lg text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-50"
            >
              Ask
            </button>
          </div>
        </div>
      </div>

      {/* Answer */}
      {loading && (
        <div className="bg-surface-container rounded-xl p-6 border border-outline-variant/20">
          <Shimmer lines={6} />
        </div>
      )}

      {answer && !loading && (
        <div className="bg-surface-container rounded-xl p-6 border border-outline-variant/20 mb-6">
          <div className="flex items-center gap-2 mb-4">
            <Icon name="auto_awesome" className="text-primary text-[18px]" />
            <span className="text-xs uppercase tracking-widest text-on-surface-variant">The Synthesis</span>
          </div>
          <Markdown content={answer} />
        </div>
      )}

      {/* History */}
      {history.length > 1 && (
        <div className="mt-8">
          <h3 className="text-xs uppercase tracking-widest text-on-surface-variant mb-3">Previous Queries</h3>
          <div className="space-y-2">
            {history.slice(1).map((h, i) => (
              <div
                key={i}
                className="bg-surface-low rounded-lg p-3 cursor-pointer hover:bg-surface-container transition-colors"
                onClick={() => { setQuestion(h.question); setAnswer(h.answer); }}
              >
                <p className="text-sm text-on-surface truncate">{h.question}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
